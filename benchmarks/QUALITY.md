# Extended quality and delivery suite

Read [SPEC.md](SPEC.md) before interpreting results. Existing `matrix.py` remains
responsible for official/full/incremental performance and resource guards. The
quality sidecar inspects retained output trees without repeating timed builds:

```sh
python3 -m unittest discover -s benchmarks -p 'test_quality_metrics.py'
python3 benchmarks/quality_suite.py --manifest benchmarks/results/quality-input.json --output benchmarks/results/quality.json
```

A manifest uses absolute paths (relative paths resolve against the current directory):

```json
{
  "performance_report": "/absolute/path/matrix.json",
  "cases": [
    {
      "label": "official-100-newspaper",
      "output_root": "/absolute/path/official/public",
      "base_url": "https://fixture.example/",
      "binary": "/absolute/path/official/zola",
      "pages": ["index.html", "journal/article-00000/index.html"]
    }
  ]
}
```

Provide one entry per retained official, fork-full, and fork-incremental tree and
size/profile. The matrix may overwrite a tree between builds: retain/copy snapshots
before inspection when distinct variants are required. A sidecar hash proves its
own inspected tree, not that it matches a historical performance sample; compare
its manifest with performance provenance before joining results. Missing output
roots and dependencies fail. Metadata, absent robots/sitemap and absent JSON-LD
are explicit findings rather than fabricated ranking scores. Hreflang checks
require reciprocal and self membership and equal alternate sets. Canonical
uniqueness checks can flag intentionally canonicalized aliases for human review.

Reader metrics recursively inspect HTML resource attributes and CSS url()/imports,
deduplicate local files and follow cycles safely. Counts include all srcset
alternatives and therefore describe potential dependencies, not a browser's chosen
viewport. Dynamic JS fetches/imports, inline CSS and external dependency sizes are
not measured. Gzip uses a deterministic actual encoder per file, even for images;
real servers may avoid image compression. Brotli is actually encoded at quality 5 when the optional installed Python encoder
is available; its version and byte counts are recorded. Missing encoders remain
unsupported. HTTP/browser transfers are not measured.

## Actual frontend search adapter

Synthetic Fuse fixtures currently generate an index without shipping a complete
search frontend. They receive `search.status=unsupported` and overall `partial`;
this is not a successful search quality gate. To run an actual frontend, supply
`search_spec` pointing to a JSON specification:

```json
{
  "adapter": "/absolute/path/frontend-adapter.mjs",
  "source_files": ["/absolute/path/shipped/search.js", "/absolute/path/public/search_index.en.json"],
  "queries": [
    {"text": "known phrase", "expected": ["https://fixture.example/known/"], "ranked_prefix": ["https://fixture.example/known/"]}
  ]
}
```

The adapter exports async `setup(specification)` returning an async search function
that returns ranked URL strings. It must load/execute the shipped search code and
actual generated index, including its actual options and locale behavior. It must
not reimplement matching just to satisfy expected answers. Include all executed
sources in `source_files`; their SHA-256 hashes and the adapter hash are retained.
`allow_extra: true` permits extra results only for explicitly recall-only queries.
Default assertions reject both missing and unexpected hits. Include positive,
negative, accent, CJK and RTL cases appropriate to the frontend's actual capability.

The probe reports 20 warmups and 100 measured queries, all raw times, median/p95,
Node version and process peak RSS. Adapter setup/index loading is outside query
timing. This is not browser latency, network cost or Lighthouse/LCP. A supplied
adapter is executable local code and should be reviewed like the benchmark itself.

## Personal frontend operational check

```sh
python3 benchmarks/personal_search_suite.py --personal-root .. --pages 100 --work benchmarks/work/personal-search-100 --output benchmarks/results/personal-search-100.json
python3 -m unittest discover -s benchmarks -p 'test_personal_search.py'
```

