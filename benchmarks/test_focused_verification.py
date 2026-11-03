import unittest
from focused_verification import noise_interval
from unittest.mock import patch


class NoiseTests(unittest.TestCase):
    def test_pid_reuse_and_new_process_do_not_invent_cpu(self):
        before = {'processes': {'1': {'name': 'desktop', 'start': 'a', 'ticks': 10},
                                '2': {'name': 'old', 'start': 'b', 'ticks': 100}}}
        after = {'processes': {'1': {'name': 'desktop', 'start': 'a', 'ticks': 60},
                               '2': {'name': 'new', 'start': 'c', 'ticks': 300},
                               '3': {'name': 'new', 'start': 'd', 'ticks': 1000}}}
        with patch('os.sysconf', return_value=100):
            result = noise_interval(before, after, 2)
        self.assertEqual(result['persistent_external_cpu_seconds'], .5)
        self.assertEqual(result['external_cpu_cores'], .25)
        self.assertEqual(len(result['top']), 1)


if __name__ == '__main__':
    unittest.main()
