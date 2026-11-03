#!/usr/bin/env python3
"""Focused remaining checks, reusing guarded engine measurements; stdlib only.

No production files are written. Results are checkpointed after every scenario.
"""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from fixtures import mutate
from matrix import build, BuildFailure, digest, memory_headroom, summary
from multilingual_fixtures import generate_multilingual, mutate_multilingual, suffix
from release_suite import WORK, manifest


def proc_snapshot():
    """Counters permit interval CPU accounting without retaining command lines."""
    processes = {}
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            text = (entry/'stat').read_text()
            end = text.rindex(')')
            fields = text[end+2:].split()
            processes[entry.name] = {'name': text[text.index('(')+1:end],
                'ticks': int(fields[11])+int(fields[12]), 'start': fields[19]}
        except (OSError, ValueError, IndexError):
            pass
    return {'monotonic': time.monotonic(), 'processes': processes,
            'load_average': list(os.getloadavg()), 'memory': memory_headroom()}


def noise_interval(before, after, seconds):
    ticks = os.sysconf('SC_CLK_TCK')
    total = sum(max(0, p['ticks']-before['processes'].get(pid, {}).get('ticks', p['ticks']))
                for pid, p in after['processes'].items()
                if before['processes'].get(pid, {}).get('start') == p['start']) / ticks
    # Engine has exited and is absent from /proc. Persistent-process CPU is
    # therefore external to it (includes the light benchmark coordinator).
    top = sorted(({'pid': pid, 'name': p['name'],
                   'cpu_seconds': (p['ticks']-before['processes'][pid]['ticks'])/ticks}
                  for pid, p in after['processes'].items()
                  if pid in before['processes'] and before['processes'][pid]['start'] == p['start']),
                 key=lambda p: p['cpu_seconds'], reverse=True)[:8]
    return {'persistent_external_cpu_seconds': total, 'external_cpu_cores': total/seconds,
            'top': top, 'limitation': 'Exited external processes are not observed; persistent processes only.'}


def compatibility(root):
    path = root/'config.toml'
    path.write_text(path.read_text().replace('include_headings = true', '')
                    .replace('include_taxonomies = true', '').replace('include_date = true', 'include_date = false'))


def fresh_oracle(root, binary, env, args):
    oracle = root.parent/'oracle'
    shutil.copytree(root, oracle, ignore=shutil.ignore_patterns('public', 'processed_images', '.zola*'))
    try:
        sample = build(binary, oracle, env, False, args)
        return manifest(oracle/'public'), sample
    finally:
        shutil.rmtree(oracle)


