#!/usr/bin/env python3
"""Compare a controlled matrix to a previous fork release, without engine runs."""
import argparse
import json
from pathlib import Path

METHOD = 'fresh exec broker inner-engine wait4; outer wrapper RSS excluded'
METRICS = {'median_seconds': .1, 'median_cpu_seconds': .1, 'max_peak_rss_bytes': 32*1024**2}


def compare(current, previous, relative=.15):
    errors, rows = [], []
    for key in ('fixture_version', 'compatibility_policy', 'platform', 'cpu_model'):
        if current.get(key) is None or current.get(key) != previous.get(key):
            errors.append('incompatible or missing '+key)
    for key in ('threads', 'warmups', 'feed_limit'):
        if current.get('parameters', {}).get(key) is None or current['parameters'][key] != previous.get('parameters', {}).get(key):
            errors.append('incompatible or missing parameter '+key)
    for key in ('toolchain', 'features', 'profile'):
        if current.get('fork_build', {}).get(key) is None or current['fork_build'][key] != previous.get('fork_build', {}).get(key):
            errors.append('incompatible or missing fork build '+key)
    for report, label in ((current, 'current'), (previous, 'previous')):
        if report.get('fork_build', {}).get('binary_sha256') != report.get('binary_sha256') or not report.get('binary_sha256'):
            errors.append(label+' missing or mismatched fork build attestation')
    old = {(c['articles'], c['languages'], c['profile']): c for c in previous.get('cases', [])}
    matched = set()
    for case in current.get('cases', []):
        key = (case['articles'], case['languages'], case['profile'])
        if key not in old:
            rows.append({'case': key, 'status': 'new_case_no_baseline'}); continue
        matched.add(key); before = old[key]
        if case.get('fixture_sha256') is None or case['fixture_sha256'] != before.get('fixture_sha256'):
            errors.append(str(key)+' incompatible fixture fingerprint'); continue
        if case.get('status') != 'passed' or before.get('status') != 'passed':
            errors.append(str(key)+' incomplete or failed correctness'); continue
        for mode in ('full', 'incremental'):
            for data, label in ((case, 'current'), (before, 'previous')):
                samples = data.get('samples', {}).get(mode, [])
                if not samples or any(s.get('rss_method') != METHOD or not s.get('exact_output_equal') or any(s.get(k) is None for k in ('seconds', 'cpu_total_seconds', 'peak_rss_bytes')) for s in samples):
                    errors.append(str(key)+' '+mode+' '+label+' missing/incompatible sample method')
            for metric, floor in METRICS.items():
                now = case.get('summary', {}).get(mode, {}).get(metric)
                prior = before.get('summary', {}).get(mode, {}).get(metric)
                if now is None or prior is None or now <= 0 or prior <= 0:
                    errors.append(str(key)+' '+mode+' missing/invalid '+metric); continue
                mad = max(case['summary'][mode].get('mad_seconds', 0), before['summary'][mode].get('mad_seconds', 0)) if metric == 'median_seconds' else 0
                threshold = max(prior*relative, floor, 3*mad)
                rows.append({'case': key, 'mode': mode, 'metric': metric, 'previous': prior, 'current': now, 'ratio': now/prior, 'absolute_increase_threshold': threshold, 'regression': now-prior > threshold, 'inconclusive_noise': now-prior > max(prior*relative, floor) and now-prior <= threshold})
    if not matched: errors.append('no matching cases')
    return {'status': 'incompatible' if errors else ('regression' if any(r.get('regression') for r in rows) else ('inconclusive_noise' if any(r.get('inconclusive_noise') for r in rows) else 'compatible_no_regression_flag')),
            'errors': errors, 'comparisons': rows, 'previous_cases_absent_now': sorted(set(old)-matched),
            'fork_binary_changed': current.get('binary_sha256') != previous.get('binary_sha256'),
            'official_baseline_changed': current.get('upstream', {}).get('binary_sha256') != previous.get('upstream', {}).get('binary_sha256'),
            'fork_dependencies_changed': current.get('fork_build', {}).get('lock_sha256') != previous.get('fork_build', {}).get('lock_sha256'),
            'policy': {'relative_increase': relative, 'absolute_floors': METRICS, 'wall_noise_floor': '3 * larger MAD', 'rss_statistic': 'maximum observed peak; advisory, not statistical significance', 'interpretation': 'Advisory screening only; absence of a flag is not evidence of equivalence or guaranteed safety', 'attribution': 'Observed changes; dependency/compiler/host effects require investigation, not automatic engine attribution'}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('current', type=Path); parser.add_argument('--baseline', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--relative', type=float, default=.15)
    parser.add_argument('--fail-on-regression', action='store_true')
    args = parser.parse_args()
    if args.relative < 0: parser.error('--relative must be nonnegative')
    current = json.loads(args.current.read_text())
    result = compare(current, json.loads(args.baseline.read_text()), args.relative) if args.baseline else {'status': 'initial_history_no_previous_release', 'current': str(args.current), 'note': 'No previous compatible controlled report was supplied; no improvement over a prior fork release is claimed.'}
    args.output.parent.mkdir(parents=True, exist_ok=True);args.output.write_text(json.dumps(result, indent=2)+'\n')
    if result['status'] == 'incompatible' or (args.fail_on_regression and result['status'] == 'regression'): raise SystemExit(1)


if __name__ == '__main__': main()
