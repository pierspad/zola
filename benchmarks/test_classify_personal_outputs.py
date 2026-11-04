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

    def test_source_dimensions_prove_only_actual_image_attributes(self):
        from classify_personal_outputs import verified_image_attributes
        with tempfile.TemporaryDirectory() as tmp:
            roots = [Path(tmp)/name for name in ['official', 'fork']]
            for root in roots:
                root.mkdir()
                (root/'image.svg').write_text('<svg width="792px" height="388px"/>')
            a = '<img src="/image.svg" loading="lazy" decoding="async">'
            b = '<img src="/image.svg" width="792" height="388" decoding="async">'
            x, y, proofs = verified_image_attributes(a, b, 'index.html', 'https://example.com/', *roots)
            self.assertEqual(x, y)
            self.assertEqual(proofs[0]['source_dimensions'], [792, 388])
            x, y, _ = verified_image_attributes(a, b.replace('792', '793'), 'index.html', 'https://example.com/', *roots)
            self.assertNotEqual(x, y)
            (roots[1]/'image.svg').write_text('<svg width="10" height="20"/>')
            self.assertEqual(verified_image_attributes(a, b, 'index.html', 'https://example.com/', *roots)[2], [])

    def test_feed_image_proofs_resolve_relative_to_article_and_preserve_other_text(self):
        import html
        from classify_personal_outputs import verified_feed_contents
        with tempfile.TemporaryDirectory() as tmp:
            roots = [Path(tmp)/name for name in ['official', 'fork']]
            for root in roots:
                (root/'article').mkdir(parents=True)
                (root/'article/image.svg').write_text('<svg width="10" height="20"/>')
            def feed(image, title='same'):
                encoded = html.escape(image, quote=True).replace('&#x27;', '&#39;')
                return '<rss><channel><item><title>'+title+'</title><link>https://example.com/article/</link><description>'+encoded+'</description></item></channel></rss>'
            a, b = feed('<img src="image.svg" loading="lazy">'), feed('<img src="image.svg" width="10" height="20">')
            x, y, proofs = verified_feed_contents(a, b, 'https://example.com/', *roots, [{}, {}])
            self.assertEqual(x, y)
            self.assertTrue(proofs)
            x, y, _ = verified_feed_contents(a, b.replace('<title>same', '<title>changed'), 'https://example.com/', *roots, [{}, {}])
            self.assertNotEqual(x, y)

    def test_nonfirst_lazy_changes_nonpixel_svg_and_duplicate_text_are_not_hidden(self):
        from classify_personal_outputs import verified_image_attributes
        with tempfile.TemporaryDirectory() as tmp:
            roots = [Path(tmp)/name for name in ['official', 'fork']]
            for root in roots:
                root.mkdir()
                (root/'image.svg').write_text('<svg width="72pt" height="72pt"/>')
            a = '<img src="/image.svg" loading="lazy">'
            b = '<img src="/image.svg" width="96" height="96">'
            x, y, _ = verified_image_attributes(a, b, 'index.html', 'https://example.com/', *roots)
            self.assertNotEqual(x, y)
            x, y, proofs = verified_image_attributes('<img src="/other">'+a, '<img src="/other">'+a.replace(' loading="lazy"', ''), 'index.html', 'https://example.com/', *roots)
            self.assertNotEqual(x, y)
            self.assertEqual(proofs, [])
            literal = '<script>const fake=\''+a+'\';</script>'
            x, y, proofs = verified_image_attributes(literal+a, literal+a.replace(' loading="lazy"', ''), 'index.html', 'https://example.com/', *roots)
            self.assertEqual(x, y)
            self.assertIn(literal, x)

    def test_feed_duplicate_body_literal_outside_entry_remains_visible(self):
        import html
        from classify_personal_outputs import verified_feed_contents
        with tempfile.TemporaryDirectory() as tmp:
            roots = [Path(tmp)/name for name in ['official', 'fork']]
            for root in roots:
                root.mkdir()
                (root/'image.svg').write_text('<svg width="10" height="20"/>')
            a = '<img src="/image.svg" loading="lazy">'
            b = '<img src="/image.svg">'
            def feed(inner, outer):
                escape = lambda text: html.escape(text, quote=True).replace('&#x27;', '&#39;')
                return '<rss><channel><description>'+escape(outer)+'</description><item><link>https://example.com/</link><description>'+escape(inner)+'</description></item></channel></rss>'
            x, y, _ = verified_feed_contents(feed(a, a), feed(b, b), 'https://example.com/', *roots, [{}, {}])
            self.assertNotEqual(x, y)
            self.assertIn('<description>'+html.escape(a, quote=True)+'</description>', x)
