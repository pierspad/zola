#!/usr/bin/env python3
"""Resource-preflight orchestration. Engine measurements remain owned by matrix.py."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from matrix import memory_headroom

COMMON = '100x1,1000x1,10000x1,1000x15,25000x1'


def selected_cases(text, allow_long):
    cases = []
    for cell in text.split(','):
        try:
            articles, languages = map(int, cell.split('x'))
        except ValueError:
            raise ValueError('cases must use articles x locales, e.g. 1000x15')
        if articles < 8 or not 1 <= languages <= 15:
            raise ValueError('articles >=8 and locales 1..15 required')
        if articles * languages >= 50000 and not allow_long:
            raise ValueError('>=50000 pages requires explicit --long opt-in')
        cases.append(cell)
    return ','.join(cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=Path('target/release/zola'))
    parser.add_argument('--cases', default=COMMON)
    parser.add_argument('--long', action='store_true', help='Explicitly permit 50000/100000-page capacity cells')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rss-gib', type=float, default=3)
    parser.add_argument('--reserve-gib', type=float, default=8)
    parser.add_argument('--disk-gib', type=float, default=8)
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--quality', action='store_true', help='Requires matrix quality hook; otherwise matrix rejects it explicitly')
    args = parser.parse_args()
    try:
        cases = selected_cases(args.cases, args.long)
    except ValueError as error:
        parser.error(str(error))
    if min(args.rss_gib, args.reserve_gib, args.disk_gib, args.timeout) <= 0:
        parser.error('resource guards must be positive')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {'schema': 1, 'measurement_contract': 'benchmarks/SPEC.md', 'cases': cases,
              'long_opt_in': args.long, 'preflight': memory_headroom(),
              'free_disk_bytes': shutil.disk_usage(args.output.parent).free,
              'status': 'prepared'}
    matrix_output = args.output.with_name(args.output.stem + '-matrix.json')
    command = [sys.executable, str(Path(__file__).with_name('matrix.py')), '--binary', str(args.binary),
               '--cases', cases, '--output', str(matrix_output), '--rss-gib', str(args.rss_gib),
               '--reserve-gib', str(args.reserve_gib), '--disk-gib', str(args.disk_gib), '--timeout', str(args.timeout)]
    if args.offline:
        command.append('--offline')
    if args.quality:
        command.append('--quality')
    report['command'] = command
    report['matrix_report'] = str(matrix_output)
    if report['free_disk_bytes'] < args.reserve_gib * 1024**3:
        report.update(status='skipped_resource_preflight', reason='free disk below reserve')
    elif report['preflight']['effective_available_bytes'] < args.rss_gib * 1024**3:
        report.update(status='skipped_resource_preflight', reason='available RAM below requested engine RSS guard')
    elif args.dry_run:
        report['status'] = 'dry_run_no_measurements'
    else:
        log_path = args.output.with_suffix('.log')
        report['raw_log'] = str(log_path)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
        start = time.monotonic()
        with log_path.open('w') as log:
            process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        report.update(status='completed' if process.returncode == 0 else 'failed', returncode=process.returncode,
                      orchestration_elapsed_seconds=time.monotonic()-start)
        # This duration includes preparation, fixture generation and quality work;
        # only matrix samples are engine-generation performance measurements.
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    return 1 if report['status'] == 'failed' else 0


if __name__ == '__main__':
    sys.exit(main())
