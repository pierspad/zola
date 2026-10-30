#!/usr/bin/env python3
"""Regression checks for attributable engine resources and failed measurements."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from matrix import BuildFailure, WORK, build


class ResourceAccountingTests(unittest.TestCase):
    def setUp(self):
        WORK.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='resource-test-', dir=WORK)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = self.root/'child.py'
        self.args = SimpleNamespace(timeout=2, rss_gib=3, reserve_gib=0, disk_gib=8)

    def child(self, source):
        self.binary.write_text('#!/usr/bin/env python3\n'+source)
        self.binary.chmod(0o700)
        return build(self.binary.resolve(), self.root, os.environ, False, self.args)

    def test_engine_rss_excludes_large_parent_heap(self):
        retained = bytearray(200*1024**2)
        retained[::4096] = b'x'*len(retained[::4096])
        sample = self.child('import time\nx=bytearray(20*1024**2)\ntime.sleep(.02)\n')
        self.assertGreater(sample['peak_rss_bytes'], 20*1024**2)
        self.assertLess(sample['peak_rss_bytes'], 80*1024**2)
        self.assertGreater(sample['outer_wrapper_wait4_peak_rss_bytes_not_engine'], 150*1024**2)
        self.assertGreaterEqual(sample['seconds'], .02)

    def test_nonzero_engine_is_failed_measurement(self):
        with self.assertRaises(BuildFailure) as failure:
            self.child('raise SystemExit(7)\n')
        self.assertEqual(failure.exception.args[0]['exit_code'], 7)

    def test_group_timeout_does_not_substitute_wrapper_resources(self):
        self.args.timeout = .05
        with self.assertRaises(BuildFailure) as failure:
            self.child('import time\ntime.sleep(2)\n')
        sample = failure.exception.args[0]
        self.assertEqual(sample['abort_reason'], 'timeout budget')
        for field in ('peak_rss_bytes', 'seconds', 'cpu_total_seconds'):
            self.assertIsNone(sample[field])
        self.assertIn('sampled_engine_rss_lower_bound_bytes', sample)


if __name__ == '__main__':
    unittest.main()
