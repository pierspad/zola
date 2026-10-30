#!/usr/bin/env python3
"""Static output checks and reader bytes. No ranking or browser performance claims."""
import gzip
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import platform
import zlib
import shutil
import subprocess
from functools import lru_cache
try:
    import brotli
except ImportError:
    brotli = None
NODE_BROTLI = shutil.which("node") if brotli is None else None
from urllib.parse import unquote, urljoin, urlsplit
import xml.etree.ElementTree as ET

MAX_SITEMAP_BYTES = 50 * 1024 * 1024
MAX_SITEMAP_URLS = 50_000


def encoded_bytes(data):
    result = {'raw_bytes': len(data), 'gzip_bytes': len(gzip.compress(data, mtime=0))}
    if brotli is not None:
        result['brotli_bytes'] = len(brotli.compress(data, quality=5))
    elif NODE_BROTLI:
        script = 'const z=require("node:zlib");let chunks=[];process.stdin.on("data",x=>chunks.push(x));process.stdin.on("end",()=>process.stdout.write(z.brotliCompressSync(Buffer.concat(chunks),{params:{[z.constants.BROTLI_PARAM_QUALITY]:5}})));'
        result['brotli_bytes'] = len(subprocess.run([NODE_BROTLI, '-e', script], input=data, capture_output=True, check=True, timeout=30).stdout)
    return result


@lru_cache(maxsize=1)
def encoder_versions():
    brotli_info = {'version': brotli.__version__, 'quality': 5} if brotli is not None else {'status': 'unsupported: encoder unavailable'}
    if NODE_BROTLI:
        versions = json.loads(subprocess.run([NODE_BROTLI, '-p', 'JSON.stringify(process.versions)'], capture_output=True, text=True, check=True, timeout=10).stdout)
        brotli_info = {'node': versions['node'], 'version': versions.get('brotli'), 'quality': 5}
    return {'gzip': {'python': platform.python_version(), 'zlib': zlib.ZLIB_RUNTIME_VERSION, 'level': 9, 'mtime': 0}, 'brotli': brotli_info}


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.lang = self.direction = None
        self.canonicals, self.alternates, self.links, self.resources = [], [], [], []
        self.ids, self.duplicates, self.descriptions, self.jsonld = set(), [], [], []
        self.title = ''
        self._title = self._json = False
        self._jsontext = ''
        self.feed(text)

    def handle_starttag(self, tag, attributes):
        a = dict(attributes)
        if tag == 'html':
            self.lang, self.direction = a.get('lang'), a.get('dir', 'ltr')
        if a.get('id'):
            if a['id'] in self.ids:
                self.duplicates.append(a['id'])
            self.ids.add(a['id'])
        if tag == 'title':
            self._title = True
        if tag == 'meta' and a.get('name', '').lower() == 'description':
            self.descriptions.append(a.get('content', ''))
        if tag == 'link':
            rel = a.get('rel', '').split()
            if 'canonical' in rel:
                self.canonicals.append(a.get('href', ''))
            if 'alternate' in rel and 'hreflang' in a:
                self.alternates.append((a['hreflang'], a.get('href', '')))
            if any(r in rel for r in ('stylesheet', 'icon', 'preload', 'modulepreload')):
                self.resources.append(a.get('href', ''))
        if tag == 'a' and 'href' in a:
            self.links.append(a['href'])
            if 'hreflang' in a:
                self.alternates.append((a['hreflang'], a['href']))
        if tag in ('img', 'script', 'source', 'video', 'audio', 'iframe'):
            if 'src' in a:
                self.resources.append(a['src'])
            if 'poster' in a:
                self.resources.append(a['poster'])
            # srcset alternatives are potential downloads, not all fetched by one browser.
            self.resources.extend(x.strip().split()[0] for x in a.get('srcset', '').split(',') if x.strip())
        if tag == 'script' and a.get('type') == 'application/ld+json':
            self._json, self._jsontext = True, ''

    def handle_data(self, data):
        if self._title:
            self.title += data
        if self._json:
            self._jsontext += data

    def handle_endtag(self, tag):
        if tag == 'title':
            self._title = False
        if tag == 'script' and self._json:
            self.jsonld.append(self._jsontext)
            self._json = False


