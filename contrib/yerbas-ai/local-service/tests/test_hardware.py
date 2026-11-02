import subprocess
import unittest
from unittest.mock import patch
from yerbas_ai.hardware import inventory, resolve_gpu


class HardwareTests(unittest.TestCase):
    @patch('yerbas_ai.hardware.subprocess.run')
    def test_inventory_and_uuid_selection(self, run):
        run.return_value.stdout = '1, GPU-abc, Example GPU, 11264, 34, 2\n'
        report = inventory()
        self.assertEqual(report['devices'][0]['memory_used_mib'], 34)
        self.assertEqual(resolve_gpu('1', report), 'GPU-abc')
        self.assertEqual(resolve_gpu('GPU-abc', report), 'GPU-abc')
        with self.assertRaises(ValueError):
            resolve_gpu('0', report)

    @patch('yerbas_ai.hardware.subprocess.run', side_effect=FileNotFoundError)
    def test_missing_driver_is_unavailable_not_zero_usage(self, run):
        report = inventory()
        self.assertFalse(report['available'])
        self.assertEqual(report['devices'], [])

    @patch('yerbas_ai.hardware.subprocess.run')
    def test_unsupported_metrics_are_null(self, run):
        run.return_value.stdout = '0, GPU-abc, Example GPU, 8192, [N/A], [N/A]\n'
        device = inventory()['devices'][0]
        self.assertIsNone(device['memory_used_mib'])
        self.assertIsNone(device['utilization_percent'])