Use a new work directory each time. `--personal-root` explicitly identifies the
checkout containing the real frontend and generator. A standalone Zola checkout
does not contain these personal-site sources: its integration test explicitly
skips, and the extended driver records unsupported search unless a root is supplied. This imports the actual personal site's
`prepush-scripts/02-generate-search-dicts.py` against isolated Markdown fixtures and
executes shipped `static/search.js` inside Node VM. A minimal DOM and fetch stub
supply the generated dictionary; the adapter exports the real closure's search
function through one checked instrumentation anchor. It does not copy the algorithm.
Repeat-query suppression is reset so every sample executes scoring and rendering;
120ms event debounce is excluded. Latin ranking, accent folding, CJK and RTL text,
no-hit and all-token requirements use six deterministic oracles. The generator
supports it/en dictionaries, so Unicode content is tested in the supported Italian
dictionary; this makes no claim about additional locale stemming. Dictionary bytes
at search activation are separate from initial-page dependency bytes, with actual
gzip/Brotli encoding and versions when available. Peak RSS covers the whole Node
process, not an isolated search allocation.

## Long runs

```sh
python3 benchmarks/extended_suite.py --output benchmarks/results/extended.json --quality --personal-root ..
python3 benchmarks/extended_suite.py --long --cases 50000x1,100000x1 --timeout 600 --output benchmarks/results/capacity.json --quality --personal-root ..
```

For a correctness-only end-to-end check with the existing frozen executable:

```sh
python3 benchmarks/extended_suite.py --quick --quality --personal-root .. --binary target/release/zola --fork-build-metadata benchmarks/results/fork-build-memory-final.json --output benchmarks/results/extended-quick-e2e.json
```

`--quick` selects 8x1 and 24x2 newspaper cells, one sample, no warmups. These are
correctness checks, not release timing baselines. The explicit attestation prevents
rebuilding the fork. The actual personal search uses 100 documents for quick checks
and 10,000 otherwise; its scope remains separate from the synthetic Fuse index.
Missing adapters produce `partial`, and detected quality failures produce
`failed_quality` with a nonzero exit status even when engine correctness passes.
Version 3 multilingual fixtures (base workload 4) provide canonical, language,
direction and description metadata, including a 404 and pagination redirect
template. Redirect canonicals match the real listing refresh destination. The quality
checker exempts canonical reuse only after validating one immediate local
refresh to an existing, non-redirect, self-canonical destination. This workload has no arbitrary
content aliases. Older fixture performance and SEO reports remain historical and
are not comparable to this revised template workload. Search still remains
unsupported for synthetic fixtures. Review per-case findings without treating
them as a ranking score.

The extended driver uses the existing matrix rather than duplicating engine timing
logic. It records preflight evidence, skips insufficient RAM/disk explicitly, saves
all child output in an adjacent raw log and preserves the matrix JSON. Its elapsed
time includes compilation/fixtures/quality and must not be used as engine timing.
`--dry-run` prepares and records the exact command without executing measurements.
The `--quality` option requires the matrix quality hook; an absent hook causes an
explicit argument error rather than silently omitting quality. Capacity cells with
at least 50,000 pages require `--long`. The standard driver covers all common sizes
including 25,000; it never silently reduces them.


Run common size profiles through the existing guarded matrix and retain its raw
JSON/logs. For a deliberately long capacity run, explicitly include 50000x1 or
100000x1 in `--cases`, increase `--timeout` only after assessing RAM/disk, and retain
`--rss-gib`, `--reserve-gib` and `--disk-gib` guards. A resource skip establishes no
capacity claim. Do not run memory-intensive suites alongside engine measurements.
Long runs still compare pinned upstream and both fork modes; quality sidecars are
required for each retained output. Binary compilation remains separate and cached
Cargo timing must not be labeled cold compilation.

## Completed fixture-v3 baseline, 2026-11-02

The corrected full run completed with exit code 0: ten cells (stress and newspaper
at 100, 1,000, 10,000, 1,000 × 15 locales and 25,000 articles), 114 measured
engine samples, two warmups per mode, and no resource abort. Earlier references to
135 samples were an arithmetic error: four small cells × three modes × five
repeats plus six larger cells × three modes × three repeats equals 114.

All ten official/fork comparisons passed the narrow documented difference policy;
fork full/incremental outputs matched exactly. All twenty output inspections
(official and fork for each cell) passed technical SEO with zero errors, and all
56 representative delivery inspections had zero missing dependencies. The
multilingual cells inspected 18,316 HTML files per engine, validating 240 local
pagination redirects each. The 25,000-article cells inspected 30,022 HTML files
per engine. Quality remains **partial** because synthetic Fuse frontend search
has no verified adapter; it is not reported as passed.

