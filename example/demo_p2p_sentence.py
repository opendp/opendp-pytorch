import os

import numpy as np
import torch

from sentence_module import SentenceModule
from utilities import ModelCoordinator, main, printf

from opendp.network.odometer import assert_release_binary
from opendp.network.odometer_reconstruction import ReconstructionPrivacyOdometer

assert_release_binary()


def run_lstm_worker(
        rank, size,
        epoch_limit=None, private_step_limit=None,
        federation_scheme='shuffle', queue=None,
        model_filepath=None, end_event=None
):
    """
    Perform federated learning in a ring structure
    :param rank: index for specific data set
    :param size: total ring size
    :param epoch_limit: maximum number of epochs
    :param private_step_limit: maximum number of private steps
    :param federation_scheme: how to choose the next worker
    :param queue: stores values and privacy accountant usage
    :param model_filepath: indicating where to save the model checkpoint
    :return:
    """

    # Every node gets same data for now
    EMBEDDING_SIZE = 6
    HIDDEN_SIZE = 7

    training_data = [
        ("The dog ate the apple".split(), ["DET", "NN", "V", "DET", "NN"]),
        ("Everybody read that book".split(), ["NN", "V", "DET", "NN"])
    ]

    idx_to_tag = ['DET', 'NN', 'V']
    tag_to_idx = {'DET': 0, 'NN': 1, 'V': 2}

    word_to_idx = {}
    for sent, tags in training_data:
        for word in sent:
            if word not in word_to_idx:
                word_to_idx[word] = len(word_to_idx)

    def prepare_sequence(seq, to_idx):
        """Convert sentence/sequence to torch Tensors"""
        idxs = [to_idx[w] for w in seq]
        return torch.LongTensor(idxs)

    model = SentenceModule(
        vocab_size=len(word_to_idx),
        embedding_size=EMBEDDING_SIZE,
        hidden_size=HIDDEN_SIZE,
        tagset_size=len(tag_to_idx),
        bahdanau=False)

    odometer = ReconstructionPrivacyOdometer(step_epsilon=1.0, reduction='sum')
    odometer.track_(model)
    coordinator = ModelCoordinator(model, rank, size, federation_scheme, end_event=end_event)

    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)

    for epoch in range(epoch_limit):
        coordinator.recv()

        for sentence, tags in training_data:
            # sentence1 = prepare_sequence(training_data[0][0][:4], word_to_idx)
            # sentence2 = prepare_sequence(training_data[1][0][:4], word_to_idx)
            # sentence = torch.stack([
            #     sentence1,
            #     sentence2
            # ])
            # print(sentence.shape)
            #
            # target1 = prepare_sequence(training_data[0][1][:4], tag_to_idx)
            # target2 = prepare_sequence(training_data[1][1][:4], tag_to_idx)
            # target = torch.stack([
            #     target1,
            #     target2
            # ])
            # print(target.shape)
            sentence = prepare_sequence(sentence, word_to_idx)
            target = prepare_sequence(tags, tag_to_idx)

            loss = model.loss(sentence, target)
            loss.backward()
            optimizer.step()
            optimizer.zero_grad()
        odometer.increment_epoch()

        inputs = prepare_sequence(training_data[0][0], word_to_idx)
        tag_scores = model(inputs).detach().numpy()

        tag = [idx_to_tag[idx] for idx in np.argmax(tag_scores[0], axis=1)]
        printf(f"{rank: 4d} | {epoch: 5d} | {tag}     | {training_data[0][1]}", force=True)

        # Ensure that send() does not happen on the last epoch of the last node,
        # since this would send back to the first node (which is done) and hang
        if rank == size - 1 and epoch == epoch_limit - 1:
            # Only save if filename is given
            if model_filepath:
                torch.save({
                    'epoch': epoch,
                    'model_state_dict': model.state_dict(),
                    'optimizer_state_dict': optimizer.state_dict(),
                    'loss': loss
                }, model_filepath)
        else:
            coordinator.send()


if __name__ == "__main__":
    model_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'model_checkpoints', 'p2p_lstm')
    os.makedirs(model_path, exist_ok=True)

    print("Rank | Epoch | Predicted | Actual")
    main(worker=run_lstm_worker,
         n_workers=2,
         epoch_limit=1000,
         model_filepath=os.path.join(model_path, 'model.pt'),
         federation_scheme='shuffle')
