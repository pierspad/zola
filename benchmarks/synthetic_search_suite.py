#!/usr/bin/env python3
"""Test actual Zola-generated Fuse indexes with a pinned fixture consumer.

This deliberately minimal search fixture isolates indexing/runtime compatibility;
it does not establish search UX quality of an existing site or rich-site build speed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from multilingual_fixtures import LANGUAGES
from quality_metrics import encoded_bytes, encoder_versions

HERE = Path(__file__).resolve().parent
BASE = 'https://search.example.com/'


def url(i, lang):
    return BASE + ('' if lang == 'en' else lang + '/') + f'entry-{i:05}/'


def generate(root, pages, languages):
    (root/'content').mkdir(parents=True)
    (root/'templates').mkdir()
    (root/'templates/page.html').write_text('<html><head><title>{{ page.title }}</title></head><body>{{ page.content | safe }}</body></html>')
    config = 'base_url="' + BASE + '"\ndefault_language="en"\nbuild_search_index=true\n[search]\nindex_format="fuse_json"\ninclude_title=true\ninclude_content=true\ninclude_description=false\ninclude_date=false\n'
    for lang, _, _ in languages[1:]:
        config += f'\n[languages.{lang}]\nbuild_search_index=true\n'
    (root/'config.toml').write_text(config)
    titles = ['Orion telescope guide', 'Caffè résumé', '東京 研究', 'مرحبا بالعالم', 'Background notes']
    for lang, marker, _ in languages:
        for i in range(pages):
            title = titles[i] if i < len(titles) else f'Neutral document {i}'
            body = 'Orion telescope guide' if i == 4 else 'Independent reference body'
            suffix = '' if lang == 'en' else '.' + lang
            (root/'content'/f'entry-{i:05}{suffix}.md').write_text('+++\ntitle=' + json.dumps(title, ensure_ascii=False) + '\n+++\n' + body + '\n\n' + marker)


def specification(index, pages, lang, iterations):
    urls = [BASE + ('' if lang == 'en' else lang + '/')] + [url(i, lang) for i in range(pages)]
    return {'adapter': str(HERE/'fuse_fixture_adapter.mjs'), 'index': str(index), 'expected_count': pages + 1,
            'expected_urls': urls, 'warmups': 2, 'iterations': iterations,
            'measurement': 'Pinned Fuse.js fixture consumer in Node; not shipped frontend/browser latency/LCP',
            'source_files': [str(index), str(HERE/'vendor/fuse-7.1.0.mjs'), str(HERE/'fuse_fixture_adapter.mjs')],
            'queries': [
                {'text':'Orion telescope', 'expected':[url(0, lang), url(4, lang)], 'ranked_prefix':[url(0, lang)]},
                {'text':'caffe resume', 'expected':[url(1, lang)]},
                {'text':'東京', 'expected':[url(2, lang)]},
                {'text':'مرحبا', 'expected':[url(3, lang)]},
                {'text':'unfindablezzzz', 'expected':[]},
            ]}


def probe(index, pages, lang, work, iterations):
    spec = specification(index, pages, lang, iterations)
    spec_path = work/f'{index.stem}-spec.json'
    spec_path.write_text(json.dumps(spec, ensure_ascii=False))
    process = subprocess.run(['node', str(HERE/'search_probe.mjs'), str(spec_path)], capture_output=True, text=True, timeout=180)
    if process.returncode:
        return {'status':'fail', 'stderr':process.stderr}
    result = json.loads(process.stdout)
    result['search_activation_index_download'] = {**encoded_bytes(index.read_bytes()), 'encoder_versions':encoder_versions(), 'policy':'fixture index bytes separate from initial HTML; transfer time not measured'}
    return result


def inspect_corpus(root, descriptor):
    """Known version-3 multilingual source oracle, independent of generated index."""
    import tempfile
    articles = descriptor['articles']
    languages = descriptor['languages']
    base = descriptor['base_url'].rstrip('/') + '/'
    markers = {code: marker for code, marker, _ in LANGUAGES}
    results = {}
    with tempfile.TemporaryDirectory(prefix='fuse-corpus-') as folder:
        for lang in languages:
            prefix = base + ('' if lang == 'en' else lang + '/')
            expected = [prefix, prefix + 'articles/'] + [prefix + f'articles/page-{i:05}/' for i in range(articles)]
            index = root/f'search_index.{lang}.json'
            spec = {'adapter':str(HERE/'fuse_fixture_adapter.mjs'), 'index':str(index),
                    'expected_count':articles + 2, 'expected_urls':expected, 'warmups':2, 'iterations':5,
                    'measurement':'Pinned Fuse.js fixture consumer of actual generated corpus index; no shipped frontend or browser claim',
                    'source_files':[str(index),str(HERE/'vendor/fuse-7.1.0.mjs'),str(HERE/'fuse_fixture_adapter.mjs')],
                    'queries':[{'text':'Page 00000:', 'expected':[expected[2]], 'ranked_prefix':[expected[2]]},
                               {'text':markers[lang] + ' Page 00000:', 'expected':[expected[2]]},
                               {'text':'unfindablezzzz', 'expected':[]}]}
            if lang == 'en':
                spec['queries'].append({'text':'Cafe naive facade resume Page 00000:', 'expected':[expected[2]]})
            spec_path = Path(folder)/(lang + '.json')
            spec_path.write_text(json.dumps(spec, ensure_ascii=False))
            process = subprocess.run(['node',str(HERE/'search_probe.mjs'),str(spec_path)],capture_output=True,text=True,timeout=180)
            result = json.loads(process.stdout) if process.returncode == 0 else {'status':'fail','stderr':process.stderr}
            if index.is_file():
                result['search_activation_index_download'] = encoded_bytes(index.read_bytes())
            results[lang] = result
    return {'status':'pass' if all(item['status'] == 'pass' for item in results.values()) else 'fail',
            'scope':'version-3 source-defined synthetic corpus; pinned fixture consumer; not site search UX',
            'shipped_frontend_provided':False, 'languages':results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fork', required=True, type=Path)
    parser.add_argument('--upstream', required=True, type=Path)
    parser.add_argument('--work', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--cases', default='100x1,1000x1,10000x1,1000x15,25000x1')
    parser.add_argument('--iterations', type=int, default=20)
    args = parser.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    binaries = {name:path.resolve() for name,path in [('fork',args.fork), ('upstream',args.upstream)]}
    report = {'scope':'fixture-only Fuse consumer; common upstream/fork fields; no date/headings/taxonomy search claim',
              'binary_sha256':{name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in binaries.items()}, 'cases':[]}
    for cell in args.cases.split(','):
        pages, count = map(int, cell.split('x'))
        if pages < 5 or not 1 <= count <= 15 or args.iterations < 1:
            parser.error('pages>=5, languages=1..15, iterations>=1 required')
        languages = LANGUAGES[:count]
        item = {'cell':cell, 'modes':{}, 'status':'pass'}
        snapshots = {}
        for mode in ('upstream_full','fork_full','fork_incremental'):
            site = work/(cell + '-' + ('upstream' if mode == 'upstream_full' else 'fork'))
            if mode != 'fork_incremental':
                generate(site, pages, languages)
            binary = binaries['upstream' if mode == 'upstream_full' else 'fork']
            command = [str(binary), 'build'] + (['--incremental'] if mode == 'fork_incremental' else [])
            process = subprocess.run(command, cwd=site, env={**os.environ, 'RAYON_NUM_THREADS':'4'}, capture_output=True, text=True, timeout=180)
            if process.returncode:
                item['modes'][mode] = {'status':'fail', 'stderr':process.stderr, 'stdout':process.stdout}
                item['status'] = 'fail'
                continue
            mode_result = {}
            for lang, _, _ in languages:
                index = site/'public'/f'search_index.{lang}.json'
                mode_result[lang] = probe(index, pages, lang, site, args.iterations)
                data = json.loads(index.read_text())
                key = lang
                if mode == 'upstream_full':
                    snapshots[key] = data
                mode_result[lang]['index_equals_upstream'] = data == snapshots.get(key)
                if mode_result[lang]['status'] != 'pass' or not mode_result[lang]['index_equals_upstream']:
                    item['status'] = 'fail'
            item['modes'][mode] = mode_result
        report['cases'].append(item)
        report['status'] = 'pass' if all(case['status'] == 'pass' for case in report['cases']) else 'fail'
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(cell, item['status'], flush=True)
    return report['status'] != 'pass'


if __name__ == '__main__':
    sys.exit(main())
