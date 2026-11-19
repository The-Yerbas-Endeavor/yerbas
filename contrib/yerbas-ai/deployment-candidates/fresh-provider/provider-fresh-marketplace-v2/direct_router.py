"""Fresh-host direct worker entry point; never consult migration-era policies.

Use only in a new installation. Existing hosts retain their migration router.
The executor remains responsible for credentials, hashes, deadlines and locks.
"""
import argparse
import os
from pathlib import Path
import stat
import sys

POLICY = '/etc/yerbas-ai/provider-direct-cupti-v1.json'
SELECTOR = '/etc/yerbas-ai/provider-direct-cupti-mode.json'


def permitted(selector, retained, replay):
    if (type(selector) is not dict or set(selector) != {'enabled'}
            or type(selector['enabled']) is not bool
            or type(retained) is not bool or type(replay) is not bool):
        raise ValueError('Explicit enabled flag and recovery state required')
    if replay:
        if not retained:
            raise ValueError('Replay requires retained state')
    elif not selector['enabled']:
        raise ValueError('Training disabled pending enrollment and acceptance')


def main():
    from provider_executor import (read_json, verify_policy, validate_request,
                                   require_root_ancestry, require_service_boundary)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--replay-only', action='store_true')
    args = parser.parse_args()
    uid = os.getuid()
    if uid == 0:
        raise ValueError('Dedicated non-root provider required')
    require_root_ancestry(POLICY)
    policy = verify_policy(read_json(POLICY, owner=0))
    if policy['schema'] != 3 or policy['measurement'] != 'direct-cupti-v1':
        raise ValueError('Fresh installation requires the pinned direct collector')
    if policy['provider_uid'] != uid or os.path.realpath(policy['python']) != os.path.realpath(sys.executable):
        raise ValueError('Provider account or interpreter differs')
    request = validate_request(read_json(args.request, owner=uid))
    require_service_boundary(request['run_id'], replay_only=args.replay_only)
    require_root_ancestry(SELECTOR)
    selector = read_json(SELECTOR, owner=0)
    root = Path(policy['state'])
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077:
        raise ValueError('Private provider state directory required')
    retained = root / (request['run_id'] + '-' + request['contribution'])
    exists = os.path.lexists(retained)
    if exists:
        info = retained.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077:
            raise ValueError('Unsafe retained state')
    permitted(selector, exists, args.replay_only)
    command = [policy['python'], '-B', str(Path(__file__).with_name('provider_executor.py')),
               '--policy', POLICY, '--request', str(args.request)]
    if args.replay_only:
        command.append('--replay-only')
    os.execv(command[0], command)


if __name__ == '__main__':
    main()
