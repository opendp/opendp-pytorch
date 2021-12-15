import argparse
import os
import subprocess
import sys


def log(message, command=False):
    prefix = "$" if command else "#"
    print(f"{prefix} {message}", file=sys.stderr)


def run_command(description, args, capture_output=True, shell=True):
    if description:
        log(description)
    printed_args = args.join(" ") if type(args) == list else args
    log(printed_args, command=True)
    stdout = subprocess.PIPE if capture_output else None
    completed_process = subprocess.run(args, stdout=stdout, shell=shell, check=True, encoding="utf-8")
    return completed_process.stdout.rstrip() if capture_output else None


def python(args):
    log(f"*** PUBLISHING PYTHON LIBRARY ***")
    # https://pypi.org/help/#apitoken
    os.environ["TWINE_USERNAME"] = "__token__"
    os.environ["TWINE_PASSWORD"] = os.environ["PYPI_API_TOKEN"]
    dry_run_arg = " --repository testpypi" if args.dry_run else ""
    run_command("Publishing opendp package", f"python3 -m twine upload{dry_run_arg} --verbose --skip-existing python/wheelhouse/*")


def _main(argv):
    parser = argparse.ArgumentParser(description="OpenDP build tool")
    subparsers = parser.add_subparsers(dest="COMMAND", help="Command to run")
    subparsers.required = True

    subparser = subparsers.add_parser("python", help="Publish Python library")
    subparser.set_defaults(func=python)
    subparser.add_argument("-n", "--dry-run", dest="dry_run", action="store_true", default=False)
    subparser.add_argument("-nn", "--no-dry-run", dest="dry_run", action="store_false")

    args = parser.parse_args(argv[1:])
    args.func(args)


def main():
    _main(sys.argv)


if __name__ == "__main__":
    main()
