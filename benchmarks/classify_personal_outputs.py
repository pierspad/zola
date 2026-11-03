#!/usr/bin/env python3
"""Prove localized asset deduplication by exact bytes; preserve all other deltas."""
import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path


def classify(official, fork, changed, minifier=None):
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
    remaining = []
    for name in unknown:
        before, after = official / name, fork / name
        if name.endswith(('.html', '.xml')) and before.is_file() and after.is_file():
            original = before.read_text()
            normalized = original
            used = []
            for asset, old_hash, new_hash in hash_pairs:
                pattern = r'(?<=/)' + re.escape(asset) + r'\?h=' + old_hash + r'(?![0-9a-f])'
                normalized, count = re.subn(pattern, asset + '?h=' + new_hash, normalized)
                if count:
                    used.append(asset)
            if used and normalized == after.read_text():
                proofs[name] = {'classification': 'verified_minified_asset_hash_urls_only',
                                'verified_assets': used}
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
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    result = classify(args.official, args.fork, report['changed_paths'], args.minifier)
    result['source_report'] = str(args.report)
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