def mutations(root, articles, languages, binary, env, args, checkpoint):
    result = []
    config = root/'config.toml'
    config.write_text(config.read_text()+'\n[translations]\nverification = "original language string"\n')
    template = root/'templates/base.html'
    template.write_text(template.read_text().replace('<main>', '<main><span>{{ trans(key="verification", lang="en") }}</span>'))
    build(binary, root, env, True, args)
    scenarios = ['new_article_all_languages', 'edit_translation', 'metadata', 'delete_translation',
                 'rename_translation', 'template', 'sass', 'media', 'asset', 'language']
    for scenario in scenarios:
        if scenario in ('new_article_all_languages', 'edit_translation', 'delete_translation', 'rename_translation'):
            mutate_multilingual(root, scenario, articles, languages, summary=True)
        elif scenario == 'metadata':
            path = root/f'content/articles/page-00003{suffix(languages[-1][0])}.md'
            path.write_text(path.read_text().replace('date = 2024-01-04', 'date = 2025-02-03')
                            .replace('description = "', 'description = "Metadata changed '))
        elif scenario == 'template':
            path = root/'templates/base.html'
            path.write_text(path.read_text().replace('<main>', '<main data-verification="updated">'))
        elif scenario == 'language':
            path = root/'config.toml'
            path.write_text(path.read_text().replace('original language string', 'changed language configuration'))
        else:
            mutate(root, scenario, articles)
        candidate_sample = build(binary, root, env, True, args)
        candidate = manifest(root/'public')
        expected, oracle_sample = fresh_oracle(root, binary, env, args)
        changed = sorted(k for k in candidate.keys() | expected.keys() if candidate.get(k) != expected.get(k))
        result.append({'scenario': scenario, 'equal': not changed, 'changed_paths': changed,
                       'candidate': candidate_sample, 'oracle': oracle_sample,
                       'oracle_manifest_sha256': digest(expected)})
        checkpoint(result)
        if changed:
            break
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['timing', 'mutations', 'capacity', 'personal'])
    parser.add_argument('--personal-root', type=Path, default=Path('..'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--articles', type=int, default=1000)
    parser.add_argument('--languages', type=int, default=15)
    parser.add_argument('--cycles', type=int, default=9)
    parser.add_argument('--binary', type=Path, default=Path('target/release/zola'))
    parser.add_argument('--upstream-binary', type=Path, default=WORK/'upstream-target/release/zola')
    parser.add_argument('--rss-gib', type=float, default=6)
    parser.add_argument('--timeout', type=float, default=600)
    parser.add_argument('--external-cores', type=float, default=.75)
    args = parser.parse_args()
    args.disk_gib, args.reserve_gib = 20, 12
    args.binary, args.upstream_binary = args.binary.resolve(), args.upstream_binary.resolve()
    if args.work.exists():
        parser.error('Use a fresh work directory; existing evidence is never overwritten')
    args.work = args.work.resolve()
    args.work.mkdir(parents=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {'schema': 1, 'mode': args.mode, 'parameters': {k: str(v) if isinstance(v, Path) else v for k,v in vars(args).items()},
              'memory_preflight': memory_headroom(), 'binaries': {}, 'status': 'running'}
    for name in ('binary', 'upstream_binary'):
        binary = getattr(args, name)
        report['binaries'][name] = {'path': str(binary), 'sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}
    def save():
        args.output.write_text(json.dumps(report, indent=2)+'\n')
    save()
    env = dict(os.environ, RAYON_NUM_THREADS='4', RUST_LOG='site=info,zola=info')
    root = args.work/'site'
    root.mkdir()
    try:
        if args.mode == 'personal':
            source = args.personal_root.resolve()
            for name in ('content', 'static', 'templates', 'themes', 'sass', '.git'):
                path = source/name
                if path.is_dir():
                    shutil.copytree(path, root/name, ignore=shutil.ignore_patterns('.git') if name != '.git' else None)
                elif path.is_file():
                    shutil.copy2(path, root/name)
            shutil.copy2(source/'config.toml', root/'config.toml')
            report['production_input_sha256'] = digest(manifest(root))
            report['production_config_sha256'] = hashlib.sha256((root/'config.toml').read_bytes()).hexdigest()
            try:
                report['original_upstream'] = build(args.upstream_binary, root, env, False, args)
            except BuildFailure as error:
                report['original_upstream'] = error.args[0]
            report['original_fork_full'] = build(args.binary, root, env, False, args)
            original = manifest(root/'public')
            report['original_fork_incremental'] = build(args.binary, root, env, True, args)
            report['production_full_incremental_exact'] = original == manifest(root/'public')
            # Explicitly separate compatible semantics from the production setting.
            config = root/'config.toml'
            previous = config.read_text()
            config.write_text(previous.replace('infer_updated_from_git = true', ''))
            report['compatibility_changes'] = ['Remove unsupported infer_updated_from_git in BOTH engines; inferred modification dates are excluded from this comparison.']
            report['compatible_config_sha256'] = hashlib.sha256(config.read_bytes()).hexdigest()
            shutil.rmtree(root/'public', ignore_errors=True)
            shutil.rmtree(root/'.zola-cache', ignore_errors=True)
            upstream = args.work/'official'
            shutil.copytree(root, upstream, ignore=shutil.ignore_patterns('public', 'processed_images', '.zola*'))
            modes = {'upstream_full': (args.upstream_binary, upstream, False),
                     'full': (args.binary, root, False), 'incremental': (args.binary, root, True)}
            report['samples'] = {name: [] for name in modes}
            expected = {}
            for name, (binary, site, incremental) in modes.items():
                report['samples'][name].append(build(binary, site, env, incremental, args))
                expected[name] = manifest(site/'public')
            report['compatible_full_incremental_exact'] = expected['full'] == expected['incremental']
            changed = sorted(k for k in expected['full'].keys() | expected['upstream_full'].keys()
                             if expected['full'].get(k) != expected['upstream_full'].get(k))
            report['changed_paths'] = changed
            diffroot = args.work/'diffs'
            diffroot.mkdir()
            for i, name in enumerate(changed):
                a, b = upstream/'public'/name, root/'public'/name
                (diffroot/f'{i:04}.diff').write_text('\n'.join(difflib.unified_diff(
                    a.read_text(errors='replace').splitlines() if a.exists() else [],
                    b.read_text(errors='replace').splitlines() if b.exists() else [],
                    fromfile='official/'+name, tofile='fork/'+name)))
            report['diff_directory'] = str(diffroot)
            for cycle in range(args.cycles):
                names = list(modes)
                names = names[cycle%3:]+names[:cycle%3]
                for name in names:
                    binary, site, incremental = modes[name]
                    sample = build(binary, site, env, incremental, args)
                    sample['exact_output_equal'] = expected[name] == manifest(site/'public')
                    report['samples'][name].append(sample)
                    save()
            report['summary'] = {name: summary(samples[1:]) for name,samples in report['samples'].items()}
            report['status'] = 'upstream_differences_require_review' if changed else 'passed'
            save()
            return
        languages = generate_multilingual(root, args.articles, args.languages, 'newspaper', 50)
        compatibility(root)
        report['fixture_sha256'] = digest(manifest(root))
        if args.mode == 'mutations':
            def checkpoint(entries):
                report['mutations'] = entries
                save()
            entries = mutations(root, args.articles, languages, args.binary, env, args, checkpoint)
            report['status'] = 'passed' if all(e['equal'] for e in entries) else 'correctness_failure'
        else:
            upstream = args.work/'official'
            shutil.copytree(root, upstream)
            modes = {'upstream_full': (args.upstream_binary, upstream, False),
                     'full': (args.binary, root, False), 'incremental': (args.binary, root, True)}
            report['population'] = {}
            report['samples'] = {name: [] for name in modes}
            expected = {}
            for name, (binary, site, incremental) in modes.items():
                report['population'][name] = build(binary, site, env, incremental, args)
                expected[name] = manifest(site/'public')
                save()
            report['fork_full_incremental_exact'] = expected['full'] == expected['incremental']
            from matrix import classify_baseline
            changed = sorted(k for k in expected['full'].keys() | expected['upstream_full'].keys()
                             if expected['full'].get(k) != expected['upstream_full'].get(k))
            report['official_comparison'] = classify_baseline(upstream/'public', root/'public', changed)
            report['warmups'] = {}
            for name, (binary, site, incremental) in modes.items():
                report['warmups'][name] = build(binary, site, env, incremental, args)
            report['orders'] = []
            for cycle in range(args.cycles if args.mode == 'timing' else 1):
                order = list(modes)
                offset = cycle % len(order)
                order = order[offset:]+order[:offset]
                report['orders'].append(order)
                for name in order:
                    binary, site, incremental = modes[name]
                    before = proc_snapshot()
                    sample = build(binary, site, env, incremental, args)
                    after = proc_snapshot()
                    sample['noise'] = noise_interval(before, after, sample['seconds'])
                    sample['noise_gate_passed'] = sample['noise']['external_cpu_cores'] <= args.external_cores
                    sample['exact_output_equal'] = manifest(site/'public') == expected[name]
                    report['samples'][name].append(sample)
                    save()
            report['summary'] = {name: summary(samples) for name,samples in report['samples'].items()}
            report['noise_gate'] = {'max_external_cores': args.external_cores,
                'passed': all(s['noise_gate_passed'] for samples in report['samples'].values() for s in samples)}
            report['status'] = 'passed' if report['fork_full_incremental_exact'] and not report['official_comparison']['unclassified_paths'] and all(s['exact_output_equal'] for samples in report['samples'].values() for s in samples) else 'correctness_failure'
    except BuildFailure as error:
        report['status'] = 'resource_guard' if error.args[0].get('abort_reason') else 'build_failure'
        report['failure'] = error.args[0]
    except Exception as error:
        report['status'], report['failure'] = 'failed', repr(error)
        raise
    finally:
        save()
    print(json.dumps({'status': report['status'], 'output': str(args.output)}), flush=True)
    if report['status'] in ('correctness_failure', 'build_failure', 'failed'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
