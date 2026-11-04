import tempfile
import unittest
from pathlib import Path

from classify_personal_outputs import classify, normalize_asset_urls


class ClassificationTests(unittest.TestCase):
    def test_only_absent_localized_copy_with_identical_bytes_is_proven(self):
        with tempfile.TemporaryDirectory() as tmp:
            official, fork = Path(tmp)/'official', Path(tmp)/'fork'
            (official/'en').mkdir(parents=True)
            fork.mkdir()
            (official/'en/a.png').write_bytes(b'actual image bytes')
            (fork/'a.png').write_bytes(b'actual image bytes')
            result = classify(official, fork, ['en/a.png', 'index.html'])
            self.assertEqual(list(result['classified']), ['en/a.png'])
            self.assertEqual(result['unclassified_paths'], ['index.html'])
            (fork/'a.png').write_bytes(b'other image bytes')
            self.assertEqual(classify(official, fork, ['en/a.png'])['classified'], {})
            (fork/'a.png').write_bytes(b'actual image bytes')
            (fork/'en').mkdir()
            (fork/'en/a.png').write_bytes(b'changed localized bytes')
            self.assertEqual(classify(official, fork, ['en/a.png'])['classified'], {})

    def test_resource_proofs_do_not_rewrite_text_scripts_or_unverified_hashes(self):
        assets = {('a.js', 'h=verified'): 'asset'}
        text = '''<script>const fake='<a href="/a.js?h=verified">';</script><p>/a.js?h=verified</p><script src="/a.js?h=verified"></script><a href="/a.js?h=wrong">link</a>'''
        result = normalize_asset_urls(text, 'index.html', 'https://example.com/', assets)
        self.assertIn('const fake=\'<a href="/a.js?h=verified">', result)
        self.assertIn('<p>/a.js?h=verified</p>', result)
        self.assertIn('src="/__verified_asset_asset"', result)
        self.assertIn('href="/a.js?h=wrong"', result)
        self.assertEqual(normalize_asset_urls('<a href="https://elsewhere/a.js?h=verified">x</a>', 'index.html', 'https://example.com/', assets), '<a href="https://elsewhere/a.js?h=verified">x</a>')

    def test_unrelated_attribute_values_are_not_resource_attributes(self):
        text = "<a onclick=\"go('href=/a.js?h=verified')\">x</a>"
        self.assertEqual(normalize_asset_urls(text, 'index.html', 'https://example.com/', {('a.js', 'h=verified'): 'asset'}), text)
