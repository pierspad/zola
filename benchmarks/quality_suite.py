#!/usr/bin/env python3
"""Attach quality/reader evidence to existing matrix outputs; never rerun builds."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from quality_metrics import binary_metrics, delivery, technical_seo


def inspect_case(case):
    root = Path(case['output_root']).resolve()
    result = {'label': case['label'], 'output_root': str(root), 'base_url': case['base_url']}
    if not root.is_dir():
        return {**result, 'status': 'fail', 'reason': 'output root missing'}
    files = sorted(p for p in root.rglob('*') if p.is_file())
    result['output_manifest_sha256'] = hashlib.sha256(json.dumps({str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}, sort_keys=True).encode()).hexdigest()
    result['technical_seo'] = technical_seo(root, case['base_url'])
    result['reader_delivery'] = [delivery(root, page, case['base_url']) for page in case['pages']]
    if case.get('binary'):
        result['binary'] = binary_metrics(case['binary'])
    search_spec = case.get('search_spec')
    if not search_spec:
        result['search'] = {'status': 'unsupported', 'reason': 'No verified shipped frontend runtime adapter and query oracle supplied; index existence is not search quality.'}
    elif not shutil.which('node'):
        result['search'] = {'status': 'unsupported', 'reason': 'Node runtime unavailable'}
    else:
        try:
            process = subprocess.run(['node', str(Path(__file__).with_name('search_probe.mjs')), search_spec], capture_output=True, text=True, timeout=case.get('search_timeout_seconds', 60))
            result['search'] = json.loads(process.stdout) if process.returncode == 0 else {'status': 'fail', 'stderr': process.stderr, 'returncode': process.returncode}
        except (subprocess.TimeoutExpired, ValueError) as error:
            result['search'] = {'status': 'fail', 'reason': str(error)}
    result['status'] = 'fail' if (result['technical_seo']['status'] == 'fail' or result['search']['status'] == 'fail' or any(d['missing_dependencies'] for d in result['reader_delivery'])) else 'pass'
    if result['status'] == 'pass' and result['search']['status'] == 'unsupported':
        result['status'] = 'partial'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    spec = json.loads(args.manifest.read_text())
    report = {'schema': 1, 'contract': 'benchmarks/SPEC.md', 'python': platform.python_version(),
              'manifest_sha256': hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
              'performance_report': spec.get('performance_report'), 'cases': []}
    if report['performance_report']:
        report['performance_report_sha256'] = hashlib.sha256(Path(report['performance_report']).read_bytes()).hexdigest()
    for case in spec['cases']:
        try:
            report['cases'].append(inspect_case(case))
        except (OSError, ValueError) as error:
            report['cases'].append({'label': case['label'], 'status': 'fail', 'reason': str(error)})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    return 1 if any(c['status'] == 'fail' for c in report['cases']) else 0


if __name__ == '__main__':
    sys.exit(main())