The fresh mutation budget was explicitly 25,000 pages. All 22 selected scenarios
produced 44 byte-exact comparisons against fresh full-build oracles, with none
skipped. The four small cells exercise add/edit/delete/rename; the six larger
cells exercise deletion only. This budget does not establish broad mutation
coverage at 25,000 pages.

Newspaper wall medians in seconds and maximum observed engine RSS in MiB:

| Articles/locales | Official s / MiB | Fork full s / MiB | Fork incremental s / MiB |
| --- | ---: | ---: | ---: |
| 100 / 1 | 0.155 / 72.3 | 0.143 / 74.2 | 0.162 / 75.8 |
| 1,000 / 1 | 0.795 / 117.6 | 0.617 / 119.8 | 0.498 / 134.0 |
| 10,000 / 1 | 8.770 / 573.8 | 6.051 / 570.2 | 4.472 / 707.7 |
| 1,000 / 15 | 9.701 / 931.8 | 10.155 / 921.2 | 7.494 / 1,149.9 |
| 25,000 / 1 | 22.286 / 1,298.7 | 15.363 / 1,297.5 | 11.243 / 1,625.4 |

These are shared-host observations, with unrelated test workers and desktop
processes active. Performance attribution remains provisional; no whole-suite
rerun was performed. In particular, multilingual newspaper full builds were
about 4.7% slower than official upstream, and tiny incremental builds were slower
than full builds. Incremental memory was higher in every cell. The maximum timed
engine RSS across both profiles was 2,592,018,432 bytes (2,471.9 MiB), at 25,000
stress incremental, below the 3 GiB watchdog. Content-cache accounting budgets
are not hard process RSS limits. Raw MAD/ranges, CPU and cold-build metrics remain
in the matrix report; the Python orchestration's 2,809.8 seconds are not engine
time or cold compilation time.

The actual personal site's shipped search frontend passed all six deterministic
oracles over 10,000 generated entries in Node v26.12.1. Median query times were
10.76–11.70 ms and p95 11.67–12.84 ms; whole Node process peak RSS was
81,436,672 bytes. The activation dictionary was 1,957,788 raw / 87,122 gzip /
32,299 Brotli bytes. These are Node/runtime and static encoding measurements,
not browser UX, network transfer or LCP. No 50,000/100,000-page capacity claim is
made. All 29 benchmark unit/integration tests passed after the run.

The release executable was frozen from clean fork commit
`42a6586e2f65523f779d058fb96a78169f23d3ab`, using the recorded release profile
(LTO, one codegen unit, stripping). Fork binary SHA-256:
`d2a648f5baa237de26bfa5cf130cbc73ce550ad2390f99ff09f39b78cb082e75`.
Official upstream refreshed to `628926f8ea5d68d9430ee242289ce1a33794dbd2`,
with binary SHA-256
`d0bee1ddea6a4689cf5e0c1fda1860fd9429f99aec51309438d273abd2bc8ad8`.
Older fixture-v2 partial reports remain superseded and incomparable.

Locally retained evidence (ignored benchmark artifacts):

- `benchmarks/results/extended-baseline-fixture-v3.json` and adjacent `.log`
- `benchmarks/results/extended-baseline-fixture-v3-matrix.json` and `.md`
- `benchmarks/results/extended-baseline-fixture-v3-personal-search.json`
- `benchmarks/results/extended-baseline-fixture-v3-host-noise.json`
- `benchmarks/results/fork-build-fixture-v3.json`

## Fixture-only Fuse runtime extension, 2026-11-03

The historical baseline above remains partial. New evidence in
`benchmarks/results/fuse-standard-current-v1.json` executes actual upstream/fork-generated
indexes using pinned Fuse.js 7.1.0 (official source, SHA-256 and Apache license in
`benchmarks/vendor`). Zola explicitly provides no Fuse frontend; this is a
controlled fixture consumer, not validation of a shipped search UI. The actual
personal site's custom frontend remains a separate search system.

