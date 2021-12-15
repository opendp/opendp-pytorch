import os

import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset

from utilities import printf, ModelCoordinator, main
from pums_downloader import download_pums_data, get_pums_data_path, datasets

from opendp.network.odometer import assert_release_binary
from opendp.network.odometer_reconstruction import ReconstructionPrivacyOdometer


assert_release_binary()

# distributed learning implemented via sequential point-to-point communication
# this is too slow to be practically useful


TRAIN_PUBLIC = False

# defaults to predicting ambulatory difficulty based on age, weight and cognitive difficulty
ACTIVE_PROBLEM = 'ambulatory'

problem = {
    'ambulatory': {
        'description': 'predict ambulatory difficulty based on age, weight and cognitive difficulty',
        'predictors': ['AGEP', 'PWGTP', 'DREM'],
        'target': 'DPHY'
    },
    'marital': {
        'description': 'predict marital status as a function of income and education',
        'predictors': ['PERNP', 'SCHL'],
        'target': 'MAR'
    },
    'medicare': {
        'description': 'predict medicare status based on mode of transporation to work (JWTR), '
                       'hours worked per week (WKHP), and number of weeks worked in past 12 months (WKW)',
        'predictors': ['JWTR', 'WKHP', 'WKW'],
        'target': 'HINS4'
    }
}[ACTIVE_PROBLEM]


def load_pums(dataset):
    download_pums_data(**dataset)
    data_path = get_pums_data_path(**dataset)

    data = pd.read_csv(
        data_path,
        nrows=50 if dataset['public'] else None,
        usecols=problem['predictors'] + [problem['target']],
        engine='python')
    data.dropna(inplace=True)
    if ACTIVE_PROBLEM == 'marital':
        data['MAR'] = (data['MAR'] == 1) + 1
    return TensorDataset(
        torch.from_numpy(data[problem['predictors']].to_numpy()).type(torch.float32),
        torch.from_numpy(data[problem['target']].to_numpy()).type(torch.LongTensor) - 1)


class PumsModule(nn.Module):

    def __init__(self, input_size, output_size):
        """
        Example NN module
        :param input_size:
        :param output_size:
        """
        super().__init__()
        internal_size = 5
        self.linear1 = nn.Linear(input_size, internal_size)
        self.linear2 = nn.Linear(internal_size, output_size)

    def forward(self, x):
        x = self.linear1(x)
        x = F.relu(x)
        x = self.linear2(x)
        return x

    def loss(self, batch):
        inputs, targets = batch
        outputs = self(inputs)
        return F.cross_entropy(outputs, targets)

    def score(self, batch):
        with torch.no_grad():
            inputs, targets = batch
            outputs = self(inputs)
            loss = F.cross_entropy(outputs, targets)
            pred = torch.argmax(outputs, dim=1)
            accuracy = torch.sum(pred == targets) / len(pred)
            return [accuracy, loss]


def evaluate(model, loader):
    """Compute average of scores on each batch (unweighted by batch size)"""
    return torch.mean(torch.tensor([model.score(batch) for batch in loader]), dim=0)


def train(
        model, optimizer, private_step_limit,
        train_loader, test_loader,
        coordinator, odometer,
        rank, public):

    history = []
    epoch = 0 if TRAIN_PUBLIC else 1
    while True:
        for batch in train_loader:

            if not public or epoch != 0:
                # synchronize weights with the previous worker
                coordinator.recv()

            if coordinator.step == private_step_limit:
                return history

            loss = model.loss(batch)
            loss.backward()

            optimizer.step()
            optimizer.zero_grad()

            # send weights to the next worker
            if not public or epoch != 0:
                coordinator.send()

            accuracy, loss = evaluate(model, test_loader)
            history.append({
                'rank': rank, 'step': coordinator.step.item(), 'loss': loss.item(), 'accuracy': accuracy.item()
            })
            printf(f"{rank: 4d} | {epoch: 5d} | {accuracy.item():.2f}     | {loss.item():.2f}", force=True)

        # privacy book-keeping
        epoch += 1
        if not public:
            odometer.steps = len(train_loader)
            odometer.increment_epoch()


def run_pums_worker(rank, size, private_step_limit=None, federation_scheme='shuffle', queue=None, model_filepath=None, end_event=None):
    """
    Perform federated learning over pums data

    :param rank: index for specific data set
    :param size: total ring size
    :param federation_scheme:
    :param private_step_limit:
    :param queue: stores values and privacy usage
    :param model_filepath: indicating where to save the model checkpoint
    :return:
    """

    public = datasets[rank]['public']

    # load train data specific to the current rank
    train_loader = DataLoader(load_pums(datasets[rank]), batch_size=1, shuffle=True)
    test_loader = DataLoader(load_pums(datasets[1]), batch_size=1000)

    model = PumsModule(len(problem['predictors']), 2)

    odometer = ReconstructionPrivacyOdometer(step_epsilon=.1)
    if not public:
        odometer.track_(model)
    coordinator = ModelCoordinator(model, rank, size, private_step_limit, federation_scheme, end_event=end_event)

    optimizer = torch.optim.SGD(model.parameters(), .00005)

    history = train(
        model, optimizer,
        private_step_limit,
        train_loader, test_loader,
        coordinator, odometer,
        rank, public)

    # Only save if filename is given
    if rank == size - 1 and model_filepath:
        torch.save({
            'model_state_dict': model.state_dict(),
            'optimizer_state_dict': optimizer.state_dict(),
            'loss': evaluate(model, test_loader)
        }, model_filepath)

    if queue:
        queue.put((tuple(datasets[rank].values()), odometer.compute_usage(), history))


if __name__ == "__main__":
    # Model checkpoints will be saved here
    model_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'model_checkpoints', 'p2p_pums')
    if not os.path.exists(model_path):
        os.mkdir(model_path)

    print("Rank | Epoch | Accuracy | Loss")
    main(worker=run_pums_worker,
         n_workers=len(datasets),
         private_step_limit=40,
         model_filepath=os.path.join(model_path, 'model.pt'),
         federation_scheme='shuffle')
