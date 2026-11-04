#!/usr/bin/env python3
"""Prove localized asset deduplication by exact bytes; preserve all other deltas."""
import argparse
import hashlib
import html
import json
import re
import subprocess
import tempfile
from urllib.parse import urljoin, urlsplit, unquote
from pathlib import Path
from html.parser import HTMLParser
import xml.etree.ElementTree as ET


def normalize_asset_urls(text, document, base_url, assets):
    """Replace only actual resource attributes with exact, verified URL keys."""
    def value(raw):
        url = urlsplit(urljoin(base_url.rstrip('/') + '/' + document, html.unescape(raw)))
        if url.netloc != urlsplit(base_url).netloc or url.fragment:
            return raw
        token = assets.get((unquote(url.path).lstrip('/'), url.query))
        return '/__verified_asset_' + token if token else raw
    class Tags(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.edits = []
            self.lines = [0]
            self.lines.extend(m.end() for m in re.finditer('\n', text))
        def handle_starttag(self, tag, attrs):
            raw = self.get_starttag_text()
            pattern = r'([^\s"\'<>/=]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s"\'<>]+))'
            def replace(m):
                if m[1] not in {'src', 'href', 'poster', 'data-search-css', 'data-search-src'}:
                    return m[0]
                group = next(i for i in (2, 3, 4) if m[i] is not None)
                return m[0][:m.start(group)-m.start()] + value(m[group]) + m[0][m.end(group)-m.start():]
            changed = re.sub(pattern, replace, raw)
            if changed != raw:
                line, col = self.getpos()
                self.edits.append((self.lines[line-1]+col, len(raw), changed))
        handle_startendtag = handle_starttag
    parser = Tags()
    parser.feed(text)
    for start, length, replacement in reversed(parser.edits):
        text = text[:start] + replacement + text[start+length:]
    return text


def verified_image_attributes(before, after, document, base_url, official, fork):
    """Prove only dimensions of identical source bytes and lazy-to-eager changes.

    Only the first parsed content image may lose lazy loading. Non-pixel SVG
    dimensions remain unclassified; no physical-unit conversion is assumed.
    """
    from PIL import Image
    evidence = []
    def source(root, value):
        url = urlsplit(urljoin(base_url.rstrip('/') + '/' + document, html.unescape(value)))
        if url.netloc != urlsplit(base_url).netloc or url.query or url.fragment:
            return None
        path = root / unquote(url.path).lstrip('/')
        return path if path.is_file() else None
    def tags(text):
        values = []
        class Images(HTMLParser):
            def handle_starttag(self, tag, attrs):
                if tag == 'img':
                    line, col = self.getpos()
                    offset = sum(len(part) for part in text.splitlines(keepends=True)[:line-1]) + col
                    values.append((self.get_starttag_text(), dict(attrs), offset))
            handle_startendtag = handle_starttag
        Images(convert_charrefs=False).feed(text)
        return values
    old, new = tags(before), tags(after)
    if len(old) != len(new):
        return before, after, evidence
    edits = [[], []]
    for index, ((raw_a, a, pos_a), (raw_b, b, pos_b)) in enumerate(zip(old, new)):
        pa, pb = source(official, a.get('src', '')), source(fork, b.get('src', ''))
        if not pa or not pb or pa.read_bytes() != pb.read_bytes():
            continue
        remove_a, remove_b = [], []
        svg_units = None
        try:
            if pb.suffix.lower() == '.svg':
                svg = ET.parse(pb).getroot()
                svg_units = {key: svg.attrib[key] for key in ('width', 'height')}
                width, height = (int(re.fullmatch(r'(\d+)(?:px)?', svg.attrib[key])[1]) for key in ('width', 'height'))
            else:
                with Image.open(pb) as image:
                    width, height = image.size
            for key, dimension in [('width', width), ('height', height)]:
                if key not in a and b.get(key) == str(dimension):
                    remove_b.append(key)
        except (OSError, ValueError, KeyError, TypeError, ET.ParseError):
            pass
        if index == 0 and a.get('loading') == 'lazy' and 'loading' not in b:
            remove_a.append('loading')
        if not remove_a and not remove_b:
            continue
        def strip(raw, keys):
            for key in keys:
                raw = re.sub(r'\s+' + key + r'=(?:"[^"]*"|\'[^\']*\'|[^\s>]+)', '', raw)
            return raw
        edits[0].append((pos_a, len(raw_a), strip(raw_a, remove_a)))
        edits[1].append((pos_b, len(raw_b), strip(raw_b, remove_b)))
        evidence.append({'official_asset': str(pa.relative_to(official)),
                         'fork_asset': str(pb.relative_to(fork)),
                         'source_sha256': hashlib.sha256(pb.read_bytes()).hexdigest(),
                         'source_dimensions': [width, height] if remove_b else None,
                         'svg_literal_units': svg_units,
                         'dimension_policy': 'Exact integral SVG pixel dimensions.' if svg_units else 'Decoded raster pixel dimensions.',
                         'official_attributes': remove_a, 'fork_attributes': remove_b,
                         'loading_policy_scope': 'Only first parsed content image; render fragments beyond that require review.'})
    texts = [before, after]
    for i in range(2):
        for start, length, value in reversed(edits[i]):
            texts[i] = texts[i][:start] + value + texts[i][start+length:]
    return *texts, evidence


def verified_feed_contents(before, after, base_url, official, fork, asset_maps):
    """Compare escaped HTML within feed entries using each article's URL."""
    proofs = []
    try:
        trees = [ET.fromstring(text) for text in (before, after)]
    except ET.ParseError:
        return before, after, proofs
    def local(tag):
        return tag.rsplit('}', 1)[-1]
    entries = [[e for e in tree.iter() if local(e.tag) in {'entry', 'item'}] for tree in trees]
    if len(entries[0]) != len(entries[1]):
        return before, after, proofs
    texts = [before, after]
    for entry_index, pair in enumerate(zip(*entries)):
        links, contents = [], []
        for entry in pair:
            links.append(next((e.attrib.get('href', e.text or '') for e in entry if local(e.tag) == 'link' and e.attrib.get('rel', 'alternate') == 'alternate'), ''))
            contents.append(next((e.text or '' for e in entry if local(e.tag) in {'content', 'description'}), ''))
        if links[0] != links[1] or not links[0] or not all(contents):
            continue
        doc = urlsplit(links[0]).path.lstrip('/')
        a, b, image_proofs = verified_image_attributes(*contents, doc, base_url, official, fork)
        normalized = [normalize_asset_urls(value, doc, base_url, assets) for value, assets in zip((a, b), asset_maps)]
        if normalized[0] != normalized[1]:
            continue
        encoded = [html.escape(value, quote=True).replace('&#x27;', '&#39;') for value in contents]
        spans = []
        for raw, text, parsed_entries in zip(encoded, texts, entries):
            blocks = list(re.finditer(r'<(entry|item)\b[^>]*>.*?</\1>', text, re.S))
            if len(blocks) != len(parsed_entries):
                break
            block = blocks[entry_index]
            matches = [m for m in re.finditer(r'<(content|description)\b[^>]*>(.*?)</\1>', block[0], re.S) if m[2] == raw]
            if len(matches) != 1:
                break
            start, end = matches[0].span(2)
            spans.append((block.start() + start, block.start() + end))
        if len(spans) != 2:
            continue
        canonical = html.escape(normalized[0], quote=True).replace('&#x27;', '&#39;')
        for i in range(2):
            start, end = spans[i]
            texts[i] = texts[i][:start] + canonical + texts[i][end:]
        if contents[0] != contents[1]:
            proofs.append({'article_url': links[0], 'source_image_attribute_proofs': image_proofs})
    return *texts, proofs


def classify(official, fork, changed, minifier=None, base_url='https://classification.invalid/'):

    proofs, unknown = {}, []
    for name in changed:
        before = official / name
        replacement = fork / name[3:]
        if (name.startswith('en/') and before.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg', '.avif', '.pdf', '.mp3', '.mp4', '.ogg', '.wav'}
                and before.is_file()
                and not (fork / name).exists() and replacement.is_file()
                and before.read_bytes() == replacement.read_bytes()):
            proofs[name] = {'classification': 'localized_asset_deduplication',
                            'same_bytes_fork_path': name[3:],
                            'sha256': hashlib.sha256(before.read_bytes()).hexdigest()}
        elif (minifier and before.is_file() and (fork / name).is_file()
              and before.suffix in {'.css', '.js'}):
            with tempfile.TemporaryDirectory(prefix='asset-minifier-proof-') as tmp:
                output = Path(tmp) / 'minified'
                subprocess.run([str(minifier), str(before), str(output)], check=True)
                if output.read_bytes() == (fork / name).read_bytes():
                    proofs[name] = {'classification': 'exact_asset_minifier_output',
                                    'official_sha256': hashlib.sha256(before.read_bytes()).hexdigest(),
                                    'fork_sha256': hashlib.sha256(output.read_bytes()).hexdigest()}
                else:
                    unknown.append(name)
        else:
            unknown.append(name)
    # Only rewrite a resource URL after the complete asset transformation was
    # proven above and both URL hash values match those actual asset bytes.
    hash_pairs = [(name, proof['official_sha256'][:20], proof['fork_sha256'][:20])
                  for name, proof in proofs.items()
                  if proof['classification'] == 'exact_asset_minifier_output']
    asset_maps = [{}, {}]
    for old, proof in list(proofs.items()):
        if proof['classification'] != 'localized_asset_deduplication':
            continue
        for root, asset_map in zip([official, fork], asset_maps):
            for path in [old, proof['same_bytes_fork_path']]:
                target = root / path
                if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == proof['sha256']:
                    asset_map[(path, '')] = proof['sha256']
    for name, old_hash, new_hash in hash_pairs:
        for asset_map, resource_hash in zip(asset_maps, (old_hash, new_hash)):
            asset_map[(name, 'h=' + resource_hash)] = 'minified_' + name
    remaining = []
    for name in unknown:
        before, after = official / name, fork / name
        if name.endswith(('.html', '.xml')) and before.is_file() and after.is_file():
            original, candidate = before.read_text(), after.read_text()
            if name.endswith('.xml'):
                original, candidate, image_proofs = verified_feed_contents(original, candidate, base_url, official, fork, asset_maps)
            else:
                original, candidate, image_proofs = verified_image_attributes(original, candidate, name, base_url, official, fork)
            normalized = normalize_asset_urls(original, name, base_url, asset_maps[0])
            expected = normalize_asset_urls(candidate, name, base_url, asset_maps[1])
            if (image_proofs or normalized != original or expected != candidate) and normalized == expected:
                proofs[name] = {'classification': 'verified_asset_urls_only',
                                'scope': 'Actual resource attributes and source-image attributes only; URL compatibility and eager loading behavior are separate checks.',
                                'source_image_attribute_proofs': image_proofs}
                continue
        remaining.append(name)
    unknown = remaining
    return {'schema': 1, 'status': 'requires_review' if unknown else 'passed',
            'changed_paths_count': len(changed), 'classified': proofs,
            'unclassified_paths': unknown,
            'scope': 'Exact localized asset bytes, exact minifier outputs and matching resource hash URL substitutions only; all other deltas require review.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('official', type=Path)
    parser.add_argument('fork', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--minifier', type=Path)
    parser.add_argument('--minifier-library', type=Path)
    parser.add_argument('--base-url', default='https://classification.invalid/')
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    def manifest(root):
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob('*') if p.is_file()}
    before, after = manifest(args.official), manifest(args.fork)
    changed = sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))
    if changed != sorted(report['changed_paths']):
        raise ValueError('Supplied changed_paths is incomplete or differs from complete output manifests')
    result = classify(args.official, args.fork, changed, args.minifier, args.base_url)
    result['complete_manifests_verified'] = True
    result['official_file_count'], result['fork_file_count'] = len(before), len(after)
    result['source_report'] = str(args.report)
    result['base_url'] = args.base_url
    if args.minifier:
        result['minifier_executable_sha256'] = hashlib.sha256(args.minifier.read_bytes()).hexdigest()
        source = Path(__file__).with_name('minify_asset_proof.rs')
        result['minifier_source_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
        if args.minifier_library:
            result['minifier_library_sha256'] = hashlib.sha256(args.minifier_library.read_bytes()).hexdigest()
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(f"{len(result['classified'])} proven; {len(result['unclassified_paths'])} require review")


if __name__ == '__main__':
    main()
