#!/usr/bin/env python3
"""Run every enabled Boost suite in its own process and retain JUnit reports.

A crash or timeout in one suite must neither hide failures nor prevent the
remaining suites from running. No third-party Python packages are required.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET


def failure_report(path, name, message, output):
    # Preserve raw logs separately, but omit characters forbidden in XML 1.0.
    message = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', message)
    output = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', output)
    root = ET.Element('testsuite', name=name, tests='1', errors='1', failures='0')
    case = ET.SubElement(root, 'testcase', classname='test_runner', name=name)
    ET.SubElement(case, 'error', message=message).text = output
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--output', type=Path, default=Path('test-results'))
    parser.add_argument('--timeout', type=int, default=180,
                        help='Maximum seconds per suite (default: 180)')
    parser.add_argument('--suite', action='append', help='Run only a named suite; repeatable')
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    binary = args.binary.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / 'discovery.xml').unlink(missing_ok=True)
    try:
        listed = subprocess.run([str(binary), '--list_content=HRF', '--color_output=no'],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors='replace', timeout=30, check=True)
        (output / 'discovery.log').write_text(listed.stdout, encoding='utf-8')
        suites = re.findall(r'^([A-Za-z_][A-Za-z_0-9]*)\*$', listed.stdout, re.MULTILINE)
        if not suites:
            raise ValueError('No enabled Boost suites were discovered')
        if args.suite:
            unknown = set(args.suite) - set(suites)
            if unknown:
                raise ValueError('Unknown or disabled suites: ' + ', '.join(sorted(unknown)))
            suites = [suite for suite in suites if suite in args.suite]
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        message = str(exc)
        details = getattr(exc, 'stdout', None) or message
        if isinstance(details, bytes):
            details = details.decode('utf-8', errors='replace')
        failure_report(output / 'discovery.xml', 'discovery', message, details)
        print('Test discovery failed: ' + message, flush=True)
        return 1

    results = []
    for suite in suites:
        xml = output / (suite + '.xml')
        log = output / (suite + '.log')
        # Never accept a report left over from an earlier invocation.
        xml.unlink(missing_ok=True)
        command = [str(binary), '--run_test=' + suite, '--color_output=no',
                   '--log_format=JUNIT', '--log_sink=' + str(xml), '--report_level=short']
        started = time.monotonic()
        print('Running ' + suite, flush=True)
        error = None
        code = None
        with log.open('w', encoding='utf-8') as handle:
            try:
                code = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT,
                                      timeout=args.timeout, check=False).returncode
            except subprocess.TimeoutExpired:
                error = 'Suite timed out after {} seconds'.format(args.timeout)
            except OSError as exc:
                error = str(exc)
        try:
            root = ET.parse(xml).getroot()
            if root.tag not in ('testsuite', 'testsuites'):
                raise ValueError('Unexpected JUnit root: ' + root.tag)
            cases = list(root.iter('testcase'))
            if not any(case.find('skipped') is None for case in cases):
                raise ValueError('JUnit contains no executed test cases')
            reported_failures = root.findall('.//failure') + root.findall('.//error')
            if code != 0 and not reported_failures:
                error = error or 'Test process exited with code {}'.format(code)
            if code == 0 and reported_failures:
                error = 'JUnit reported failures despite a successful process exit'
        except (OSError, ValueError, ET.ParseError) as exc:
            error = error or 'Missing or invalid JUnit report: ' + str(exc)
        if error:
            text = log.read_text(encoding='utf-8', errors='replace')[-12000:]
            failure_report(xml, suite, error, text)
        passed = code == 0 and error is None
        result = {'suite': suite, 'passed': passed, 'exit_code': code,
                  'seconds': round(time.monotonic() - started, 3), 'error': error}
        results.append(result)
        print('{}: {} ({:.1f}s)'.format(suite, 'PASS' if passed else 'FAIL', result['seconds']), flush=True)

    (output / 'summary.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    failed = sum(not result['passed'] for result in results)
    summary = ['## Yerbas unit tests', '',
               '**{} passed · {} failed** — {} suites, {:.1f}s total.'.format(
                   len(results) - failed, failed, len(results),
                   sum(r['seconds'] for r in results)), '']
    if failed:
        summary.extend(['### Failed suites', '',
                        '| Suite | Result | Seconds |', '| --- | --- | --- |'])
        summary.extend('| {} | FAIL | {} |'.format(r['suite'], r['seconds'])
                       for r in results if not r['passed'])
        summary.append('')
    summary.extend(['<details>', '<summary>Show all suite results</summary>', '',
                    '| Suite | Result | Seconds |', '| --- | --- | --- |'])
    summary.extend('| {} | {} | {} |'.format(r['suite'], 'PASS' if r['passed'] else 'FAIL', r['seconds'])
                   for r in results)
    summary.extend(['', '</details>', '',
                    'JUnit reports and individual suite logs are in the test-results artifact.', ''])
    report = '\n'.join(summary)
    (output / 'summary.md').write_text(report, encoding='utf-8')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as handle:
            handle.write(report)
    print('{} suites passed; {} failed'.format(len(results) - failed, failed), flush=True)
    return int(bool(failed))


if __name__ == '__main__':
    raise SystemExit(main())