The deliberately minimal search corpus passed 100, 1,000, 10,000, 1,000 × 15
locales and 25,000 article cells in upstream full, fork full and fork incremental
modes. Every per-language index matched upstream exactly with the common enabled
schema (title/body, date disabled). The source-defined oracle checks all document
URLs/counts independently of the index and five queries: title-over-body ranking,
accent folding, CJK, RTL and no hits. Seven regression tests reject missing/wrong/
duplicate URLs, title-ranking corruption and lost Unicode content.

Fork-full Node query results (two warmups, twenty measurements per query):

| Articles/locales | Median range ms | p95 range ms | Peak Node RSS MiB |
| --- | ---: | ---: | ---: |
| 100 / 1 | 0.196–0.289 | 0.249–0.749 | 64.0 |
| 1,000 / 1 | 1.889–2.411 | 1.962–2.723 | 65.7 |
| 10,000 / 1 | 19.307–22.560 | 19.655–24.957 | 89.9 |
| 1,000 / 15 | 1.730–3.613 | 1.802–4.090 | 66.6 |
| 25,000 / 1 | 47.805–58.246 | 48.203–68.293 | 118.0 |

The 25,000-article activation index is 3,738,945 raw / 138,763 gzip /
56,203 Brotli bytes. In the 15-locale cell, one locale index ranges from
145,948–211,948 raw / 5,977–6,418 gzip / 2,365–2,981 Brotli bytes;
English is 147,945 / 5,978 / 2,373 bytes. All fifteen indexes together occupy
2,432,217 raw bytes; the complete minimal site occupies 6,042,433 raw bytes.
The 25,000-article minimal site occupies 9,404,665 raw bytes. These site totals
are disk sizes, not single-visit downloads. Query processes load one locale,
not all locale indexes. These are encoded-byte estimates and whole Node process
peak RSS, not observed browser transfers or browser heap. The pinned runtime is
a separate asset; Fuse uses no separate dictionary download in this fixture.
Build latency of this minimal corpus is intentionally not reported or comparable
to the rich stress/newspaper matrix.

The canonical matrix quality hook now tests its own version-3 rich corpus with
source-defined page/section membership, unique title, locale-script, accent-folded
English and no-hit oracles. It records `shipped_frontend_provided: false` and the
fixture scope. Reports without an adapter or known fixture descriptor continue
to report unsupported search and partial quality. Existing reports are unchanged.

The current extension uses the same `d2a648f5…` fork / `d0bee1dd…`
official binaries attested in the corrected baseline. An earlier minimal report
`fuse-standard-v1.json` used an older frozen binary (`8b31917d…`) and is preserved
as historical evidence, not the current-fork result.

The actual rich newspaper corpus was also executed: 1,000 articles in all fifteen
locales, including its long bodies, images, taxonomies, feeds and pagination.
All source-defined membership and 46 query oracles passed; every actual per-locale
index was byte-identical to official upstream. The retained engine verification
establishes full/incremental output identity, so equal indexes do not require
redundant runtime probing for every engine mode. Evidence:
`fuse-rich-current-1000x15-bounded-repeat.json`, alongside
`remaining-timing-1000x15.json`.

Rich indexes are 3,078,857–3,804,989 raw bytes per locale (English 3,130,801),
43,225–56,117 gzip bytes and 14,918–16,341 Brotli bytes. All fifteen indexes
occupy 48,886,281 raw bytes. A cold search loads one locale index, not all fifteen.
In the bounded repeat, five samples after two warmups gave query medians
49.428–75.120 ms, p95 50.630–173.658 ms and maximum fresh-broker Node RSS
106.9 MiB. These small-sample shared-desktop observations are not absolute browser
performance or browser-memory claims. The earlier twenty-sample rich report is
preserved and explicitly flagged for a twenty-five-second overlapping agent CPU
workload; the bounded repeat had no other agent workload, with ordinary background
processes still uncontrolled.

The unique title query stays below Fuse's 32-character Bitap chunk boundary.
Runtime validation caught that longer combined marker/title patterns could admit
all pages sharing one chunk even at threshold zero. Separate script-token and
accent-folded queries therefore check the complete source-defined membership;
no custom AND behavior is invented and attributed to Fuse.

## Completed remaining guarded runs (2026-11-03)

