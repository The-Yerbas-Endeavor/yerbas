#!/usr/bin/env python3
"""Render one compact workflow summary without hiding failed or missing reports."""
import json
from pathlib import Path
import sys

PLATFORMS = {
    'ubuntu22': 'Ubuntu 22',
    'ubuntu24': 'Ubuntu 24',
    'ubuntu26': 'Ubuntu 26',
    'ubuntu24-arm64': 'Ubuntu 24 ARM64',
    'macos15-intel': 'macOS 15 Intel',
    'win64': 'Windows 64-bit',
}


def render(directory):
    lines = ['## Unit tests by platform', '',
             '| Platform | Passed suites | Failed suites | Time |',
             '| --- | ---: | ---: | ---: |']
    failures = []
    incomplete = []
    for platform, label in PLATFORMS.items():
        path = Path(directory) / ('yerbas-' + platform + '-unit-summary') / 'summary.json'
        try:
            results = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(results, list) or not results:
                raise ValueError('Empty or invalid report')
            for result in results:
                if (not isinstance(result, dict) or type(result.get('passed')) is not bool
                        or not isinstance(result.get('suite'), str)
                        or not isinstance(result.get('seconds'), (int, float))):
                    raise ValueError('Invalid suite result')
            failed = [result for result in results if not result['passed']]
            lines.append('| {} | {} | {} | {:.1f}s |'.format(
                label, len(results) - len(failed), len(failed), sum(r['seconds'] for r in results)))
            failures.extend((label, result['suite']) for result in failed)
        except (OSError, ValueError, TypeError):
            lines.append('| {} | — | Report unavailable | — |'.format(label))
            incomplete.append(label)
    if failures:
        lines.extend(['', '### Failed suites', ''])
        for label, suite in failures:
            safe = suite.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('`', '')
            lines.append('- {}: `{}`'.format(label, safe))
    if incomplete:
        lines.extend(['', 'Missing reports are not passes. Check the corresponding build/test jobs.'])
    lines.extend(['', 'Counts are unit-test suites. Qt, transaction utility, and wallet/asset recovery checks remain in their job logs.',
                  'Full suite details and JUnit reports are retained in each platform’s test-results artifact.', ''])
    return '\n'.join(lines), bool(failures or incomplete)


if __name__ == '__main__':
    report, failed = render(sys.argv[1])
    print(report)
    raise SystemExit(int(failed))