def local_path(root, base_url, reference, page_url):
    url = urlsplit(urljoin(page_url, reference))
    base = urlsplit(base_url)
    if url.scheme not in ('http', 'https') or url.netloc != base.netloc:
        return None
    # Base URL can include a deployment prefix.
    prefix = base.path.rstrip('/')
    path = unquote(url.path)
    if prefix and not (path == prefix or path.startswith(prefix + '/')):
        return None
    candidate = (root / path[len(prefix):].lstrip('/')).resolve()
    if not candidate.is_relative_to(root.resolve()):
        return None
    if candidate.is_dir() or path.endswith('/'):
        candidate /= 'index.html'
    return candidate


def sitemap_check(data, max_bytes=MAX_SITEMAP_BYTES):
    errors = []
    if len(data) > max_bytes:
        errors.append('uncompressed sitemap exceeds byte limit')
    try:
        tree = ET.fromstring(data)
    except ET.ParseError as exc:
        return {'errors': errors + [f'invalid XML: {exc}'], 'urls': [], 'indexes': []}
    kind = tree.tag.rsplit('}', 1)[-1]
    if kind not in ('urlset', 'sitemapindex'):
        errors.append('unexpected sitemap root')
    locations = [e.text or '' for e in tree.iter() if e.tag.rsplit('}', 1)[-1] == 'loc']
    if len(locations) > MAX_SITEMAP_URLS:
        errors.append('sitemap exceeds 50000 entries')
    if len(set(locations)) != len(locations):
        errors.append('duplicate sitemap locations')
    return {'errors': errors, 'urls': locations if kind == 'urlset' else [], 'indexes': locations if kind == 'sitemapindex' else []}


def technical_seo(root, base_url):
    root = Path(root).resolve()
    documents = {p: Document(p.read_text(errors='replace')) for p in root.rglob('*.html')}
    errors, missing_metadata, canonicals = [], [], {}
    def problem(path, message):
        errors.append({'path': str(path.relative_to(root)), 'message': message})
    def page_url(path):
        relative = str(path.relative_to(root))
        return urljoin(base_url.rstrip('/') + '/', relative[:-10] if relative.endswith('index.html') else relative)
    for path, doc in documents.items():
        url = page_url(path)
        if not doc.lang or doc.direction not in ('ltr', 'rtl', 'auto'):
            problem(path, 'missing language or invalid direction')
        if doc.lang and doc.lang.split('-')[0] in ('ar', 'he', 'fa', 'ur') and doc.direction != 'rtl':
            problem(path, 'RTL language lacks rtl direction')
        alternate_targets = {local_path(root, base_url, href, url) for _, href in doc.alternates}
        if doc.alternates and path not in alternate_targets:
            problem(path, 'hreflang missing self membership')
        if len(doc.canonicals) != 1 or not urlsplit(doc.canonicals[0]).netloc:
            problem(path, 'expected one absolute canonical')
        else:
            canonical = doc.canonicals[0]
            if canonical in canonicals:
                problem(path, 'canonical reused by ' + str(canonicals[canonical].relative_to(root)))
            canonicals[canonical] = path
        if not doc.title.strip() or not any(doc.descriptions):
            missing_metadata.append(str(path.relative_to(root)))
        for duplicate in doc.duplicates:
            problem(path, 'duplicate ID: ' + duplicate)
        for raw in doc.jsonld:
            try:
                json.loads(raw)
            except ValueError:
                problem(path, 'invalid JSON-LD syntax')
        for link in doc.links:
            target = local_path(root, base_url, link, url)
            if target is not None:
                if not target.exists():
                    problem(path, 'broken local link: ' + link)
                elif urlsplit(link).fragment and target in documents and unquote(urlsplit(link).fragment) not in documents[target].ids:
                    problem(path, 'missing local fragment: ' + link)
        for lang, link in doc.alternates:
            target = local_path(root, base_url, link, url)
            if target not in documents:
                problem(path, 'hreflang target unavailable: ' + link)
            else:
                peer = documents[target]
                if lang != 'x-default' and peer.lang != lang:
                    problem(path, 'hreflang language mismatch: ' + link)
                peer_targets = {local_path(root, base_url, href, page_url(target)) for _, href in peer.alternates}
                if path not in peer_targets:
                    problem(path, 'hreflang missing reciprocal membership: ' + link)
                if peer_targets != alternate_targets:
                    problem(path, 'hreflang alternate membership differs: ' + link)
    sitemaps = {}
    for path in root.rglob('*.xml'):
        data = path.read_bytes()
        if b'<urlset' not in data and b'<sitemapindex' not in data:
            continue
        result = sitemap_check(data)
        sitemaps[str(path.relative_to(root))] = result
        for issue in result['errors']:
            problem(path, issue)
        for link in result['urls'] + result['indexes']:
            target = local_path(root, base_url, link, page_url(path))
            if target is None or not target.exists():
                problem(path, 'sitemap target unavailable: ' + link)
    robots = root / 'robots.txt'
    robots_refs = []
    if robots.exists():
        robots_refs = re.findall(r'^Sitemap:\s*(\S+)', robots.read_text(), re.I | re.M)
        for link in robots_refs:
            target = local_path(root, base_url, link, base_url)
            if target is None or not target.exists():
                problem(robots, 'robots sitemap unavailable: ' + link)
    return {'attribution': 'Static generated-output findings; compare identical source templates/upstream before attributing an engine regression.', 'status': 'fail' if errors else 'pass', 'errors': errors, 'html_count': len(documents),
            'missing_title_or_description': missing_metadata, 'metadata_status': 'missing' if missing_metadata else 'present',
            'jsonld_documents': sum(bool(d.jsonld) for d in documents.values()),
            'robots_status': 'present' if robots.exists() else 'absent', 'robots_sitemap_references': robots_refs,
            'sitemap_status': 'present' if sitemaps else 'absent', 'sitemaps': sitemaps}


