#!/usr/bin/env python3
"""Refresh an isolated, unmodified official Zola checkout and build its baseline."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
CHECKOUT = ROOT / 'work' / 'upstream'
TARGET = ROOT / 'work' / 'upstream-target'
URL = 'https://github.com/getzola/zola.git'
# Public read-only fetches must not inherit user Git URL rewrites.
NETWORK_ENV = {**os.environ, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}


def run(*args, cwd=CHECKOUT):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def ensure_upstream(build=True, offline=False):
    CHECKOUT.parent.mkdir(parents=True, exist_ok=True)
    if not CHECKOUT.exists():
        if offline:
            raise RuntimeError('No baseline checkout exists for offline use')
        subprocess.run(['git', 'clone', '--origin', 'upstream', URL, str(CHECKOUT)], env=NETWORK_ENV, check=True)
    if run('git', 'config', '--get', 'remote.upstream.url') != URL:
        raise RuntimeError('Baseline checkout has an unexpected upstream remote')
    subprocess.run(['git', 'config', 'remote.upstream.pushurl', 'no_push://disabled'], cwd=CHECKOUT, check=True)
    if run('git', 'status', '--porcelain'):
        raise RuntimeError('Baseline checkout is dirty; refusing to overwrite it')
    if not offline:
        subprocess.run(['git', 'fetch', 'upstream', 'HEAD', '--tags'], cwd=CHECKOUT, env=NETWORK_ENV, check=True)
        commit = run('git', 'rev-parse', 'FETCH_HEAD')
        subprocess.run(['git', 'checkout', '--detach', commit], cwd=CHECKOUT, check=True)
    commit = run('git', 'rev-parse', 'HEAD')
    binary = TARGET / 'release' / 'zola'
    metadata = {'stale': offline, 'source': URL, 'commit': commit, 'description': run('git', 'log', '-1', '--format=%cI %s'),
                'toolchain': run('rustc', '-Vv'), 'cargo': run('cargo', '-V'),
                'features': 'default', 'profile': 'release (upstream Cargo.toml)', 'latest_stable': run('git', 'describe', '--tags', '--abbrev=0'), 'binary': str(binary),
                'checkout': str(CHECKOUT), 'lock_sha256': hashlib.sha256((CHECKOUT / 'Cargo.lock').read_bytes()).hexdigest()}
    if build:
        subprocess.run(['cargo', 'build', '--release', '--locked'], cwd=CHECKOUT,
                       env={**os.environ, 'CARGO_TARGET_DIR': str(TARGET)}, check=True)
        metadata['binary_sha256'] = hashlib.sha256(binary.read_bytes()).hexdigest()
        metadata['version'] = run(str(binary), '--version')
        (TARGET / 'baseline.json').write_text(json.dumps(metadata, indent=2) + '\n')
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sync-only', '--sync', action='store_true')
    parser.add_argument('--offline', action='store_true', help='Explicitly use existing checkout without fetching (marked stale)')
    args = parser.parse_args()
    print(json.dumps(ensure_upstream(not args.sync_only, offline=args.offline), indent=2))
