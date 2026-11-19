"""Validate proposed collector JSONL diagnostics; never authorize GPU rewards.

This is an offline protocol prototype. No deployed collector emits it yet.
Even a structurally valid transcript cannot prove the collector told the truth.
"""
import argparse
import json
from pathlib import Path
import re

MAX_BYTES = 8 * 1024 * 1024
MAX_EVENTS = 50000
IDENTITY_FIELDS = {'run_id', 'runtime_sha256', 'recipe_sha256'}


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def natural(value):
    if type(value) is not int or value < 0:
        raise ValueError('Expected nonnegative integer')
    return value


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch('[a-zA-Z0-9_-]{1,64}', value):
        raise ValueError('Invalid buffer or context identifier')
    return value


def review(raw, expected):
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES or not raw.endswith(b'\n'):
        raise ValueError('Oversized, empty or truncated transcript')
    if set(expected) != IDENTITY_FIELDS:
        raise ValueError('Expected external run, runtime and recipe identity')
    for key, length in (('run_id', 32), ('runtime_sha256', 64), ('recipe_sha256', 64)):
        if not isinstance(expected[key], str) or not re.fullmatch('[a-f0-9]{%d}' % length, expected[key]):
            raise ValueError('Invalid expected identity')
    lines = raw.splitlines()
    if not 5 <= len(lines) <= MAX_EVENTS:
        raise ValueError('Incomplete or oversized event count')
    buffers = {}
    completed = set()
    checked = set()
    contexts = set()
    final_checked = set()
    flushing = False
    flushed = False
    queries = 0
    shapes = {
        'start': {'schema', *IDENTITY_FIELDS},
        'buffer_requested': {'buffer'},
        'buffer_completed': {'buffer', 'context', 'stream', 'parse_status'},
        'loss_check': {'buffer', 'context', 'stream', 'status', 'dropped'},
        'flush_begin': set(), 'flush_end': {'status'},
        'final_loss_check': {'context', 'stream', 'status', 'dropped'},
        'finish': {'buffers_requested', 'buffers_completed', 'loss_queries'},
    }
    for index, line in enumerate(lines):
        event = json.loads(line, object_pairs_hook=unique)
        if not isinstance(event, dict) or type(event.get('seq')) is not int or event['seq'] != index:
            raise ValueError('Missing, duplicate or unordered event')
        kind = event.get('kind')
        if not isinstance(kind, str) or kind not in shapes or set(event) != shapes[kind] | {'seq', 'kind'}:
            raise ValueError('Unknown event or schema fields')
        if index == 0:
            if kind != 'start' or type(event['schema']) is not int or event['schema'] != 1:
                raise ValueError('Missing startup')
            if any(event[k] != expected[k] for k in IDENTITY_FIELDS):
                raise ValueError('Transcript identity differs from expected run')
            continue
        if kind == 'start' or (index == len(lines) - 1) != (kind == 'finish'):
            raise ValueError('Invalid startup/finalization boundary')
        if kind == 'buffer_requested':
            if flushing or flushed:
                raise ValueError('New activity after final flush began')
            buffer = identifier(event['buffer'])
            if buffer in buffers:
                raise ValueError('Buffer ID reused; allocation-unique IDs required')
            buffers[buffer] = None
        elif kind == 'buffer_completed':
            buffer = identifier(event['buffer'])
            if flushed or buffer not in buffers or buffer in completed or event['parse_status'] != 'ok':
                raise ValueError('Unknown, duplicate, late or failed buffer completion')
            pair = (identifier(event['context']), natural(event['stream']))
            buffers[buffer] = pair
            contexts.add(pair)
            completed.add(buffer)
        elif kind in ('loss_check', 'final_loss_check'):
            pair = (identifier(event['context']), natural(event['stream']))
            if natural(event['status']) != 0 or natural(event['dropped']) != 0:
                raise ValueError('CUPTI query failed or records were dropped')
            if kind == 'loss_check':
                buffer = identifier(event['buffer'])
                if flushed or buffer not in completed or buffer in checked or buffers[buffer] != pair:
                    raise ValueError('Missing completion, duplicate query or context mismatch')
                checked.add(buffer)
            else:
                if not flushed or pair not in contexts or pair in final_checked:
                    raise ValueError('Invalid final loss check')
                final_checked.add(pair)
            queries += 1
        elif kind == 'flush_begin':
            if flushing or flushed:
                raise ValueError('Repeated flush')
            flushing = True
        elif kind == 'flush_end':
            if not flushing or flushed or natural(event['status']) != 0:
                raise ValueError('Missing or failed final flush')
            if not buffers or completed != set(buffers) or checked != completed:
                raise ValueError('Uncompleted buffers or missing loss checks')
            flushed = True
        elif kind == 'finish':
            if not flushed or contexts != final_checked:
                raise ValueError('Missing final flush or context loss checks')
            counts = (len(buffers), len(completed), queries)
            if tuple(natural(event[k]) for k in ('buffers_requested', 'buffers_completed', 'loss_queries')) != counts:
                raise ValueError('Final accounting differs')
    return {'transcript_valid': True, 'buffers': len(buffers), 'loss_queries': queries,
            'scope': 'supplied collector transcript structure and reported counters only',
            'collector_execution_verified': False, 'capture_completeness_verified': False,
            'calibration_verified': False, 'approved_gpu_ms': None, 'reward_eligible': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('transcript', type=Path)
    for key in sorted(IDENTITY_FIELDS):
        parser.add_argument('--' + key.replace('_', '-'), required=True)
    args = parser.parse_args()
    with args.transcript.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    print(json.dumps(review(raw, {k: getattr(args, k) for k in IDENTITY_FIELDS}), indent=2))


if __name__ == '__main__':
    main()
