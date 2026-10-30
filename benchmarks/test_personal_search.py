import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(shutil.which('node'), 'actual frontend search requires Node')
class PersonalSearchTests(unittest.TestCase):
    def test_actual_frontend_and_dictionary_generator(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report = root/'report.json'
            subprocess.run([sys.executable, str(Path(__file__).with_name('personal_search_suite.py')),
                            '--pages', '100', '--work', str(root/'fixture'), '--output', str(report)], check=True)
            result = json.loads(report.read_text())
            self.assertEqual(result['status'], 'pass')
            self.assertEqual(len(result['samples']), 6)
            self.assertTrue(all(len(sample['raw_ms']) == 100 and len(sample['raw_cpu_ms']) == 100 for sample in result['samples']))
            self.assertTrue(all(source['sha256'] for source in result['source_files']))
            self.assertGreater(result['peak_process_rss_bytes'], 0)


if __name__ == '__main__':
    unittest.main()
