#!/usr/bin/env python3
"""Generate isolated content through the actual personal search dictionary builder."""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
from quality_metrics import encoded_bytes, encoder_versions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pages', type=int, default=100)
    parser.add_argument('--personal-root', required=True, type=Path, help='Checkout containing actual static/search.js and prepush dictionary generator')
    parser.add_argument('--work', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.pages < 5:
        parser.error('--pages must be >=5')
    repo = args.personal_root.resolve()
    generator = repo/'prepush-scripts/02-generate-search-dicts.py'
    frontend = repo/'static/search.js'
    if not generator.is_file() or not frontend.is_file():
        parser.error('--personal-root must contain actual frontend and dictionary generator')
    spec = importlib.util.spec_from_file_location('personal_dictionary_generator', generator)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    work = args.work.resolve()
    # Refuse reuse: stale fixture files must not change query membership.
    work.mkdir(parents=True, exist_ok=False)
    content, dictionaries = work/'content', work/'search_dicts'
    content.mkdir()
    dictionaries.mkdir()
    titles = ['Orion telescope guide', 'Caffè résumé', '東京 研究', 'مرحبا بالعالم', 'Background notes']
    for i in range(args.pages):
        title = titles[i] if i < len(titles) else f'Neutral document {i}'
        description = 'Orion telescope guide' if i == 4 else 'Benchmark reference'
        (content/f'entry-{i:05}.md').write_text('+++\ntitle = ' + json.dumps(title, ensure_ascii=False) + '\ndescription = ' + json.dumps(description) + '\n+++\n\nIndependent fixture body.\n')
    with contextlib.redirect_stdout(io.StringIO()):
        module.generate_search_dictionaries(content, dictionaries)
    index = dictionaries/'search_dict.it.json'
    url = lambda i: f'/entry-{i:05}/'
    queries = [
        {'text': 'Orion telescope', 'expected': [url(0), url(4)], 'ranked_prefix': [url(0)]},
        {'text': 'caffe resume', 'expected': [url(1)], 'ranked_prefix': [url(1)]},
        {'text': '東京', 'expected': [url(2)]},
        {'text': 'مرحبا', 'expected': [url(3)]},
        {'text': 'unfindablezzzz', 'expected': []},
        {'text': 'Orion unfindablezzzz', 'expected': []},
    ]
    specification = {'adapter': str(Path(__file__).with_name('personal_search_adapter.mjs').resolve()),
                     'frontend': str(frontend), 'index': str(index), 'language': 'it',
                     'source_files': [str(frontend), str(generator), str(index)], 'queries': queries}
    spec_path = work/'search-spec.json'
    spec_path.write_text(json.dumps(specification, ensure_ascii=False, indent=2))
    process = subprocess.run(['node', str(Path(__file__).with_name('search_probe.mjs')), str(spec_path)], capture_output=True, text=True, timeout=120)
    report = json.loads(process.stdout) if process.returncode == 0 else {'status': 'fail', 'stderr': process.stderr}
    report.update({'search_activation_index_download': {**encoded_bytes(index.read_bytes()), 'encoder_versions': encoder_versions(), 'policy': 'dictionary fetch on search initialization; separate from initial document dependency graph; no browser transfer measured'}, 'pages': args.pages, 'fixture': 'actual personal dictionary generator; multilingual text in supported it dictionary, no locale stemming claim',
                   'generator_sha256': hashlib.sha256(generator.read_bytes()).hexdigest(), 'specification': str(spec_path)})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
