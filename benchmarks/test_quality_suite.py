from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from quality_suite import inspect_case


class QualitySuiteTests(unittest.TestCase):
    def test_inspect_valid_output_search_is_honestly_partial(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'index.html').write_text('<html lang="en"><title>A</title><meta name="description" content="A"><link rel="canonical" href="https://x/"></html>')
            result = inspect_case({'label': 'fixture', 'output_root': str(root), 'base_url': 'https://x/', 'pages': ['index.html']})
            self.assertEqual(result['status'], 'partial')
            self.assertEqual(result['technical_seo']['status'], 'pass')
            self.assertEqual(result['search']['status'], 'unsupported')
            self.assertEqual(result['reader_delivery'][0]['potential_local_requests'], 1)
            self.assertEqual(len(result['output_manifest_sha256']), 64)

    def test_fixture_search_scope_and_failures_propagate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'index.html').write_text('<html lang="en"><title>A</title><meta name="description" content="A"><link rel="canonical" href="https://x/"></html>')
            case = {'label':'fixture', 'output_root':str(root), 'base_url':'https://x/', 'pages':[],
                    'fixture_search':{'articles':8, 'languages':['en'], 'base_url':'https://x/'}}
            for status in ('pass', 'fail'):
                with patch('quality_suite.shutil.which', return_value='/node'), patch('synthetic_search_suite.inspect_corpus', return_value={'status':status, 'shipped_frontend_provided':False}):
                    result = inspect_case(case)
                self.assertEqual(result['status'], status)
                self.assertFalse(result['search']['shipped_frontend_provided'])
            with patch('quality_suite.shutil.which', return_value=None):
                result = inspect_case(case)
            self.assertEqual(result['status'], 'partial')
            self.assertEqual(result['search']['status'], 'unsupported')

    def test_missing_output_fails(self):
        result = inspect_case({'label': 'missing', 'output_root': '/nonexistent-benchmark-output', 'base_url': 'https://x/', 'pages': []})
        self.assertEqual(result['status'], 'fail')


if __name__ == '__main__':
    unittest.main()
