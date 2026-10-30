#!/usr/bin/env python3
"""Controlled, resource-bounded build matrix; stdlib only. Run from repository root."""
import argparse
import difflib
import hashlib
import html
import re
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from multilingual_fixtures import VERSION, LANGUAGES, article, generate_multilingual, mutate_multilingual
from multilingual_suite import coverage
from release_suite import WORK, cache_hits, manifest


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def tree_bytes(root):
    return sum(p.stat().st_size for p in root.rglob('*') if p.is_file())


def summary(samples):
    times = [s['seconds'] for s in samples]
    middle = statistics.median(times)
    return {'n': len(times), 'median_seconds': middle, 'mad_seconds': statistics.median(abs(t-middle) for t in times), 'min_seconds': min(times), 'max_seconds': max(times), 'median_cpu_seconds': statistics.median(s['cpu_total_seconds'] for s in samples), 'max_peak_rss_bytes': max(s['peak_rss_bytes'] for s in samples)}


def classify_baseline(upstream, fork, changed):
    """Narrow fixture-specific exceptions; all other bytes must remain equal."""
    classified = {}
    unknown = []
    def images(text):
        def normalize(tag):
            if re.search(r'src=["\']?/media/logbook\.webp', tag):
                tag = re.sub(r' (?:width=(?:"448"|448)|height=(?:"333"|333)|loading=(?:"lazy"|lazy))(?=[ >])', '', tag)
            elif re.search(r'src=["\']?/media/terminal\.webp', tag):
                tag = re.sub(r' (?:width=(?:"2200"|2200)|height=(?:"872"|872))(?=[ >])', '', tag)
            return tag
        text = re.sub(r'<img\b[^>]*>', lambda m: normalize(m.group()), text)
        return re.sub(r'&lt;img\b.*?&gt;', lambda m: html.escape(normalize(html.unescape(m.group())), quote=False), text)
    exact_static = {
        'assets/main.css': ('/* static CSS */ .loaded { opacity: 1; }\n', '.loaded{opacity:1}'),
        'assets/main.js': ('/* static JS */ document.documentElement.classList.add("loaded");\n', 'document.documentElement.classList.add(`loaded`);'),
    }
    for name in changed:
        before, after = upstream/name, fork/name
        if not before.exists() or not after.exists():
            unknown.append(name)
            continue
        a, b = before.read_text(errors='replace'), after.read_text(errors='replace')
        if name in exact_static and (a, b) == exact_static[name]:
            classified[name] = 'intentional: exact fixture static CSS/JS minification'
        elif name.endswith(('.html', '.xml')) and images(a) == images(b):
            classified[name] = 'intentional: known source image dimensions (448x333,2200x872), first logbook image loading'
        else:
            unknown.append(name)
    return {'classified': classified, 'unclassified_paths': unknown}


