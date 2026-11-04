import unittest
from focused_verification import noise_interval
from unittest.mock import patch


class NoiseTests(unittest.TestCase):
    def test_aggregate_counts_exited_work_and_does_not_double_count_guest(self):
        before = {'processes': {}, 'aggregate_cpu_ticks': [0]*10, 'runqueue': 2}
        after = {'processes': {}, 'aggregate_cpu_ticks': [100, 0, 50, 200, 50, 0, 0, 0, 100, 0], 'runqueue': 3}
        with patch('os.sysconf', return_value=100):
            result = noise_interval(before, after, 2, engine_cpu=.5)
        self.assertEqual(result['host_active_cpu_seconds'], 1.5)
        self.assertEqual(result['aggregate_external_cpu_seconds_estimate'], 1)
        self.assertEqual(result['host_idle_including_iowait_fraction'], .625)

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


class PersonalInputTests(unittest.TestCase):
    def test_cold_site_cache_is_symmetric_but_theme_assets_survive(self):
        import tempfile
        from pathlib import Path
        from focused_verification import prepare_personal_comparison
        with tempfile.TemporaryDirectory() as tmp:
            root, official = Path(tmp)/'site', Path(tmp)/'official'
            (root/'static/processed_images').mkdir(parents=True)
            (root/'static/processed_images/stale.webp').write_bytes(b'cache')
            theme = root/'themes/theme/static/processed_images/asset.webp'
            theme.parent.mkdir(parents=True)
            theme.write_bytes(b'tracked theme asset')
            report = prepare_personal_comparison(root, official)
            self.assertTrue(report['exact_input_manifests_equal'])
            self.assertFalse((root/'static/processed_images').exists())
            self.assertEqual((official/theme.relative_to(root)).read_bytes(), theme.read_bytes())


if __name__ == '__main__':
    unittest.main()
