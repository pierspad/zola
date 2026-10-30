#!/usr/bin/env python3
"""Deterministic end-to-end release regression and timing checks (stdlib only)."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
from fixtures import generate, mutate, MUTATIONS, WORKLOAD
import statistics
import subprocess
import sys
import tempfile
import time

SCHEMA = 1
BENCHMARKS = Path(__file__).resolve().parent
WORK = BENCHMARKS / "work"


def manifest(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def assert_coverage(public, pages):
    required = ("journal.css", "assets/main.css", "assets/main.js", "atom.xml", "rss.xml",
                "sitemap.xml", "search_index.en.json", "articles/page/2/index.html",
                "tags/shared/page/2/index.html", "categories/engineering/page/2/index.html",
                "articles/page-00000/source.webp", "articles/page-00000/caption.txt")
    for name in required:
        if not (public / name).is_file():
            raise ValueError(f"missing workload coverage output: {name}")
    html = (public / "articles/page-00000/index.html").read_text()
    for marker in ("<table", "<blockquote", "<pre", "processed_images/", "Dependency-aware annotation", 'width=', 'height='):
        if marker not in html:
            raise ValueError(f"missing rendered rich-content marker: {marker}")
    css = (public / "journal.css").read_text()
    if "$ink" in css or "#243746" not in css:
        raise ValueError("Sass compilation did not resolve the palette")
    search = json.loads((public / "search_index.en.json").read_text())
    if len(search) != pages + 2:
        raise ValueError(f"search index contains {len(search)} records instead of {pages + 2}")
    article = next(item for item in search if item["url"].endswith("/articles/page-00000/"))
    if not article.get("date") or not article.get("headings") or not article.get("taxonomies"):
        raise ValueError("search is missing requested dates/headings/taxonomies")
    variants = list((public / "processed_images").glob("*.webp"))
    if len(variants) != 6:
        raise ValueError(f"expected six real resize variants, found {len(variants)}")
    return {"page_count": pages, "search_records": len(search), "resize_variants": len(variants),
            "sass": True, "section_and_taxonomy_pagination": True, "feeds": True,
            "bundled_media": True, "shortcodes": True, "rich_markdown": True}


def command(args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()


def cache_hits(output):
    match = re.search(r"Incremental cache: reused (\d+) Markdown renders and (\d+) page HTML renders", output)
    return {"markdown": int(match[1]), "page_html": int(match[2])} if match else None


def build(binary, root, env, extra=()):
    start = time.perf_counter()
    result = subprocess.run([str(binary), "--root", str(root), "build", *extra],
                            env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode:
        raise ValueError(f"build failed ({result.returncode}):\n{result.stdout}")
    build.last_output = result.stdout
    return time.perf_counter() - start


def check_mutations(binary, root, pages, env, extra, add_runs, artifacts):
    artifacts.mkdir(parents=True, exist_ok=True)
    results = []
    if extra:
        build(binary, root, env, extra)  # Cache is created only by opt-in candidate builds.
    for scenario in MUTATIONS:
        mutate(root, scenario, pages)
        candidate_seconds = build(binary, root, env, extra)
        candidate_cache_hits = cache_hits(build.last_output)
        candidate = manifest(root / "public")
        with tempfile.TemporaryDirectory(prefix="oracle-", dir=WORK) as temp:
            oracle = Path(temp) / "site"
            shutil.copytree(root, oracle, ignore=shutil.ignore_patterns("public", "processed_images", ".zola*"))
            oracle_seconds = build(binary, oracle, env)
            expected = manifest(oracle / "public")
        evidence = artifacts / f"{scenario}.json"
        evidence.write_text(json.dumps({"scenario": scenario, "equal": candidate == expected,
                                       "oracle_manifest": expected,
                                       "candidate_manifest": candidate if candidate != expected else None},
                                      indent=2, sort_keys=True) + "\n")
        if candidate != expected:
            changed = sorted(k for k in candidate.keys() | expected.keys() if candidate.get(k) != expected.get(k))
            raise ValueError(f"{scenario}: changed-tree output differs from fresh full build: {changed[:12]}")
        add_samples = []
        full_add_samples = []
        if scenario == "add":
            add_samples.append(candidate_seconds)
            full_add_samples.append(build(binary, root, env))
            for _ in range(add_runs - 1):
                (root / "content/articles/added.md").unlink()
                build(binary, root, env, extra)  # Restore/prime the pre-add state, outside timing.
                mutate(root, "add", pages)
                add_samples.append(build(binary, root, env, extra))
                if manifest(root / "public") != expected:
                    raise ValueError("repeated add differs from fresh full-build oracle")
                full_add_samples.append(build(binary, root, env))
        results.append({"scenario": scenario, "candidate_seconds": candidate_seconds,
                        "oracle_seconds": oracle_seconds, "files": len(candidate), "equal": True,
                        "cache_hits": candidate_cache_hits,
                        "manifest_artifact": str(evidence.resolve()), "add_samples_seconds": add_samples, "add_full_samples_seconds": full_add_samples})
        print(f"mutation {scenario}: oracle matches ({candidate_seconds:.3f}s / {oracle_seconds:.3f}s full)", file=sys.stderr)
    return results


def run(args):
    binary = args.binary.resolve()
    if not binary.is_file():
        raise ValueError(f"binary does not exist: {binary}")
    baseline = json.loads(args.baseline.read_text()) if args.baseline else None
    pages = 100 if args.size == "quick" else 10000
    context = {"schema": SCHEMA, "workload": WORKLOAD, "pages": pages,
               "threads": args.threads, "platform": platform.platform(), "machine": platform.machine()}
    if baseline and any(baseline.get(k) != v for k, v in context.items()):
        raise ValueError("baseline schema/workload/pages/threads/platform/machine differs; use matching settings and host")
    if baseline:
        median = baseline.get("median_seconds")
        if not isinstance(median, (int, float)) or not math.isfinite(median) or median <= 0:
            raise ValueError("baseline median_seconds must be finite and positive")
        if baseline.get("failures"):
            raise ValueError("baseline contains failed checks")
    samples = []
    warmup_samples = []
    timed_cache_hits = []
    expected = None
    WORK.mkdir(parents=True, exist_ok=True)
    mutation_results = []
    with tempfile.TemporaryDirectory(prefix="release-", dir=WORK) as temp:
        root = Path(temp)
        generate(root, pages)
        source_files = [p for p in root.rglob("*") if p.is_file()]
        source_stats = {"files": len(source_files), "bytes": sum(p.stat().st_size for p in source_files),
                        "markdown_files": sum(p.suffix == ".md" for p in source_files)}
        fixture_hash = hashlib.sha256(json.dumps(manifest(root), sort_keys=True).encode()).hexdigest()
        if baseline and baseline.get("fixture_sha256") != fixture_hash:
            raise ValueError("baseline fixture fingerprint differs")
        env = dict(os.environ, RAYON_NUM_THREADS=str(args.threads))
        env.setdefault("RUST_LOG", "site=info,zola=info")
        for i in range(args.warmups + args.runs):
            start = time.perf_counter()
            result = subprocess.run([str(binary), "--root", str(root), "build", *args.build_arg],
                                    env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            elapsed = time.perf_counter() - start
            if result.returncode:
                raise ValueError(f"build failed ({result.returncode}):\n{result.stdout}")
            output = manifest(root / "public")
            coverage = assert_coverage(root / "public", pages)
            if not output or len([p for p in output if p.startswith("articles/page-") and p.endswith("/index.html")]) != pages:
                raise ValueError("build did not render the expected number of pages")
            if expected is not None and output != expected:
                raise ValueError("output changed between identical builds")
            expected = output
            if i >= args.warmups:
                samples.append(elapsed)
                timed_cache_hits.append(cache_hits(result.stdout))
            else:
                warmup_samples.append(elapsed)
            print(f"{'warmup' if i < args.warmups else 'sample'} {i + 1}: {elapsed:.3f}s", file=sys.stderr)
        persistent_cache_bytes = sum(p.stat().st_size for p in (root / ".zola-cache").rglob("*") if p.is_file())
        if args.mutations:
            mutation_results = check_mutations(binary, root, pages, env, args.mutation_build_arg, args.add_runs,
                                               args.output.parent / (args.output.stem + "-mutations"))
    median = statistics.median(samples)
    report = dict(context, fixture_sha256=fixture_hash, binary=str(binary),
                  binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                  version=command([str(binary), "--version"]), samples_seconds=samples,
                  warmup_samples_seconds=warmup_samples, minimum_seconds=min(samples), maximum_seconds=max(samples),
                  median_absolute_deviation_seconds=statistics.median(abs(x - median) for x in samples),
                  median_seconds=median, output_manifest=expected, warmups=args.warmups,
                  mutations=mutation_results, coverage=coverage, source_stats=source_stats,
                  persistent_cache_bytes=persistent_cache_bytes, cache_hits=timed_cache_hits,
                  logging_filter=env.get("RUST_LOG"), build_args=args.build_arg, mutation_build_args=args.mutation_build_arg, cache_policy="fresh processes; retained image and OS caches")
    try:
        report["revision"] = command(["git", "rev-parse", "HEAD"], Path(__file__).resolve().parent.parent)
        report["checkout_dirty"] = bool(command(["git", "status", "--porcelain"], Path(__file__).resolve().parent.parent))
        report["rustc"] = command(["rustc", "--version"])
    except (OSError, subprocess.CalledProcessError):
        pass
    failures = []
    if baseline:
        if baseline["output_manifest"] != expected and not args.allow_output_changes:
            failures.append("output differs from baseline (inspect intentional release changes before replacing baseline)")
        delta = median - baseline["median_seconds"]
        regression = delta / baseline["median_seconds"]
        report["comparison"] = {"relative_change": regression, "seconds_change": delta,
                                "threshold_fraction": args.threshold, "minimum_seconds": args.minimum_seconds}
        if regression > args.threshold and delta > args.minimum_seconds:
            message = f"timing regression: {regression:.1%} (+{delta:.3f}s)"
            print(message, file=sys.stderr)
            if args.fail_on_regression:
                failures.append(message)
    report["failures"] = failures
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"median: {median:.3f}s; report: {args.output}", file=sys.stderr)
    for failure in failures:
        print(failure, file=sys.stderr)
    return bool(failures)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-arg", action="append", default=[], help="extra build argument for timed builds, e.g. --build-arg=--incremental")
    parser.add_argument("--add-runs", type=int, default=3, help="repeated add/full-build timings in mutation mode")
    parser.add_argument("--mutations", action="store_true", help="check changed sources against fresh full-build output")
    parser.add_argument("--mutation-build-arg", action="append", default=[],
                        help="additional candidate build argument for mutation checks only (e.g. --mutation-build-arg=--incremental)")
    parser.add_argument("--binary", type=Path, default=Path("target/release/zola"))
    parser.add_argument("--size", choices=("quick", "10k"), default="quick")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--threshold", type=float, default=0.15)
    parser.add_argument("--minimum-seconds", type=float, default=0.1)
    parser.add_argument("--fail-on-regression", action="store_true")
    parser.add_argument("--allow-output-changes", action="store_true",
                        help="allow intentional cross-version output changes; repeatability still required")
    args = parser.parse_args()
    if args.add_runs < 1 or args.runs < 1 or args.warmups < 0 or args.threads < 1 or args.threshold < 0 or args.minimum_seconds < 0 or not math.isfinite(args.threshold) or not math.isfinite(args.minimum_seconds):
        parser.error("runs/add-runs/threads must be positive; warmups and finite thresholds must be nonnegative")
    try:
        return run(args)
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        print(f"release suite: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
