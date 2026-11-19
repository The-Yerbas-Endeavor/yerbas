"""Journaled create-only phases. No services, enrollment or automatic retry.

Caller supplies a verified root/home directory handle after host preflight.
This module deliberately exposes no live-install command.
"""
import hashlib
import os
from pathlib import PurePosixPath
import sys
from pathlib import Path
_legacy = Path(__file__).resolve().parent.parent/'provider-fresh-host-candidate-v1'
if _legacy.is_dir():sys.path.insert(0,str(_legacy))
from guarded_writer import Writer, DIR_FLAGS, parts, trusted
from install_journal import canonical


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def phases(owner_uid, owner_gid, provider_uid, provider_gid, home, hostname):
    from compose import compose
    plan = compose(owner_uid, owner_gid, provider_uid, provider_gid, home, hostname)
    result = {name: dict(files={}, directories={}) for name in ('root', 'owner')}
    owner_base = PurePosixPath(home)
    for kind in ('files', 'directories'):
        for name, entry in plan[kind].items():
            path = PurePosixPath(name)
            is_owner = path.is_relative_to(owner_base)
            relative = str(path.relative_to(owner_base if is_owner else '/'))
            parts(relative)
            result['owner' if is_owner else 'root'][kind][relative] = entry
    return dict(schema=1, phases=result, phase_sha256={k:digest(v) for k,v in result.items()},
                activate_services=False, submissions_enabled=False,
                automatic_retry=False, fresh_host_acceptance=False)


def preflight(root_fd, phase, expected_digest, staging_uid):
    if digest(phase) != expected_digest:
        raise ValueError('Phase differs from reviewed plan')
    if set(phase) != {'files', 'directories'}:
        raise ValueError('Unexpected phase fields')
    trusted(root_fd, staging_uid)
    files, directories = phase['files'], phase['directories']
    if set(files) & set(directories):
        raise ValueError('Conflicting target kinds')
    for name, entry in files.items():
        parts(name)
        raw = bytes.fromhex(entry['content_hex'])
        if hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError('Planned content hash differs')
    # Walk existing ancestors through handles, never through symlinks. Missing
    # ancestors must be explicit planned directories; never adopt existing state.
    for name in sorted(set(files) | set(directories)):
        components = parts(name)
        fd = os.dup(root_fd)
        try:
            missing = False
            for index, component in enumerate(components):
                prefix = '/'.join(components[:index+1])
                last = index == len(components)-1
                if missing:
                    if not last and prefix not in directories:
                        raise ValueError('Unplanned missing parent: '+prefix)
                    continue
                try:
                    info = os.stat(component, dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    if not last and prefix not in directories:
                        raise ValueError('Required existing parent absent: '+prefix)
                    missing = True
                    continue
                if last or prefix in directories:
                    raise ValueError('Existing target preserved: '+prefix)
                child = os.open(component, DIR_FLAGS, dir_fd=fd)
                try:
                    trusted(child, staging_uid)
                except BaseException:
                    os.close(child)
                    raise
                os.close(fd); fd = child
        finally:
            os.close(fd)


def stage(root_fd, phase, expected_digest, journal, staging_uid):
    preflight(root_fd, phase, expected_digest, staging_uid)
    writer = Writer(root_fd, staging_uid, journal)
    try:
        for name, entry in sorted(phase['directories'].items(), key=lambda item:(item[0].count('/'),item[0])):
            writer.mkdir(name, entry['mode'])
        for name, entry in sorted(phase['files'].items()):
            writer.write(name, bytes.fromhex(entry['content_hex']), entry['sha256'], entry['mode'])
        metadata = {name:{k:entry[k] for k in ('uid','gid','mode')}
                    for kind in ('directories','files') for name,entry in phase[kind].items()}
        writer.finalize(metadata)
        return dict(staged=True, entries=len(metadata), services_started=False,
                    gpu_started=False, automatic_retry=False)
    finally:
        writer.close()
