#!/usr/bin/env python3
"""Build the local fork before timing, or verify explicit prebuilt provenance."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def verify_metadata(binary, metadata):
    required = ('binary_sha256', 'toolchain', 'features', 'profile', 'lock_sha256')
    if any(not metadata.get(key) for key in required):
        raise ValueError('Fork build metadata is incomplete')
    if metadata['binary_sha256'] != sha(binary):
        raise ValueError('Fork build metadata executable SHA-256 does not match --binary')
    return metadata


def prepare_fork(binary, metadata_path=None, profile='release'):
    binary = Path(binary).resolve()
    if metadata_path:
        return verify_metadata(binary, json.loads(Path(metadata_path).read_text()))
    expected = ROOT/'target'/('release' if profile == 'release' else 'debug')/'zola'
    if binary != expected:
        raise ValueError('Custom prebuilt binary requires --fork-build-metadata')
    # Explicit target dir prevents a caller CARGO_TARGET_DIR from attesting another executable.
    env = {**os.environ, 'CARGO_TARGET_DIR': str(ROOT/'target')}
    args = ['cargo', 'build', '--locked'] + (['--release'] if profile == 'release' else [])
    subprocess.run(args, cwd=ROOT, env=env, check=True)
    paths = subprocess.check_output(['git', 'ls-files', '-co', '--exclude-standard', '-z'], cwd=ROOT).split(b'\0')
    source = hashlib.sha256()
    for name in sorted(set(paths)):
        path = ROOT/os.fsdecode(name)
        if name and path.is_file():
            source.update(name+b'\0'+bytes.fromhex(sha(path)))
    metadata = {'binary':str(binary), 'binary_sha256':sha(binary), 'commit':command('git','rev-parse','HEAD'),
                'dirty':bool(command('git','status','--porcelain')), 'source_sha256':source.hexdigest(),
                'source_fingerprint_policy':'Git tracked and nonignored untracked files, paths and file SHA-256',
                'toolchain':command(os.environ.get('RUSTC','rustc'),'-Vv'), 'cargo':command('cargo','-V'), 'features':'default',
                'profile':'release (lto=true, codegen-units=1, strip=true)' if profile == 'release' else 'dev (Cargo.toml)',
                'lock_sha256':sha(ROOT/'Cargo.lock'), 'version':command(str(binary),'--version'),
                'build_command':args, 'build_environment':{key:value for key,value in sorted(env.items()) if key.startswith('CARGO_PROFILE_') or key in ('CARGO_TARGET_DIR','CARGO_BUILD_TARGET','CARGO_BUILD_RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS','RUSTFLAGS','RUSTDOCFLAGS','RUSTUP_TOOLCHAIN','RUSTC','RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','CC','CXX','AR')}}
    return verify_metadata(binary, metadata)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=('release','dev'), default='release')
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    binary=ROOT/'target'/('release' if args.profile=='release' else 'debug')/'zola'
    metadata=prepare_fork(binary,profile=args.profile)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(metadata,indent=2)+'\n')
