#!/usr/bin/env python3
"""Isolated native multilingual Unicode benchmark with cache-free differential oracles."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from multilingual_fixtures import VERSION, LANGUAGES, article, generate_multilingual, mutate_multilingual
from release_suite import manifest, cache_hits, WORK


def build(binary, root, env, incremental=False):
    command = [str(binary), '--root', str(root), 'build'] + (['--incremental'] if incremental else [])
    start = time.perf_counter()
    rss = None
    # wait4 returns this child's peak RSS; cumulative RUSAGE_CHILDREN would be wrong.
    with tempfile.TemporaryFile(mode='w+') as log:
        process = subprocess.Popen(command, env=env, text=True, stdout=log, stderr=subprocess.STDOUT)
        if hasattr(os, 'wait4'):
            _, status, usage = os.wait4(process.pid, 0)
            process.returncode = os.waitstatus_to_exitcode(status)
            rss = int(usage.ru_maxrss * (1 if platform.system() == 'Darwin' else 1024))
        else:
            process.wait()
        elapsed = time.perf_counter() - start
        log.seek(0)
        output = log.read()
    if process.returncode:
        raise ValueError(output)
    return {'seconds': elapsed, 'peak_rss_bytes': None, 'rss_method': 'unsupported_direct_wait4: parent pre-exec RSS floor can contaminate engine peak; use matrix.py', 'diagnostic_direct_wait4_peak_bytes_not_engine': rss, 'cache_hits': cache_hits(output)}


def prefix(lang):
    return '' if lang == 'en' else lang + '/'


def coverage(root, articles, languages, feed_limit=None, extended_search=True):
    public = root / 'public'
    indexes = {}
    feeds = list(public.rglob('atom.xml')) + list(public.rglob('rss.xml'))
    max_feed_entries = 0
    for path in feeds:
        tree = ET.parse(path)
        entries = tree.findall('{http://www.w3.org/2005/Atom}entry') if path.name == 'atom.xml' else tree.findall('./channel/item')
        max_feed_entries = max(max_feed_entries, len(entries))
        if feed_limit is not None and len(entries) > feed_limit:
            raise ValueError(f'Feed exceeds configured limit: {path}')
        if feed_limit is not None and ('<table>' in path.read_text() or '&lt;table&gt;' in path.read_text()):
            raise ValueError(f'Feed contains full article body: {path}')
    for lang, marker, rtl in languages:
        pre = prefix(lang)
        for path in ('index.html', 'articles/index.html', 'tags/index.html', 'categories/index.html', 'atom.xml', 'rss.xml'):
            if not (public / (pre + path)).is_file():
                raise ValueError('Missing locale output: ' + pre + path)
        if articles > 20 and not (public / (pre + 'articles/page/2/index.html')).is_file():
            raise ValueError('Missing archive pagination: ' + lang)
        if articles > 20 and not (public / (pre + 'tags/shared/page/2/index.html')).is_file():
            raise ValueError('Missing taxonomy pagination: ' + lang)
        search_path = public / f'search_index.{lang}.json'
        records = json.loads(search_path.read_text())
        if len(records) != articles + 2:
            raise ValueError(f'{lang}: expected {articles + 2} search records, got {len(records)}')
        for record in records:
            url = record['url']
            base = 'https://release.example.com/' + pre
            if not url.startswith(base) or (lang == 'en' and any(url.startswith('https://release.example.com/' + code + '/') for code, _, _ in languages[1:])):
                raise ValueError(f'Cross-language search URL: {url}')
        html = (public / (pre + 'articles/page-00000/index.html')).read_text()
        for token in (f'lang={lang}', f'dir={"rtl" if rtl else "ltr"}', marker):
            if token not in html and token.replace('=', '="') + '"' not in html:
                raise ValueError(f'{lang}: missing HTML marker {token}')
        class Links(HTMLParser):
            def __init__(self):
                super().__init__()
                self.siblings = {}
                self.html_attrs = {}
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == 'html':
                    self.html_attrs = attrs
                if tag == 'a' and 'hreflang' in attrs:
                    self.siblings[attrs['hreflang']] = attrs.get('href')
        parser = Links()
        parser.feed(html)
        if parser.html_attrs.get('lang') != lang or parser.html_attrs.get('dir') != ('rtl' if rtl else 'ltr'):
            raise ValueError(f'{lang}: incorrect HTML language/direction')
        siblings = parser.siblings
        # Native page.translations includes the current page too.
        expected = {code: 'https://release.example.com/' + prefix(code) + 'articles/page-00000/' for code, _, _ in languages}
        if len(languages) == 1:
            expected = {}  # Native translation metadata is empty without siblings.
        if siblings != expected:
            raise ValueError(f'{lang}: translation hrefs differ: {siblings} != {expected}')
        item = next(record for record in records if record['url'].endswith('/articles/page-00000/'))
        if marker not in json.dumps(item, ensure_ascii=False) or (extended_search and (not item.get('headings') or not item.get('taxonomies'))):
            raise ValueError(f'{lang}: Unicode/search fields absent')
        indexes[lang] = {'records': len(records), 'bytes': search_path.stat().st_size}
    return {'logical_articles': articles, 'rendered_article_pages': articles * len(languages), 'languages': len(languages), 'search_indexes': indexes, 'html_files': len(list(public.rglob('*.html'))), 'output_files': len(manifest(public)), 'output_bytes': sum(p.stat().st_size for p in public.rglob('*') if p.is_file()), 'feed_files': len(feeds), 'feed_bytes': sum(p.stat().st_size for p in feeds), 'max_feed_entries': max_feed_entries, 'taxonomy_html_files': sum('/tags/' in '/' + p.relative_to(public).as_posix() or '/categories/' in '/' + p.relative_to(public).as_posix() for p in public.rglob('*.html'))}


def run(args):
    binary = args.binary.resolve()
    env = dict(os.environ, RAYON_NUM_THREADS=str(args.threads))
    env.setdefault('RUST_LOG', 'site=info,zola=info')
    WORK.mkdir(exist_ok=True, parents=True)
    report = {'schema': 1, 'profile': 'multilingual-unicode' if args.profile == 'stress' else 'newspaper-bounded-summary', 'fixture_version': VERSION, 'logical_articles': args.articles, 'language_count': args.languages, 'threads': args.threads, 'binary': str(binary), 'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(), 'platform': platform.platform(), 'rss_method': 'unsupported_direct_wait4: engine RSS unavailable; use canonical matrix fresh broker', 'failures': []}
    report['feed_policy'] = {'limit': args.feed_limit if args.profile == 'newspaper' else None, 'body': 'summary' if args.profile == 'newspaper' else 'full'}
    with tempfile.TemporaryDirectory(prefix='multilingual-', dir=WORK) as temp:
        root = Path(temp)
        languages = generate_multilingual(root, args.articles, args.languages, args.profile, args.feed_limit)
        report['languages'] = [lang for lang, _, _ in languages]
        report['fixture_sha256'] = hashlib.sha256(json.dumps(manifest(root), sort_keys=True).encode()).hexdigest()
        source = list(root.rglob('*.md'))
        report['source_stats'] = {'markdown_files': len(source), 'markdown_bytes': sum(p.stat().st_size for p in source)}
        report['samples'] = {}
        expected = None
        for mode in ('full', 'incremental'):
            warmups = [build(binary, root, env, mode == 'incremental') for _ in range(args.warmups)]
            samples = []
            for _ in range(args.runs):
                sample = build(binary, root, env, mode == 'incremental')
                output = manifest(root / 'public')
                if expected is not None and expected != output:
                    raise ValueError('Unchanged build differs from full output')
                expected = output
                report['coverage'] = coverage(root, args.articles, languages, args.feed_limit if args.profile == "newspaper" else None)
                samples.append(sample)
                print(f'{mode}: {sample["seconds"]:.3f}s RSS={sample["peak_rss_bytes"]}', flush=True)
            report['samples'][mode] = {'warmups': warmups, 'runs': samples, 'median_seconds': statistics.median(s['seconds'] for s in samples)}
        report['persistent_cache_bytes'] = sum(p.stat().st_size for p in (root / '.zola-cache').rglob('*') if p.is_file())
        report['mutations'] = []
        if args.mutations:
            # Seed a default-only group before priming; adding a sibling then changes native translation links.
            article(root, args.articles, 'en', LANGUAGES[0][1], summary=args.profile == 'newspaper')
            build(binary, root, env, True)
            for scenario in ('new_translation', 'new_article_all_languages', 'edit_translation', 'delete_translation', 'rename_translation'):
                if scenario == "new_translation" and len(languages) == 1:
                    continue
                mutate_multilingual(root, scenario, args.articles, languages, summary=args.profile == "newspaper")
                candidate = build(binary, root, env, True)
                actual = manifest(root / 'public')
                with tempfile.TemporaryDirectory(prefix='multilingual-oracle-', dir=WORK) as oracle_temp:
                    oracle = Path(oracle_temp) / 'site'
                    shutil.copytree(root, oracle, ignore=shutil.ignore_patterns('public', 'processed_images', '.zola*'))
                    full = build(binary, oracle, env)
                    oracle_manifest = manifest(oracle / 'public')
                changed = sorted(k for k in actual.keys() | oracle_manifest.keys() if actual.get(k) != oracle_manifest.get(k))
                evidence = args.output.parent / (args.output.stem + '-mutations') / (scenario + '.json')
                evidence.parent.mkdir(parents=True, exist_ok=True)
                evidence.write_text(json.dumps({'equal': not changed, 'oracle_manifest': oracle_manifest, 'changed': changed}, sort_keys=True) + '\n')
                if changed:
                    raise ValueError(f'{scenario}: independent full oracle mismatch: {changed[:12]}')
                report['mutations'].append({'scenario': scenario, 'candidate': candidate, 'full_oracle': full, 'equal': True, 'manifest_artifact': str(evidence.resolve())})
                print(f'{scenario}: {candidate["seconds"]:.3f}s / full {full["seconds"]:.3f}s; oracle matches', flush=True)
        report['output_manifest_sha256'] = hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=('stress', 'newspaper'), default='stress')
    parser.add_argument('--feed-limit', type=int, default=50, help='Newspaper profile only: example feed cap, adjustable to editorial policy')
    parser.add_argument('--articles', type=int, default=1000)
    parser.add_argument('--languages', type=int, default=15)
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--warmups', type=int, default=1)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--mutations', action='store_true')
    parser.add_argument('--binary', type=Path, default=Path('target/release/zola'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.articles < 8 or not 1 <= args.languages <= 15 or args.runs < 1 or args.warmups < 0 or args.threads < 1 or args.feed_limit < 1:
        parser.error('articles >= 8; languages 1..15; runs/threads/feed-limit positive; warmups nonnegative')
    try:
        run(args)
    except (ValueError, OSError, KeyError, StopIteration) as error:
        parser.exit(2, str(error) + '\n')


if __name__ == '__main__':
    main()
