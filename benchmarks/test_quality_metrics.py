import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import shutil
import quality_metrics
from quality_metrics import MAX_SITEMAP_BYTES, Document, delivery, local_path, sitemap_check, technical_seo


class MetricsTests(unittest.TestCase):
    def test_sitemap_boundaries(self):
        def sitemap(n):
            return ('<urlset>' + ''.join(f'<url><loc>https://x/{i}</loc></url>' for i in range(n)) + '</urlset>').encode()
        self.assertEqual(sitemap_check(sitemap(50000))['errors'], [])
        self.assertIn('sitemap exceeds 50000 entries', sitemap_check(sitemap(50001))['errors'])
        data = b'<urlset/>'
        self.assertEqual(sitemap_check(data, max_bytes=len(data))['errors'], [])
        self.assertIn('uncompressed sitemap exceeds byte limit', sitemap_check(data, max_bytes=len(data)-1)['errors'])

    def test_actual_fifty_mib_boundary(self):
        # Whitespace is valid XML and exercises the real default uncompressed limit.
        data = b'<urlset>' + b' ' * (MAX_SITEMAP_BYTES - 17) + b'</urlset>'
        self.assertEqual(len(data), MAX_SITEMAP_BYTES)
        self.assertEqual(sitemap_check(data)['errors'], [])
        self.assertIn('uncompressed sitemap exceeds byte limit', sitemap_check(data + b' ')['errors'])

    def test_invalid_xml_and_duplicates(self):
        self.assertTrue(sitemap_check(b'<urlset>')['errors'])
        self.assertTrue(sitemap_check(b'<urlset><url><loc>x</loc></url><url><loc>x</loc></url></urlset>')['errors'])

    def test_resolution_rejects_escape_and_other_hosts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertIsNone(local_path(root, 'https://x/blog/', '/elsewhere/', 'https://x/blog/'))
            self.assertIsNone(local_path(root, 'https://x/', 'https://other/a', 'https://x/'))
            self.assertIsNone(local_path(root, 'https://x/', '/%2e%2e/private', 'https://x/'))

    def test_delivery_css_cycle_and_shared_asset(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'index.html').write_text('<link rel="stylesheet" href="a.css"><img src="pic.webp"><script src="https://cdn/x.js"></script>')
            (root/'a.css').write_text('@import "b.css";body{background:url(pic.webp)}')
            (root/'b.css').write_text('@import "a.css";@font-face{src:url(missing.woff)}')
            (root/'pic.webp').write_bytes(b'image')
            result = delivery(root, 'index.html', 'https://x/')
            self.assertEqual(result['potential_local_requests'], 4)
            self.assertEqual(result['raw_bytes'], sum(p.stat().st_size for p in root.iterdir()))
            self.assertEqual(result['missing_dependencies'], ['missing.woff'])
            self.assertEqual(result['external_dependencies'], ['https://cdn/x.js'])

    @unittest.skipUnless(shutil.which('node'), 'Node Brotli fallback unavailable')
    def test_actual_node_brotli_fallback(self):
        with patch.object(quality_metrics, 'brotli', None), patch.object(quality_metrics, 'NODE_BROTLI', shutil.which('node')):
            result = quality_metrics.encoded_bytes(b'repeated bytes ' * 100)
            self.assertGreater(result['brotli_bytes'], 0)
            self.assertLess(result['brotli_bytes'], result['raw_bytes'])
            quality_metrics.encoder_versions.cache_clear()
            self.assertIn('node', quality_metrics.encoder_versions()['brotli'])
        quality_metrics.encoder_versions.cache_clear()

    def test_seo_reciprocity_json_and_fragments(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'index.html').write_text('<html lang="en"><title>A</title><meta name="description" content="A"><link rel="canonical" href="https://x/"><link rel="alternate" hreflang="ar" href="https://x/ar/"><a href="ar/#no">x</a><script type="application/ld+json">{bad}</script>')
            (root/'ar').mkdir()
            (root/'ar/index.html').write_text('<html lang="ar" dir="rtl"><title>B</title><link rel="canonical" href="https://x/ar/">')
            result = technical_seo(root, 'https://x/')
            messages = [e['message'] for e in result['errors']]
            self.assertEqual(result['status'], 'fail')
            self.assertTrue(any('reciprocal' in e for e in messages))
            self.assertTrue(any('JSON-LD' in e for e in messages))
            self.assertTrue(any('fragment' in e for e in messages))
            self.assertEqual(result['metadata_status'], 'missing')


if __name__ == '__main__':
    unittest.main()
