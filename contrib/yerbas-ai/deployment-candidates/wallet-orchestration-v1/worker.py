"""Owner workflow worker. It survives the wallet closing; uncertain effects stop."""
import json
import os
from pathlib import Path
import re
import sys
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from workflow import Journal
from control import ROOT
sys.path.insert(0, str(HERE.parent / 'wallet-rental-service-v1'))
from context import Context
from orchestration import Adapter


def main():
    os.umask(0o077)
    if len(sys.argv) != 2 or not re.fullmatch('[a-f0-9]{32}', sys.argv[1]):
        raise ValueError('Exact retained wallet quote required')
    directory = ROOT / sys.argv[1]
    journal = Journal(directory)
    request = journal.read('launch-intent.json')
    if not request or request['quote'] != sys.argv[1]:
        raise ValueError('Retained wallet authorization required')
    (directory / 'commands').mkdir(mode=0o700, exist_ok=True)
    Journal(directory / 'commands')
    fd = os.open(directory / 'lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    context = Context(request['quote'], directory)
    try:
        result = journal.run(request, Adapter(context))
        journal.retain('complete.json', dict(passed=True, result=result['release']))
    except Exception as error:
        # Exact private error retained locally; the wallet never interprets
        # this failure as permission for another deposit or another launch.
        journal.retain('attention.json', dict(error=str(error), automatic_retry=False))
        raise


if __name__ == '__main__':
    main()
