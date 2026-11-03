import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from synthetic_search_suite import HERE, BASE, LANGUAGES, specification, url, inspect_corpus, guarded_probe, index_bytes


@unittest.skipUnless(shutil.which('node'), 'Node required for pinned Fuse compatibility tests')
class SyntheticSearchTests(unittest.TestCase):
    def probe(self, records, change_spec=None):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = root/'index.json'
            index.write_text(json.dumps(records, ensure_ascii=False))
            spec = specification(index, 5, 'en', 2)
            if change_spec:
                change_spec(spec)
            path = root/'spec.json'
            path.write_text(json.dumps(spec))
            result = subprocess.run(['node', str(HERE/'search_probe.mjs'), str(path)], capture_output=True, text=True)
            return result, json.loads(result.stdout) if result.returncode == 0 else None

    def records(self):
        return [{'url':BASE, 'title':'', 'body':''}] + [
            {'url':url(i, 'en'), 'title':title, 'body':'Orion telescope guide' if i == 4 else 'Reference'}
            for i, title in enumerate(['Orion telescope guide','Caffè résumé','東京 研究','مرحبا بالعالم','Background notes'])]

    def test_runtime_unicode_ranking_nohits(self):
        process, report = self.probe(self.records())
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(report['status'], 'pass')
        self.assertEqual(len(report['samples']), 5)
        self.assertTrue(all(len(sample['raw_ms']) == 2 for sample in report['samples']))

    def test_missing_document_rejected_independently_of_queries(self):
        records = self.records()[:-1]
        process, _ = self.probe(records)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('membership count', process.stderr)

    def test_wrong_url_and_duplicate_rejected(self):
        for replacement in ('https://wrong.example/', BASE):
            records = self.records()
            records[-1]['url'] = replacement
            process, _ = self.probe(records)
            self.assertNotEqual(process.returncode, 0)
            self.assertIn('URL membership', process.stderr)

    def test_ranking_corruption_detected(self):
        records = self.records()
        records[1]['title'], records[-1]['title'] = records[-1]['title'], records[1]['title']
        records[1]['body'], records[-1]['body'] = records[-1]['body'], records[1]['body']
        process, report = self.probe(records)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(report['status'], 'fail')
        self.assertEqual(report['samples'][0]['status'], 'fail')

    def test_byte_preflight_skips_runtime_without_claiming_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = root/'index.json'
            index.write_text('[]')
            result = guarded_probe(root/'missing-spec.json',index,{'max_index_bytes':1})
            self.assertEqual(result['status'],'skipped_resource')
            self.assertEqual(result['resource_guard']['index_bytes'],2)
            self.assertGreater(index_bytes(index)['gzip_bytes'],0)

    def test_rich_corpus_oracle_checks_foreign_locale_membership(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for lang, marker, _ in LANGUAGES:
                if lang not in ('en', 'ar', 'zh'):
                    continue
                prefix = BASE + ('' if lang == 'en' else lang + '/')
                records = [{'url':prefix, 'title':marker + ' Home', 'body':''},
                           {'url':prefix + 'articles/', 'title':marker + ' Articles', 'body':''}]
                records += [{'url':prefix + f'articles/page-{i:05}/',
                             'title':marker + f' Page {i:05}: notes', 'body':'Reference body'} for i in range(5)]
                (root/f'search_index.{lang}.json').write_text(json.dumps(records, ensure_ascii=False))
            descriptor = {'articles':5, 'languages':['en','ar','zh'], 'base_url':BASE, 'iterations':1}
            result = inspect_corpus(root,descriptor)
            self.assertEqual(result['status'],'pass')
            self.assertFalse(result['shipped_frontend_provided'])
            path = root/'search_index.ar.json'
            records = json.loads(path.read_text())
            records.pop()
            path.write_text(json.dumps(records, ensure_ascii=False))
            result = inspect_corpus(root,descriptor)
            self.assertEqual(result['status'],'fail')
            self.assertEqual(result['languages']['ar']['status'],'fail')
            self.assertEqual(result['languages']['zh']['status'],'pass')

    def test_unicode_corruption_detected(self):
        for index in (2, 3, 4):  # accented Latin, CJK, RTL
            records = self.records()
            records[index]['title'] = 'Broken title'
            process, report = self.probe(records)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(report['status'], 'fail')


if __name__ == '__main__':
    unittest.main()