def delivery(root, page, base_url):
    root = Path(root).resolve()
    first = (root / page).resolve()
    if not first.is_relative_to(root) or not first.is_file():
        raise ValueError('representative page must exist inside output root')
    pending, seen, external, missing = [first], {}, set(), set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        data = path.read_bytes()
        seen[path] = {'path': str(path.relative_to(root)), **encoded_bytes(data)}
        url = urljoin(base_url.rstrip('/') + '/', str(path.relative_to(root)))
        refs = []
        if path.suffix == '.html':
            refs = Document(data.decode(errors='replace')).resources
        elif path.suffix == '.css':
            text = data.decode(errors='replace')
            refs = re.findall(r'url\(\s*[\'\"]?([^\)\'\"\s]+)', text)
            refs += re.findall(r'@import\s+[\'\"]([^\'\"]+)', text)
        for reference in refs:
            if reference.startswith(('data:', '#')):
                continue
            target = local_path(root, base_url, reference, url)
            if target is None:
                external.add(urljoin(url, reference))
            elif not target.is_file():
                missing.add(str(target.relative_to(root)))
            elif target not in seen:
                pending.append(target)
    resources = list(seen.values())
    return {'measurement': 'static potential dependency graph; srcset alternatives included; no JS-discovered requests',
            'cache_assumption': 'cold visit, unique local URLs; repeat shared resources assumed cached only when explicitly subtracted',
            'potential_local_requests': len(resources), 'raw_bytes': sum(r['raw_bytes'] for r in resources),
            'gzip_bytes': sum(r['gzip_bytes'] for r in resources), 'gzip_policy': 'all files individually encoded, Python gzip level 9, mtime=0; server may choose differently',
            'brotli_status': 'measured' if brotli is not None or NODE_BROTLI else 'unsupported: optional encoder unavailable',
            'brotli_bytes': sum(r['brotli_bytes'] for r in resources) if brotli is not None or NODE_BROTLI else None,
            'encoder_versions': encoder_versions(), 'external_dependencies': sorted(external),
            'missing_dependencies': sorted(missing), 'resources': resources}


def binary_metrics(path):
    path = Path(path)
    data = path.read_bytes()
    return {'path': str(path.resolve()), 'physical_bytes': len(data), 'KiB': len(data) / 1024,
            'sha256': hashlib.sha256(data).hexdigest(), 'strip_state': 'unknown unless supplied in provenance',
            'compilation_time_status': 'not measured'}
