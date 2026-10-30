# Benchmark measurement contract

This contract precedes further engine optimization. Results compare the pinned official
upstream, fork full builds, and fork incremental builds on identical generated inputs.
Correctness and quality gates are reported independently from speed; a ratio is not a
claim that every dimension improved.

## Process and reproducibility

Each timed sample is a fresh one-shot engine process. Incremental refers to reuse of
Zola's content cache, never Cargo incremental compilation. Warm fixture/cache runs do
not establish cold operating-system caches. Preserve commands, environment, fixture
hashes, revisions, binary SHA-256, toolchain, hardware, resource limits, raw logs and
all samples. Report wall and child CPU seconds, peak engine RSS in bytes, medians and
median absolute deviation; do not attribute the Python parent RSS to the engine.
Aborted runs retain their status and evidence and are not successful samples.

Binary size is physical file bytes (also KiB = bytes / 1024), labeled by actual build
profile and stripping state. Never infer stripped size. Compilation time is separate
from site generation and is reported only when measured, with Cargo cache state;
an already cached build is not a cold compilation measurement. There is no WASM
result unless an actual WASM artifact was built and measured.

Use common-search-v2 fixtures and pinned official upstream. Multilingual fixture
version 2 / base workload 3 adds SEO metadata to the shared templates; older
fixture measurements are not a comparable performance baseline. Existing narrow, exact
image-attribute and fixture asset-minification differences may be classified; every
unknown output difference fails equivalence. Earlier performance samples cannot be
relabelled as newly measured quality results without matching fixture provenance.

## Technical SEO and correctness

Inspect generated HTML for canonical URL uniqueness, document language/direction,
metadata, broken local links and duplicate IDs. Validate hreflang targets and reciprocal
membership, including the fixture's native self link across 15 languages. Validate
robots and sitemap references, sitemap XML and local targets. A sitemap URL set must
contain at most 50,000 URLs and its uncompressed XML must not exceed 50 MiB
(52,428,800 bytes). Exercise oversized boundaries with synthetic unit fixtures;
large engine fixtures are optional guarded runs. Current fixtures chunk at 30,000 URLs.
Parse JSON-LD when present; its absence is not invented structured data or a ranking
failure. No synthetic SEO score or ranking prediction is permitted.

## Search

Quality assertions use deterministic expected result membership and ranking for Latin,
accents, CJK and RTL queries against actual generated indexes and the frontend shipped
by the selected profile. Generic Fuse indexes and the personal site's custom search
are distinct systems. Do not apply unsupported stemming expectations to another
locale or claim an index-only inspection executes the frontend. Missing runtime,
frontend adapters or locale capability must be explicit unsupported/skipped evidence.

Measure warmed query latency median and p95 with the runtime/version, iterations,
process RSS and query set recorded. Node timings are not browser interaction latency
or LCP. Browser request/transfer measurements are optional only with an available
browser runtime and local HTTP server; no large dependency installation is required.

## Reader delivery

For representative pages follow actual local HTML dependencies, scripts, stylesheets,
CSS url()/imports, images and fonts. Record potential request count, raw bytes and
actual gzip bytes; record Brotli bytes/version only when an encoder is available.
Record missing and external dependencies and cycle handling. State cold-visit and
shared-resource cache assumptions. Total site disk size is never single-page download
cost. Static encoded-byte estimates are not browser network transfers; local HTTP
measurements are not real Internet performance. Do not fabricate Lighthouse results.

## Suite sizes and resource guards

The common matrix covers 100, 1,000, 10,000, multilingual 15,000 (1,000 × 15), and
25,000 pages. 50,000/100,000-page runs require explicit long-run opt-in. Preserve
upstream comparisons and baseline history. Reuse existing matrix output rather than
unnecessarily repeating its 135 samples. A short verification suite exercises metric
logic and small generated output. Long orchestration checks available RAM/cgroup
headroom, free disk, timeout and maximum RSS before and during engine work. Skips,
quality failures and resource aborts remain visible, with raw logs; never silently
shrink a fixture and retain its original label.

The automatic build wrapper always selects Zola content incremental mode. Its memory
budget policy is min(host total / 4, host available / 2, finite cgroup headroom / 2)
in MiB, with source evidence logged, explicit overrides, and a documented fallback.
A cache accounting budget is not a hard process RSS ceiling. A cost of at most one
second is acceptable; no elapsed-time heuristic changes the policy. This describes
content caching, not Rust/Cargo compilation.

## Acceptance

A report is complete when provenance and statuses are explicit, official/full/incremental
results are comparable, all unknown correctness differences fail, unit boundary tests
pass, and unsupported measurements are identified. Performance regressions remain
reported. No further engine optimization is justified by an incomplete measurement.
