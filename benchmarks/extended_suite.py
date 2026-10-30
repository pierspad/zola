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
    parser.add_argument('--cases', help='Defaults to common matrix or tiny cells with --quick')
    parser.add_argument('--quick', action='store_true', help='Correctness-only 8x1/24x2, newspaper, one sample/no warmup')
    parser.add_argument('--fork-build-metadata', type=Path, help='Explicit frozen binary attestation avoids rebuilding Cargo')
    parser.add_argument('--personal-root', type=Path, help='Actual personal frontend checkout; absent means unsupported search')
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
        cases = selected_cases(args.cases or ('8x1,24x2' if args.quick else COMMON), args.long)
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
    if args.fork_build_metadata:
        command += ['--fork-build-metadata', str(args.fork_build_metadata)]
    if args.quick:
        command += ['--profiles', 'newspaper', '--small-runs', '1', '--large-runs', '1', '--warmups', '0']
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
        if process.returncode == 0:
            measured = json.loads(matrix_output.read_text())
            report['quality_statuses'] = [case.get('quality_status', 'unsupported: quality not requested') for case in measured.get('cases', [])]
            report['personal_search'] = {'status': 'unsupported', 'reason': '--personal-root not supplied; synthetic Fuse frontend unavailable'}
            if args.personal_root:
                search_output = args.output.with_name(args.output.stem + '-personal-search.json')
                search_work = args.output.with_name(args.output.stem + '-personal-search-work-' + str(time.time_ns()))
                search_command = [sys.executable, str(Path(__file__).with_name('personal_search_suite.py')), '--personal-root', str(args.personal_root), '--pages', '100' if args.quick else '10000', '--work', str(search_work), '--output', str(search_output)]
                with log_path.open('a') as log:
                    search_process = subprocess.run(search_command, stdout=log, stderr=subprocess.STDOUT)
                report['personal_search'] = {'status': 'pass' if search_process.returncode == 0 else 'fail', 'report': str(search_output), 'command': search_command}
            if 'fail' in report['quality_statuses'] or report['personal_search']['status'] == 'fail':
                report['status'] = 'failed_quality'
            elif any(status != 'pass' for status in report['quality_statuses']) or report['personal_search']['status'] != 'pass':
                report['status'] = 'partial'
        # This duration includes preparation, fixture generation and quality work;
        # only matrix samples are engine-generation performance measurements.
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    return 1 if report['status'] in ('failed', 'failed_quality') else 0


if __name__ == '__main__':
    sys.exit(main())
