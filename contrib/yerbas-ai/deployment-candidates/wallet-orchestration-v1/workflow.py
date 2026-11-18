"""Durable owner workflow; adapters enforce proof, execution and payment policy.

An interrupted effect is reconciliation-only. This module never interprets an
absent reply as permission to retry GPU execution, signing or broadcasting.
"""
import fcntl
import hashlib
import json
import os
import re
import stat
from pathlib import Path


STEPS = ('bind', 'accept', 'execute', 'collect', 'verify', 'prepare_payment',
         'preview_payment', 'pay', 'confirm_payment', 'release')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode()


def validate_request(request):
    fields = {'schema', 'network', 'quote', 'assignment', 'terms_sha256',
              'deposit_txid', 'deposit_vout', 'maximum_base_units',
              'provider_reward_base_units', 'slot', 'automatic_settlement'}
    if type(request) is not dict or set(request) != fields:
        raise ValueError('Exact wallet authorization required')
    for key, size in (('quote', 32), ('assignment', 32), ('terms_sha256', 64),
                      ('deposit_txid', 64)):
        if type(request[key]) is not str or not re.fullmatch('[a-f0-9]{%d}' % size, request[key]):
            raise ValueError('Invalid wallet binding')
    if (type(request['schema']) is not int or request['schema'] != 1 or
            request['network'] != 'yerbas-private-reduced-collateral-testnet' or
            type(request['deposit_vout']) is not int or not 0 <= request['deposit_vout'] <= 65535 or
            type(request['maximum_base_units']) is not int or request['maximum_base_units'] != 101000 or
            type(request['provider_reward_base_units']) is not int or request['provider_reward_base_units'] != 100000 or
            request['slot'] != 'gpu-1' or request['automatic_settlement'] is not True):
        raise ValueError('Enrolled single-unit testnet authorization required')
    return hashlib.sha256(canonical(request)).hexdigest()


class ReconciliationRequired(RuntimeError):
    pass


class Journal:
    def __init__(self, directory):
        self.directory = Path(directory)
        s = self.directory.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077:
            raise ValueError('Private owner workflow directory required')

    def read(self, name):
        path = self.directory / name
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, 'rb') as stream:
            s = os.fstat(stream.fileno())
            if (not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or
                    s.st_mode & 0o077 or s.st_nlink != 1 or s.st_size > 1048576):
                raise ValueError('Invalid private workflow record')
            return json.load(stream)

    def retain(self, name, value):
        raw = canonical(value)
        if len(raw) > 1048576:
            raise ValueError('Bounded workflow record required')
        fd = os.open(self.directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def run(self, request, adapter):
        binding = validate_request(request)
        fd = os.open(self.directory / 'workflow.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            s = os.fstat(fd)
            if not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077 or s.st_nlink != 1:
                raise ValueError('Invalid workflow lock')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            old = self.read('authorization.json')
            if old is None:
                # Read-only adapter must check native funding, available credit,
                # current authority, GPU reservation and the exact assignment.
                adapter.preflight(request)
                self.retain('authorization.json', request)
            elif old != request:
                raise ValueError('Retained wallet authorization differs')
            results = {}
            for step in STEPS:
                intent_name, result_name = step + '-intent.json', step + '-result.json'
                intent, result = self.read(intent_name), self.read(result_name)
                expected = dict(step=step, authorization_sha256=binding)
                if intent is not None and intent != expected:
                    raise ValueError('Workflow intent differs')
                if result is not None:
                    if intent is None or set(result) != {'authorization_sha256', 'value'} or result['authorization_sha256'] != binding:
                        raise ValueError('Workflow result differs')
                    results[step] = result['value']
                    continue
                if intent is not None:
                    raise ReconciliationRequired(step + ' has no confirmed reply; no automatic retry')
                # Each adapter rechecks current proof/lease/funding immediately
                # before an effect. Retention occurs before calling it.
                self.retain(intent_name, expected)
                value = adapter.perform(step, request, dict(results))
                self.retain(result_name, dict(authorization_sha256=binding, value=value))
                results[step] = value
            return results
        finally:
            os.close(fd)
