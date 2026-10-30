import unittest
from unittest.mock import patch
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import extended_suite
from extended_suite import COMMON, selected_cases


class ExtendedSuiteTests(unittest.TestCase):
    def test_common_and_opt_in(self):
        self.assertEqual(selected_cases(COMMON, False), COMMON)
        for count in (50000, 100000):
            with self.assertRaises(ValueError):
                selected_cases(f'{count}x1', False)
            self.assertEqual(selected_cases(f'{count}x1', True), f'{count}x1')
        with self.assertRaises(ValueError):
            selected_cases('4000x15', False)

    def test_driver_never_calls_unsupported_quality_complete(self):
        for quality, expected, exit_code in [('partial', 'partial', 0), ('fail', 'failed_quality', 1)]:
            with tempfile.TemporaryDirectory() as folder:
                output = Path(folder)/'run.json'
                output.with_name('run-matrix.json').write_text(json.dumps({'cases': [{'status': 'passed', 'quality_status': quality}]}))
                argv = ['extended_suite.py', '--quick', '--quality', '--output', str(output), '--rss-gib', '0.01', '--reserve-gib', '0.01']
                with patch('sys.argv', argv), patch.object(extended_suite, 'memory_headroom', return_value={'effective_available_bytes': 1024**3}), patch.object(extended_suite.subprocess, 'run', return_value=SimpleNamespace(returncode=0)):
                    self.assertEqual(extended_suite.main(), exit_code)
                report = json.loads(output.read_text())
                self.assertEqual(report['status'], expected)
                self.assertEqual(report['personal_search']['status'], 'unsupported')
                self.assertIn('--warmups', report['command'])

    def test_invalid_cases(self):
        for value in ('no', '100x0', '100x16', '1x1', ''):
            with self.assertRaises(ValueError):
                selected_cases(value, True)


if __name__ == '__main__':
    unittest.main()
