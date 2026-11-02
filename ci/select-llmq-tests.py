"""Skip expensive quorum tests only for changes known to be unrelated."""
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess


def relevant(path):
    # Build definitions can affect consensus even when stored beside UI code.
    name = PurePosixPath(path).name
    if name.startswith(('Makefile', 'CMakeLists')) or name.endswith(('.mk', '.cmake', '.pro', '.pri')):
        return True
    # Everything not explicitly excluded runs the suite, including new core
    # directories, dependencies, CI, functional tests and unknown root files.
    return not (path.startswith(('src/qt/', 'contrib/yerbas-ai/', 'doc/', 'docs/'))
                or path in ('README.md', 'COPYING', 'CONTRIBUTING.md'))


def select(event_name, event, git):
    if event_name == 'workflow_dispatch' or event.get('ref', '').startswith('refs/tags/'):
        return True, 'release tag or manual run'
    try:
        if event_name == 'pull_request':
            base = event['pull_request']['base']['sha']
            head = event['pull_request']['head']['sha']
        elif event_name == 'push':
            base, head = event['before'], event['after']
        else:
            return True, 'unrecognized event'
        if not all(re.fullmatch(r'[0-9a-f]{40}', value) and value != '0' * 40 for value in (base, head)):
            return True, 'missing comparison history'
        if event_name == 'pull_request':
            base = git(['merge-base', base, head]).decode().strip()
        paths = git(['diff', '--name-only', '--no-renames', '-z', base, head, '--']).decode().split('\0')
        if any(relevant(path) for path in paths if path):
            return True, 'core, build, test or unclassified changes'
        return False, 'only UI, AI support or documentation changes'
    except (KeyError, TypeError, ValueError, UnicodeError, subprocess.SubprocessError, OSError):
        return True, 'comparison unavailable; run conservatively'


def main():
    try:
        event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    except (KeyError, ValueError, OSError):
        event = {}
    run, reason = select(os.environ.get('GITHUB_EVENT_NAME', ''), event,
                         lambda args: subprocess.check_output(['git', *args], timeout=60))
    print(json.dumps({'run_llmq': run, 'reason': reason}))
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write('run=' + str(run).lower() + '\n')


if __name__ == '__main__':
    main()
