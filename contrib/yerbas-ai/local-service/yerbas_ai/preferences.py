"""Validated local preferences and wall-clock contribution availability policy."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import threading
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT = {
    'schema_version': 1, 'revision': 0, 'default_model': None,
    'schedule': {'enabled': False, 'timezone': 'UTC', 'days': list(range(7)),
                 'start': '22:00', 'end': '06:00'},
}


class RevisionConflict(ValueError):
    pass


def minute(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', value):
        raise ValueError('Times must use 24-hour HH:MM format')
    hour, minutes = map(int, value.split(':'))
    return hour*60+minutes


def validate(data):
    if not isinstance(data, dict) or set(data) != set(DEFAULT):
        raise ValueError('Unknown or missing preference fields')
    if type(data['schema_version']) is not int or data['schema_version'] != 1:
        raise ValueError('Unsupported preferences version')
    if type(data['revision']) is not int or data['revision'] < 0:
        raise ValueError('Invalid revision')
    model = data['default_model']
    if model is not None and (not isinstance(model, str) or not model or len(model) > 256):
        raise ValueError('Default model must be null or a nonempty name up to 256 characters')
    schedule = data['schedule']
    if not isinstance(schedule, dict) or set(schedule) != set(DEFAULT['schedule']):
        raise ValueError('Unknown or missing schedule fields')
    if type(schedule['enabled']) is not bool:
        raise ValueError('Schedule enabled must be boolean')
    if not isinstance(schedule['timezone'], str):
        raise ValueError('Timezone must be an IANA timezone name')
    try:
        ZoneInfo(schedule['timezone'])
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError('Unknown timezone; install timezone data or choose a supported IANA name') from None
    days = schedule['days']
    if (not isinstance(days, list) or not 1 <= len(days) <= 7
            or any(type(day) is not int or not 0 <= day <= 6 for day in days)
            or len(set(days)) != len(days)):
        raise ValueError('Days must be unique weekday numbers 0..6 (Monday..Sunday)')
    if minute(schedule['start']) == minute(schedule['end']):
        raise ValueError('Start and end must differ; equal times do not mean all day')


def availability(schedule, now=None):
    """Overnight windows belong to the weekday on which they start.

    Evaluate real instants in the chosen zone. Repeated DST clock times both
    qualify; skipped clock times never occur. End boundaries are exclusive.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('Availability requires a timezone-aware instant')
    local = now.astimezone(ZoneInfo(schedule['timezone']))
    current = local.hour*60+local.minute
    start, end = minute(schedule['start']), minute(schedule['end'])
    day = local.weekday()
    if start < end:
        inside = day in schedule['days'] and start <= current < end
    else:
        inside = ((day in schedule['days'] and current >= start)
                  or ((day-1) % 7 in schedule['days'] and current < end))
    allowed = schedule['enabled'] and inside
    return {'schedule_enabled': schedule['enabled'], 'within_window': inside,
            'policy_allows_contribution': allowed, 'evaluated_at': local.isoformat(),
            'accepting_network_jobs': False, 'network_implemented': False,
            'reason': 'Schedule policy only; consult provider status for local bridge admission'}


class Preferences:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else None
        self.lock = threading.RLock()
        self.data = deepcopy(DEFAULT)
        if self.path is not None and self.path.exists():
            if self.path.is_symlink():
                raise ValueError('Preferences must not be a symlink')
            with self.path.open('rb') as stream:
                raw = stream.read(65537)
            if len(raw) > 65536:
                raise ValueError('Preferences file is too large')
            self.data = json.loads(raw)
            validate(self.data)

    def snapshot(self):
        with self.lock:
            return deepcopy(self.data)

    def update(self, changes, revision):
        with self.lock:
            if type(revision) is not int or revision != self.data['revision']:
                raise RevisionConflict('Preferences changed; reload and retry')
            if not isinstance(changes, dict) or not changes or set(changes)-{'default_model', 'schedule'}:
                raise ValueError('Only default_model and schedule may be changed')
            updated = deepcopy(self.data)
            updated.update(deepcopy(changes))
            updated['revision'] += 1
            validate(updated)
            if self.path is not None:
                temp = self.path.with_name('.preferences-'+secrets.token_hex(8))
                try:
                    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    with os.fdopen(fd, 'w') as stream:
                        json.dump(updated, stream, indent=2)
                        stream.write('\n')
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temp, self.path)
                finally:
                    temp.unlink(missing_ok=True)
            self.data = updated
            return deepcopy(updated)