The frozen pre-fallback-fix fork (`d2a648f5…`) completed all ten mutation scenarios at
24 articles × 2 locales, 10,000 × 1 and 1,000 × 15. All 30 incremental outputs
matched an independently rebuilt fresh full oracle exactly; every scenario
changed at least one output path. Scenarios cover addition, translation edit,
metadata, deletion, rename, template, Sass, media, asset and language configuration.
Evidence: `remaining-mutations-{24x2,10000x1,1000x15}-final.json`.

Both larger newspaper capacity cells completed without a resource abort:

| Articles / locales | Official cold full s / GiB | Fork cold full s / GiB | Fork cold incremental population s / GiB |
|---|---:|---:|---:|
| 50,000 / 1 | 37.519 / 2.470 | 31.979 / 2.454 | 34.584 / 2.998 |
| 100,000 / 1 | 74.774 / 4.870 | 79.572 / 4.835 | 78.724 / 5.921 |

Each cell contains one population build per engine/mode. These are capacity
observations, not repeated timing comparisons or warm incremental measurements.
Whole-output fork full/incremental manifests were identical in both cells.
Official comparisons contained only the narrowly checked fixture image-dimension
and first-image loading changes (50,002 / 100,002 paths), with zero unknown paths.
The requested 8 GiB engine RSS budget was capped at 40% of available memory on
every build; effective limits at 100,000 were approximately 7.65–7.69 GB. Guards
also enforced 600 seconds, 20 GiB disk growth and a 12 GiB free-space reserve.
Evidence: `remaining-capacity-{50000x1,100000x1}-final.json`. RSS comes from the
fresh broker's inner engine wait4 result, excluding the Python coordinator.

The complete prepared personal-site comparison remains explicitly under review:
`remaining-personal-prepared.json` contains 312 official/fork changed paths.
Strict SHA-256 checks prove that 64 missing localized assets are deduplicated to
byte-identical assets at their unprefixed fork paths. The retained Rust minifier
helper proves exact transformation bytes for all 29 changed CSS/JS assets.
The remaining 219 paths
are not accepted by broad HTML or hash normalization; their diffs remain in the
retained work directory. `remaining-personal-strict-classification.json` records
these exact proofs and the outstanding paths. Fork full/incremental whole output
identity passed for both the original and compatible configurations. Upstream
rejects the original `infer_updated_from_git` setting; compatible comparisons
remove that setting from both engines and exclude inferred modification dates.


The retained 100,000-article cache also completed a warm no-op and a single
article addition (100,001 total), followed by an independent fresh full oracle.
The no-op preserved the baseline exactly; the addition changed 11,764 output
paths, included the new article, and matched the fresh oracle exactly. Both
incremental runs recorded 90,000 Markdown hits and zero page-HTML hits. Their
single observations were 65.267 / 65.245 seconds and 6.138 / 6.142 GiB peak RSS;
the fresh full oracle was 133.179 seconds and 4.832 GiB. These observations do
not establish a speed ranking. Evidence: `remaining-warm-100001-final.json`.
The frozen executable remains the pre-fallback-fix `d2a648f5…` binary.

The strict personal comparison above is a preserved pre-fix snapshot. Reviewing
its unclassified paths exposed custom `robots.txt` precedence and generated CSS
hash errors; those paths were not normalized away. The source fixes restore
static overrides, avoid re-minifying generated bytes when hashing, and make
optional cache initialization failures fall back to a full build. The large
capacity measurements above remain evidence for their explicitly frozen older
binary. Post-fix output verification is recorded separately.

To reproduce the exact asset proof helper, link it to the matching frozen
`utils` build (choose the rlib from that build):

```sh
rustc benchmarks/minify_asset_proof.rs --edition=2021 \
  -L dependency=target/release/deps \
  --extern utils=target/release/deps/libutils-0ee91b09bf9bb518.rlib \
  -o /tmp/minify_asset_proof
python benchmarks/classify_personal_outputs.py REPORT OFFICIAL_PUBLIC FORK_PUBLIC OUTPUT \
  --minifier /tmp/minify_asset_proof \
  --minifier-library target/release/deps/libutils-0ee91b09bf9bb518.rlib
```

The machine report records SHA-256 values for the helper source, executable and
linked library. Proofs accept exact minifier bytes and URL hash substitutions
only when both hash values match the actual associated asset bytes. Other HTML,
feed, image and policy differences remain visible for review.
