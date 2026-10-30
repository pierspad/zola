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
