from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
from yerbas_ai.preferences import DEFAULT, Preferences, RevisionConflict, availability


class PreferencesTests(unittest.TestCase):
    def test_disabled_by_default(self):
        prefs = Preferences().snapshot()
        self.assertFalse(prefs['schedule']['enabled'])
        self.assertFalse(availability(prefs['schedule'])['accepting_network_jobs'])

    def test_persistence_and_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'preferences.json'
            prefs = Preferences(path)
            prefs.update({'default_model': 'model:local'}, 0)
            self.assertEqual(Preferences(path).snapshot()['default_model'], 'model:local')
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_conflicting_update_is_rejected(self):
        prefs = Preferences()
        prefs.update({'default_model': 'model:local'}, 0)
        with self.assertRaises(RevisionConflict):
            prefs.update({'default_model': 'other:local'}, 0)
        self.assertEqual(prefs.snapshot()['default_model'], 'model:local')

    def test_failed_replace_preserves_memory_and_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'preferences.json'
            prefs = Preferences(path)
            prefs.update({'default_model': 'original'}, 0)
            original = path.read_bytes()
            with patch('yerbas_ai.preferences.os.replace', side_effect=OSError('disk error')):
                with self.assertRaises(OSError):
                    prefs.update({'default_model': 'new'}, 1)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(prefs.snapshot()['revision'], 1)
            self.assertEqual(list(Path(directory).glob('.preferences-*')), [])

    def test_invalid_schedule_does_not_change_preferences(self):
        invalid = [{'timezone': 'Not/AZone'}, {'days': []}, {'days': [0, 0]},
                   {'days': [True]}, {'start': '24:00'}, {'start': '6:00'},
                   {'end': '22:00'}, {'enabled': 'true'}, {'extra': 1}]
        for bad in invalid:
            prefs = Preferences()
            schedule = dict(prefs.snapshot()['schedule'], **bad)
            with self.assertRaises(ValueError):
                prefs.update({'schedule': schedule}, 0)
            self.assertEqual(prefs.snapshot()['revision'], 0)

    def test_corrupt_file_fails_instead_of_resetting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'preferences.json'
            for content in ('{', '{"schema_version":99}'):
                path.write_text(content)
                with self.assertRaises(ValueError):
                    Preferences(path)
                self.assertEqual(path.read_text(), content)

    def test_snapshot_cannot_mutate_live_settings(self):
        prefs = Preferences()
        copy = prefs.snapshot()
        copy['schedule']['days'].clear()
        self.assertEqual(len(prefs.snapshot()['schedule']['days']), 7)


class ScheduleTests(unittest.TestCase):
    def window(self, days, start, end, zone='America/Los_Angeles'):
        return {'enabled': True, 'timezone': zone, 'days': days, 'start': start, 'end': end}

    def allows(self, schedule, instant):
        result = availability(schedule, datetime.fromisoformat(instant))
        self.assertFalse(result['accepting_network_jobs'])
        return result['policy_allows_contribution']

    def test_daytime_boundaries(self):
        schedule = self.window([0], '09:00', '17:00', 'UTC')
        self.assertFalse(self.allows(schedule, '2026-10-26T08:59:00+00:00'))
        self.assertTrue(self.allows(schedule, '2026-10-26T09:00:00+00:00'))
        self.assertFalse(self.allows(schedule, '2026-10-26T17:00:00+00:00'))

    def test_overnight_belongs_to_start_day(self):
        schedule = self.window([4], '22:00', '06:00')
        self.assertTrue(self.allows(schedule, '2026-10-30T22:00:00-07:00'))
        self.assertTrue(self.allows(schedule, '2026-10-31T05:59:00-07:00'))
        self.assertFalse(self.allows(schedule, '2026-10-31T06:00:00-07:00'))
        self.assertFalse(self.allows(schedule, '2026-10-31T22:00:00-07:00'))

    def test_sunday_overnight_wraps_to_monday(self):
        schedule = self.window([6], '22:00', '06:00', 'UTC')
        self.assertTrue(self.allows(schedule, '2026-10-26T05:00:00+00:00'))

    def test_fall_back_both_repeated_hours_are_allowed(self):
        schedule = self.window([6], '01:00', '02:00')
        self.assertTrue(self.allows(schedule, '2026-11-01T08:30:00+00:00'))
        self.assertTrue(self.allows(schedule, '2026-11-01T09:30:00+00:00'))
        self.assertFalse(self.allows(schedule, '2026-11-01T10:00:00+00:00'))

    def test_spring_forward_skipped_hour_never_opens(self):
        schedule = self.window([6], '02:00', '03:00')
        self.assertFalse(self.allows(schedule, '2026-03-08T09:59:00+00:00'))
        self.assertFalse(self.allows(schedule, '2026-03-08T10:00:00+00:00'))

    def test_disabled_schedule_never_authorizes_contribution(self):
        schedule = self.window([0], '09:00', '17:00', 'UTC')
        schedule['enabled'] = False
        self.assertFalse(self.allows(schedule, '2026-10-26T12:00:00+00:00'))

    def test_naive_datetime_is_rejected(self):
        with self.assertRaises(ValueError):
            availability(DEFAULT['schedule'], datetime(2026, 10, 26, 12))