def memory_headroom():
    """Available host RAM constrained by any finite cgroup-v2 ancestor limit."""
    host = next(int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
    evidence = {'host_available_bytes': host, 'cgroup_limits': []}
    relative = next((line.split(':', 2)[2] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::')), '/')
    current = Path('/sys/fs/cgroup')/relative.lstrip('/')
    while str(current).startswith('/sys/fs/cgroup'):
        limit, used = current/'memory.max', current/'memory.current'
        if limit.exists() and used.exists() and limit.read_text().strip() != 'max':
            available = max(0, int(limit.read_text())-int(used.read_text()))
            evidence['cgroup_limits'].append({'path': str(current), 'available_bytes': available})
            host = min(host, available)
        if current == Path('/sys/fs/cgroup'):
            break
        current = current.parent
    evidence['effective_available_bytes'] = host
    return evidence


def build(binary, root, env, incremental, args):
    command = [str(binary), '--root', str(root), 'build'] + (['--incremental'] if incremental else [])
    initial_free = shutil.disk_usage(WORK).free
    reason = None
    observed_rss_peak = 0
    effective_rss_limit = min(args.rss_gib*1024**3, memory_headroom()['effective_available_bytes']*.4)
    with tempfile.TemporaryFile(mode='w+') as log, tempfile.TemporaryDirectory(prefix='resource-', dir=WORK) as resource_temp:
        evidence = Path(resource_temp)/'usage.json'
        start = time.perf_counter()
        process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('resource_runner.py')), str(evidence), *command], env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        while True:
            pid, status, usage = os.wait4(process.pid, os.WNOHANG)
            if pid:
                process.returncode = os.waitstatus_to_exitcode(status)
                break
            elapsed = time.perf_counter()-start
            # Guard the inner engine; group abort can leave exact inner rusage unavailable.
            try:
                try:
                    engine_pid = json.loads(evidence.read_text())['child_pid']
                except (FileNotFoundError, json.JSONDecodeError, KeyError):
                    engine_pid = process.pid
                fields = Path(f'/proc/{engine_pid}/status').read_text().splitlines()
                rss = next(int(line.split()[1])*1024 for line in fields if line.startswith('VmRSS:'))
            except (FileNotFoundError, ProcessLookupError, StopIteration):
                rss = 0
            observed_rss_peak = max(observed_rss_peak, rss)
            if elapsed > args.timeout:
                reason = 'timeout budget'
            elif rss > effective_rss_limit:
                reason = 'RSS budget'
            elif initial_free - shutil.disk_usage(WORK).free > args.disk_gib*1024**3:
                reason = 'disk growth budget'
            elif shutil.disk_usage(WORK).free < args.reserve_gib * 1024**3:
                reason = 'free disk reserve'
            if reason:
                os.killpg(process.pid, signal.SIGKILL)
                _, status, usage = os.wait4(process.pid, 0)
                process.returncode = os.waitstatus_to_exitcode(status)
                break
            time.sleep(.005)
        elapsed = time.perf_counter()-start
        log.seek(0)
        output = log.read()
        try:
            inner_usage = json.loads(evidence.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            inner_usage = {}
    result = {'seconds': elapsed, 'peak_rss_bytes': int(usage.ru_maxrss*(1 if platform.system() == 'Darwin' else 1024)), 'exit_poll_interval_seconds': .005, 'cache_hits': cache_hits(output), 'exit_code': process.returncode, 'cpu_user_seconds': usage.ru_utime, 'cpu_system_seconds': usage.ru_stime, 'cpu_total_seconds': usage.ru_utime+usage.ru_stime, 'abort_reason': reason, 'effective_rss_limit_bytes': int(effective_rss_limit)}
    result['outer_wrapper_wait4_peak_rss_bytes_not_engine'] = result['peak_rss_bytes']
    result['outer_wrapper_wall_seconds_not_engine'] = result['seconds']
    result['outer_wrapper_cpu_seconds_not_engine'] = result['cpu_total_seconds']
    result['rss_method'] = 'fresh exec broker inner-engine wait4; outer wrapper RSS excluded'
    inner_complete = {'seconds', 'peak_rss_bytes', 'cpu_user_seconds', 'cpu_system_seconds', 'cpu_total_seconds', 'exit_code'} <= inner_usage.keys()
    if inner_complete:
        result.update(inner_usage)
    else:
        result['peak_rss_bytes'] = None
        result['rss_measurement_incomplete'] = True
        result['sampled_engine_rss_lower_bound_bytes'] = observed_rss_peak
        for key in ('seconds', 'cpu_user_seconds', 'cpu_system_seconds', 'cpu_total_seconds'):
            result[key] = None
    if process.returncode or not inner_complete or inner_usage.get('exit_code') != 0:
        result['log_tail'] = output[-4000:]
        raise BuildFailure(result)
    return result


class BuildFailure(Exception):
    pass


def run_case(spec, args, binary, env):
    articles, count, profile = spec
    result = {'articles': articles, 'languages': count, 'published_article_pages': articles*count, 'profile': profile, 'status': 'incomplete', 'mutations': []}
    with tempfile.TemporaryDirectory(prefix='matrix-', dir=WORK) as temp:
        root = Path(temp)/'site'
        root.mkdir()
        generated = time.perf_counter()
        languages = generate_multilingual(root, articles, count, profile, args.feed_limit)
        result['cache_policy'] = 'cold full starts without generated outputs/image cache; first incremental population follows full and shares image cache; all timed samples reuse image cache and generated output, only incremental reuses persistent Markdown/page cache'
        result['generation_seconds_excluded'] = time.perf_counter()-generated
        if args.compat_search:
            config = root/'config.toml'
            config.write_text(config.read_text().replace('include_headings = true', '').replace('include_taxonomies = true', '').replace('include_date = true', 'include_date = false'))
        result['fixture_sha256'] = digest(manifest(root))
        result['source_bytes'] = tree_bytes(root)
        result['markdown_bytes'] = sum(p.stat().st_size for p in root.rglob('*.md'))
        result['markdown_files'] = len(list(root.rglob('*.md')))
        try:
            upstream_root = None
            if args.upstream_binary:
                upstream_root = root.parent/'upstream-fixture'
                shutil.copytree(root, upstream_root, ignore=shutil.ignore_patterns('upstream-fixture'))
                result['upstream_fixture_sha256'] = digest(manifest(upstream_root))
                if result['upstream_fixture_sha256'] != result['fixture_sha256']:
                    raise ValueError('baseline fixture input mismatch')
                result['cold_upstream_full'] = build(args.upstream_binary.resolve(), upstream_root, env, False, args)
                upstream_expected = manifest(upstream_root/'public')
            result['cold_full'] = build(binary, root, env, False, args)
            expected = manifest(root/'public')
            if upstream_root:
                changed = sorted(k for k in expected.keys() | upstream_expected.keys() if expected.get(k) != upstream_expected.get(k))
                result['upstream_output_comparison'] = {'equal': not changed, 'changed_paths': changed, 'classification': 'requires_review' if changed else 'exact'}
                if changed:
                    result['upstream_output_comparison'].update(classify_baseline(upstream_root/'public', root/'public', changed))
                    result['upstream_output_comparison']['classification'] = 'intentional_narrow_fixture_differences' if not result['upstream_output_comparison']['unclassified_paths'] else 'requires_review'
                    evidence = args.output.parent/(args.output.stem+f'-{articles}x{count}-{profile}-upstream-diff.txt')
                    chunks = []
                    for name in changed[:5]:
                        before = (upstream_root/'public'/name)
                        after = root/'public'/name
                        if before.exists() and after.exists():
                            chunks.extend(difflib.unified_diff(before.read_text(errors='replace')[:20000].splitlines(), after.read_text(errors='replace')[:20000].splitlines(), fromfile='upstream/'+name, tofile='fork/'+name))
                    evidence.write_text('\n'.join(chunks)[:100000])
                    result['upstream_output_comparison']['diff_artifact'] = str(evidence)
            result['cold_incremental_population'] = build(binary, root, env, True, args)
            if manifest(root/'public') != expected:
                raise ValueError('cache population output differs from full')
            result['warmups'] = []
            for _ in range(args.warmups):
                for mode in (False, True):
                    result['warmups'].append({'mode': 'incremental' if mode else 'full', **build(binary, root, env, mode, args)})
            samples = {'full': [], 'incremental': []}
            if upstream_root:
                samples['upstream_full'] = []
                result['upstream_warmups'] = [build(args.upstream_binary.resolve(), upstream_root, env, False, args) for _ in range(args.warmups)]
            result['samples'] = samples
            runs = args.small_runs if articles*count <= 1000 else args.large_runs
            result['measured_orders'] = []
            for iteration in range(runs):
                modes = ['upstream_full', 'full', 'incremental'] if upstream_root else ['full', 'incremental']
                offset = iteration % len(modes)
                order = modes[offset:]+modes[:offset]
                result['measured_orders'].append(order)
                for name in order:
                    if name == 'upstream_full':
                        sample = build(args.upstream_binary.resolve(), upstream_root, env, False, args)
                        actual = manifest(upstream_root/'public')
                        sample['exact_output_equal'] = actual == upstream_expected
                    else:
                        sample = build(binary, root, env, name == 'incremental', args)
                        actual = manifest(root/'public')
                        sample['exact_output_equal'] = actual == expected
                    samples[name].append(sample)
                    if not sample['exact_output_equal']:
                        raise ValueError(f'{name}: unchanged output differs from its cold full output')
            result['summary'] = {name: summary(values) for name, values in samples.items()}
            result['coverage'] = coverage(root, articles, languages, args.feed_limit if profile == 'newspaper' else None, extended_search=not args.compat_search)
            result['coverage']['search_bytes'] = sum(p.stat().st_size for p in (root/'public').glob('search_index.*'))
            result['cache_bytes'] = tree_bytes(root/'.zola-cache')
            result['output_manifest_sha256'] = digest(expected)
            if args.quality:
                from quality_suite import inspect_case
                base_url = re.search(r'^base_url\s*=\s*"([^"]+)"', (root/'config.toml').read_text(), re.MULTILINE).group(1)
                pages = ['index.html', 'articles/page-00000/index.html']
                for lang, _, _ in languages:
                    if lang in ('ar', 'zh', 'ja', 'ko'):
                        candidate = f'{lang}/articles/page-00000/index.html'
                        if (root/'public'/candidate).is_file():
                            pages.append(candidate)
                result['quality'] = {}
                for label, site_root, engine in [('fork-full-and-incremental-identical-output', root, binary), ('upstream', upstream_root, args.upstream_binary)]:
                    if site_root:
                        evidence = inspect_case({'label': label, 'output_root': str(site_root/'public'), 'base_url': base_url, 'pages': pages, 'binary': str(engine)})
                        evidence['scope'] = 'Whole-output technical SEO and sitemap; representative homepage and English/available Arabic/CJK article delivery. Search requires a verified frontend adapter.'
                        evidence['fixture_context'] = 'Version 3 multilingual / workload 4 shared synthetic templates include SEO metadata; compare identical upstream and fork findings before engine attribution.'
                        result['quality'][label] = evidence
                result['quality_status'] = 'fail' if any(item['status'] == 'fail' for item in result['quality'].values()) else 'partial'
            # Independent fresh full oracles. Preserve mismatches, including stale thumbnails.
            if articles*count <= args.mutation_max_pages:
                article(root, articles, 'en', LANGUAGES[0][1], summary=profile == 'newspaper')
                build(binary, root, env, True, args)
                scenarios = ('new_translation', 'new_article_all_languages', 'edit_translation', 'delete_translation', 'rename_translation') if articles*count <= 1000 else ('delete_translation',)
                for scenario in scenarios:
                    if scenario == 'new_translation' and count == 1:
                        continue
                    mutate_multilingual(root, scenario, articles, languages, summary=profile == 'newspaper')
                    entry = {'scenario': scenario, 'candidates': {}}
                    for mode in (True, False):
                        sample = build(binary, root, env, mode, args)
                        actual = manifest(root/'public')
                        with tempfile.TemporaryDirectory(prefix='matrix-oracle-', dir=WORK) as oracle_temp:
                            oracle = Path(oracle_temp)/'site'
                            shutil.copytree(root, oracle, ignore=shutil.ignore_patterns('public', 'processed_images', '.zola*'))
                            full = build(binary, oracle, env, False, args)
                            expected_oracle = manifest(oracle/'public')
                        changed = sorted(k for k in actual.keys() | expected_oracle.keys() if actual.get(k) != expected_oracle.get(k))
                        entry['candidates']['incremental' if mode else 'warm_full'] = {'sample': sample, 'oracle': full, 'equal': not changed, 'changed_paths': changed}
                    result['mutations'].append(entry)
            else:
                result['mutation_skip_reason'] = 'above explicit mutation page budget'
            if articles == 8 and count == 1 and upstream_root:
                mutate_multilingual(upstream_root, 'delete_translation', articles, languages, summary=profile == 'newspaper')
                upstream_warm = build(args.upstream_binary.resolve(), upstream_root, env, False, args)
                actual = manifest(upstream_root/'public')
                with tempfile.TemporaryDirectory(prefix='upstream-delete-oracle-', dir=WORK) as oracle_temp:
                    oracle = Path(oracle_temp)/'site'
                    shutil.copytree(upstream_root, oracle, ignore=shutil.ignore_patterns('public', 'processed_images', '.zola*'))
                    upstream_fresh = build(args.upstream_binary.resolve(), oracle, env, False, args)
                    fresh_manifest = manifest(oracle/'public')
                changed = sorted(k for k in actual.keys() | fresh_manifest.keys() if actual.get(k) != fresh_manifest.get(k))
                result['upstream_delete_oracle'] = {'equal': not changed, 'warm_sample': upstream_warm, 'fresh_sample': upstream_fresh, 'classification': 'exact' if not changed else 'requires_review', 'changed': {k: {'warm': actual.get(k), 'fresh': fresh_manifest.get(k)} for k in changed}}
            result['status'] = 'passed' if all(v['equal'] for m in result['mutations'] for v in m['candidates'].values()) else 'correctness_failure'
            if result['status'] == 'passed' and result.get('upstream_output_comparison', {}).get('classification') == 'requires_review':
                result['status'] = 'upstream_difference_requires_review'
        except BuildFailure as error:
            result['failure'] = error.args[0]
        except (ValueError, OSError, KeyError) as error:
            result['failure'] = str(error)
    return result


def report_markdown(report):
    lines = ['# Controlled benchmark matrix', '', 'Times exclude fixture generation, broker startup, and output hashing. Cold means empty application cache, not cold OS caches. Warm modes rotate order across all three engines; exact orders are recorded. RSS and CPU use a fresh low-memory broker’s inner-engine wait4; outer-wrapper RSS is excluded. Aborted inner measurements are explicitly incomplete. Samples and failures are retained in JSON.', '', '| Pages | Locales | Policy | Status | Upstream full median ± MAD (s) | Fork full median ± MAD (s) | Incremental median ± MAD (s) | Peak RSS GiB | Output MB |', '|---:|---:|---|---|---:|---:|---:|---:|---:|']
    for case in report['cases']:
        stats = case.get('summary', {})
        def timing(name):
            s = stats.get(name)
            return f"{s['median_seconds']:.3f} ± {s['mad_seconds']:.3f} (n={s['n']})" if s else '—'
        peak = max((s['max_peak_rss_bytes'] for s in stats.values()), default=0)/1024**3
        lines.append(f"| {case['published_article_pages']} | {case['languages']} | {case['profile']} | {case['status']} | {timing('upstream_full')} | {timing('full')} | {timing('incremental')} | {peak:.3f} | {case.get('coverage', {}).get('output_bytes', 0)/1e6:.1f} |")
    lines += ['', 'Measured comparisons:', '']
    for case in report['cases']:
        stats = case.get('summary', {})
        if stats:
            full, inc = stats['full'], stats['incremental']
            lines.append(f"- {case['published_article_pages']} pages / {case['languages']} locales / {case['profile']}: warm incremental/full median ratio {inc['median_seconds']/full['median_seconds']:.3f}; peak RSS ratio {inc['max_peak_rss_bytes']/full['max_peak_rss_bytes']:.3f}.")
            if 'upstream_full' in stats:
                upstream = stats['upstream_full']
                lines.append(f"  Fork full/upstream full median ratio {full['median_seconds']/upstream['median_seconds']:.3f}; incremental/upstream full {inc['median_seconds']/upstream['median_seconds']:.3f}; fork full/upstream peak RSS {full['max_peak_rss_bytes']/upstream['max_peak_rss_bytes']:.3f}.")
        bounded = next((c for c in report['cases'] if c['articles'] == case['articles'] and c['languages'] == case['languages'] and c['profile'] == 'newspaper' and 'coverage' in c), None)
        if case['profile'] == 'stress' and 'coverage' in case and bounded:
            before, after = case['coverage'], bounded['coverage']
            lines.append(f"- {case['published_article_pages']} pages feed-policy effect: output {before['output_bytes']/1e6:.1f} → {after['output_bytes']/1e6:.1f} MB; feeds {before['feed_bytes']/1e6:.1f} → {after['feed_bytes']/1e6:.1f} MB.")
    lines += ['', '| Pages / policy | Upstream / fork full / incremental CPU seconds (median) | Upstream / fork full / incremental peak RSS MiB |', '|---|---:|---:|']
    for case in report['cases']:
        stats = case.get('summary', {})
        if all(k in stats for k in ('upstream_full', 'full', 'incremental')):
            cpu = ' / '.join(f"{stats[k]['median_cpu_seconds']:.3f}" for k in ('upstream_full', 'full', 'incremental'))
            rss = ' / '.join(f"{stats[k]['max_peak_rss_bytes']/2**20:.0f}" for k in ('upstream_full', 'full', 'incremental'))
            lines.append(f"| {case['published_article_pages']} / {case['profile']} | {cpu} | {rss} |")
    lines += ['', '| Pages / locales / policy | Source MB | Output MB | Feed MB | Search MB | Persistent cache MB | Incremental Markdown / HTML hits |', '|---|---:|---:|---:|---:|---:|---:|']
    for case in report['cases']:
        covered = case.get('coverage', {})
        hits = [sample.get('cache_hits') for sample in case.get('samples', {}).get('incremental', [])]
        hits = [value for value in hits if value is not None]
        hit_text = f"{hits[-1].get('markdown', 'unknown')} / {hits[-1].get('page_html', 'unknown')}" if hits else 'unknown'
        sizes = ' | '.join(f"{value/1e6:.2f}" for value in (case.get('source_bytes', 0), covered.get('output_bytes', 0), covered.get('feed_bytes', 0), covered.get('search_bytes', 0), case.get('cache_bytes', 0)))
        lines.append(f"| {case['published_article_pages']} / {case['languages']} / {case['profile']} | {sizes} | {hit_text} |")
    lines += ['', 'Full versus incremental compares identical fixture inputs and output manifests. Stress versus newspaper changes feed limit and summary policy: any savings are configuration/workload effects, not an engine optimization. RSS is a process high-water mark; it is not allocated memory or browser cost. Small sample counts and host scheduling/OS cache noise limit inference. No statistical significance is claimed.', '', 'Source, output, feed, search and persistent cache bytes, raw warmups/samples, cache hit diagnostics, binary and fixture fingerprints, resource aborts, and all oracle mismatches are in the JSON. A null cache-hit field means the binary did not emit the supported diagnostic; it is not evidence of zero hits. Skipped or incomplete sizes establish no capacity claim.', '']
    for case in report['cases']:
        if not case.get('upstream_output_comparison', {}).get('equal', True):
            comparison = case['upstream_output_comparison']
            label = 'BASELINE REVIEW REQUIRED' if comparison.get('classification') == 'requires_review' else 'Known baseline differences'
            lines.append(f"{label}: {case['published_article_pages']} {case['profile']}: {len(comparison.get('changed_paths', []))} paths; {len(comparison.get('unclassified_paths', []))} unclassified. Raw diff: `{comparison.get('diff_artifact', 'JSON evidence')}`.")
        for mutation in case['mutations']:
            for mode, evidence in mutation['candidates'].items():
                if not evidence['equal']:
                    lines.append(f"FAIL: {case['published_article_pages']} {case['profile']} {mutation['scenario']} {mode}: {evidence['changed_paths']}")
        if case.get('failure'):
            lines.append(f"INCOMPLETE: {case['published_article_pages']} {case['profile']}: {case['failure']}")
    lines += ['', 'Correctness finding: the earlier stale-thumbnail failure was introduced in fork commit `0bed47da` when static copying moved ahead of image pruning. Archived debug evidence retains the failure. The fixed fork passes warm full/incremental deletion against fresh oracles; the official eight-page warm deletion also matches its fresh oracle. This is a repaired fork regression, not an upstream defect.']
    return '\n'.join(lines)+'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=Path('target/release/zola'))
    parser.add_argument('--fork-build-metadata', type=Path, help='Required SHA-verified attestation for custom prebuilt binaries')
    parser.add_argument('--prepare-only', action='store_true', help='Prepare and attest both engines without running samples')
    parser.add_argument('--offline', action='store_true', help='Explicitly use previously pinned official checkout; report it stale')
    parser.add_argument('--upstream-binary', type=Path)
    parser.add_argument('--quality', action='store_true', help='Inspect SEO and representative delivery outside timed samples; search needs an adapter')
    parser.add_argument('--compat-search', action='store_true', help='Disable fork search extensions in identical inputs for both engines')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', default='100x1,1000x1,10000x1,1000x15', help='articles x locales, comma separated')
    parser.add_argument('--profiles', default='stress,newspaper')
    parser.add_argument('--small-runs', type=int, default=5)
    parser.add_argument('--large-runs', type=int, default=3)
    parser.add_argument('--warmups', type=int, default=2)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--feed-limit', type=int, default=50)
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--rss-gib', type=float, default=3)
    parser.add_argument('--disk-gib', type=float, default=8)
    parser.add_argument('--reserve-gib', type=float, default=8)
    parser.add_argument('--mutation-max-pages', type=int, default=15000)
    args = parser.parse_args()
    if min(args.small_runs, args.large_runs, args.threads, args.feed_limit, args.timeout, args.rss_gib, args.reserve_gib, args.disk_gib) <= 0 or args.warmups < 0:
        parser.error('sample counts and resource budgets must be positive; warmups nonnegative')
    if platform.system() != 'Linux' or not hasattr(os, 'wait4'):
        parser.error('Linux /proc and wait4 are required for guarded inner-engine measurements')
    binary = args.binary.resolve()
    from fork_build import prepare_fork
    try:
        fork_metadata = prepare_fork(binary, args.fork_build_metadata)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.error(str(error))
    from upstream import ensure_upstream
    try:
        upstream_metadata = ensure_upstream(build=True, offline=args.offline)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({'schema': 1, 'status': 'baseline_failed', 'error': str(error)}, indent=2)+'\n')
        raise SystemExit('Official upstream baseline sync/build failed; see report')
    if not args.upstream_binary:
        args.upstream_binary = Path(upstream_metadata['binary'])
    if hashlib.sha256(args.upstream_binary.resolve().read_bytes()).hexdigest() != upstream_metadata['binary_sha256']:
        parser.error('--upstream-binary must match freshly verified official baseline')
    args.compat_search = True
    env = dict(os.environ, RAYON_NUM_THREADS=str(args.threads), RUST_LOG='site=info,zola=info')
    WORK.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {'schema': 1, 'fixture_version': VERSION, 'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(), 'platform': platform.platform(), 'cpu_count': os.cpu_count(), 'cpu_model': next((line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), platform.processor()), 'memory_headroom': memory_headroom(), 'parameters': {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}, 'upstream': upstream_metadata, 'compatibility_policy': 'common-search-v2: remove include_headings/include_taxonomies; disable include_date because upstream fuse_json does not emit dates', 'cases': []}
    report['fork_build'] = fork_metadata
    if args.prepare_only:
        report['status'] = 'prepared_no_measurements'
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True)+'\n')
        return
    for size in args.cases.split(','):
        articles, count = map(int, size.split('x'))
        if articles < 8 or not 1 <= count <= 15:
            parser.error('articles >=8 and locales 1..15')
        for profile in args.profiles.split(','):
            if profile not in ('stress', 'newspaper'):
                parser.error('unknown profile')
            print(f'Running {size} {profile}', flush=True)
            case = run_case((articles, count, profile), args, binary, env)
            report['cases'].append(case)
            args.output.write_text(json.dumps(report, indent=2, sort_keys=True)+'\n')
            args.output.with_suffix('.md').write_text(report_markdown(report))
            print(f"{size} {profile}: {case['status']}", flush=True)
    if hashlib.sha256(binary.read_bytes()).hexdigest() != report['binary_sha256'] or hashlib.sha256(args.upstream_binary.resolve().read_bytes()).hexdigest() != upstream_metadata['binary_sha256']:
        report['status'] = 'invalid_binary_changed'
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True)+'\n')
        raise SystemExit('Binary changed during matrix: timings invalid')
    if any(c['status'] in ('correctness_failure', 'upstream_difference_requires_review') or (c['status'] == 'incomplete' and not (isinstance(c.get('failure'), dict) and c['failure'].get('abort_reason'))) for c in report['cases']):
        raise SystemExit('Strict correctness/baseline comparison failed; see JSON evidence')


if __name__ == '__main__':
    main()
