# Isolated release and incremental benchmarks

All synthetic inputs, bundled reference media, scripts and docs live in this
folder. Generated source trees, image caches and rendered output are temporary
children of ignored `benchmarks/work/`. JSON measurements belong in ignored
`benchmarks/results/`. Neither the production website nor its media is modified.
Only two inspected media files (37,194 bytes total) are copied into `assets/`;
provenance is recorded in [assets/README.md](assets/README.md).

## Release checks

From the Zola checkout root, with Python 3 (standard library only):

```sh
cargo fmt --check
cargo test --workspace --locked
cargo build --release --locked
python3 benchmarks/release_suite.py --mutations --output benchmarks/results/full-quick.json
python3 benchmarks/release_suite.py --size 10k --output benchmarks/results/full-10k.json
```

Quick is 100 pages; 10k is 10,000 pages. Every page contains 3–7 prose sections,
headings/TOC, tables, lists, quotations, Rust code with syntax highlighting,
internal Markdown links and two images. Four deterministic article classes vary
content length, dates, tags and categories. The site exercises:

- Sass with a shared palette partial and static CSS/JavaScript minification;
- section pagination, two paginated taxonomies, Atom/RSS and sitemaps;
- Fuse search with dates, headings and taxonomies;
- a real photographic journal illustration and terminal banner, six shared
  `resize_image` variants, lazy image attributes, and four colocated-media bundles;
- Tera components/shortcodes on 10% of pages, a shared base template and a pure
  page template on 25% of pages. The other page template calls `resize_image`.

Assertions require the expected page/search counts, Sass palette resolution,
section and taxonomy pagination, feeds, bundle copies, six processed images,
rich HTML markers, shortcode rendering and search fields. Every repeated build
must produce identical paths and SHA-256 hashes. No golden snapshot is needed
for intentional formatting changes across releases.

## Baseline comparison

```sh
python3 benchmarks/release_suite.py --binary /path/to/previous/zola --size 10k --output benchmarks/results/baseline.json
python3 benchmarks/release_suite.py --size 10k --baseline benchmarks/results/baseline.json --output benchmarks/results/candidate.json --fail-on-regression
```

Defaults are two warmups, five samples and four Rayon threads. Both 15% and 0.1
seconds must be exceeded for a timing warning; `--fail-on-regression` makes it a
failure. Without it, timing is advisory. Different baseline output fails unless
`--allow-output-changes` explicitly acknowledges an intentional cross-version
change. This never waives build repeatability. Workload version 2 rejects the
older minimal fixture baseline.

Reports include raw wall times/median, range and median absolute deviation,
excluded warmup durations, binary hash/version, checkout revision and
dirty state, Rust version, host metadata, thread count, fixture fingerprint,
source counts/bytes, persistent-cache disk bytes (not RAM), actual cache-hit
counters, coverage checks and output manifests. Checkout metadata
identifies the harness source, not an arbitrary supplied binary. Baselines must
match schema, workload, page count, threads and platform; use the same actual
host/power settings and alternate measurements if results are close.

## Incremental differential checks

When the candidate supports `build --incremental`:

```sh
python3 benchmarks/release_suite.py --build-arg=--incremental --mutations --mutation-build-arg=--incremental --output benchmarks/results/incremental-quick.json
python3 benchmarks/release_suite.py --size 10k --build-arg=--incremental --mutations --mutation-build-arg=--incremental --baseline benchmarks/results/full-10k.json --output benchmarks/results/incremental-10k.json
```

`--build-arg` affects repeated timed builds only. `--mutation-build-arg` affects
changed-tree candidates only, including an untimed priming build. The independent
oracle always performs a plain full build in a separate source copy with no
output, processed-image cache or `.zola*` cache. Add, edit (including taxonomy),
delete, rename, Sass partial, shared template, JavaScript, source image,
shortcode component and base-URL changes are applied in order. Each candidate
output must match its fresh full-build oracle exactly, including removed paths.
Per-scenario manifests are retained beside the result in an ignored
`<report-name>-mutations/` folder; failures also retain the candidate manifest.

Add timings repeat three times (`--add-runs`) by removing the new page, restoring
the candidate's pre-add cache, and adding it again. Reports preserve candidate
and plain full-build samples with the same retained image cache. The clean
oracle timing is separate and is **not** a fair speed comparison against a warm
candidate. Initial repeated timings measure unchanged builds; add timings measure
one new page; the other mutations are correctness checks with single timings.

## Measurement limits

Fixture creation, output hashing, assertions and mutation application are outside
timed builds. Processes are fresh but OS and image caches are retained after the
warmups: these are not cold-cache measurements. Two warmups allow generated
image files to settle before persistent-render cache measurements. The first warmup duration is not a
cold-build baseline. There is no peak-memory measurement. The full suite includes
real image processing but reuses a small set of six operations; it does not model
10,000 unique high-resolution photographs. File watching is not benchmarked.
Synthetic workloads complement existing feature tests and real-site builds.

Linux GNU CI runs the quick incremental workload and all differential mutations
against fresh full oracles using its already-built debug binary (two timed
samples and two repeated adds). These timings must not become release baselines.
The existing Criterion load-only bench remains useful for component profiling.

The harness defaults `RUST_LOG` to `site=info,zola=info` to capture actual cache-hit counters; an explicit environment value is preserved and recorded.

## Native multilingual Unicode workload

The separate multilingual harness preserves the existing monolingual fixtures,
mutation API and baseline compatibility:

```sh
python3 benchmarks/multilingual_suite.py --articles 24 --languages 15 --runs 1 --warmups 0 --mutations --output benchmarks/results/multilingual-smoke.json
python3 benchmarks/multilingual_suite.py --articles 1000 --languages 15 --mutations --output benchmarks/results/multilingual-1000x15.json
```

`--articles` counts logical article groups: 1,000 groups × 15 languages renders
15,000 article pages, plus translated homes, archives, taxonomy pages, feeds and
pagination. Defaults are 1,000 groups, 15 languages, five measured builds per
mode, one excluded warmup and four Rayon threads. The language set is en, it,
fr, de, es, pt, ru, el, ar, he, hi, bn, zh, ja and ko. Text is deterministic
synthetic Unicode material rather than real translations; Latin diacritics,
Cyrillic, Greek, Arabic, Hebrew, Devanagari, Bengali and CJK scripts occur
throughout titles, headings and bodies. Arabic/Hebrew pages use RTL direction.
Native `.LANG.md` filenames and translated `_index.LANG.md` files establish
Zola translation groups. Every language has its own archives, taxonomies,
Atom/RSS feeds and Fuse JSON search index. Fuse stores Unicode records without
requiring unsupported Elasticlunr language stemmers. This measures index
production and content integrity, not browser search latency or linguistic
search relevance. Shared source images and resize variants match the mono
fixture; this does not model 15,000 distinct photographs.

Coverage checks require exact locale search counts, Unicode metadata, HTML
language/direction and exact translation sibling hrefs for all 15 languages.
Every measured full and incremental output must match byte for byte. Mutation
checks add a translation to a seeded default-only article, add a complete
15-language group, edit a translation (title/body/taxonomy), delete a translation
and rename a translation. Each candidate is compared with an independent full
build in a copied tree without persistent or image caches. JSON evidence stores
the full oracle manifests. Reports distinguish logical groups, rendered article
pages, all HTML files, source Markdown bytes, per-language search bytes and
persistent cache bytes. This legacy harness reports null peak RSS with an explicit
unsupported diagnostic; use the fresh-broker controlled matrix for engine memory. Fixture version and fingerprint identify this
profile independently of the monolingual workload version. No 100,000-page run
is needed to validate the requested 1,000 × 15 target.

These synthetic timings do not directly predict the personal site's build.
The personal blog (up to about 100 pages) keeps plain full builds in `build.sh`.
Its custom search dictionaries remain enabled through `extra.custom_search`;
native search-index generation is disabled in both configured locales. The
browser still loads and scans a whole locale search JSON file. Existing category
layouts remain unchanged. No newspaper website is created by this harness.

Capacity must be expressed in published localized pages: 10,000 logical articles
with 15 translations means 150,000 article pages; 100,000 logical articles means
1.5 million article pages, before archives and taxonomies. The measured target
here is 1,000 logical articles / 15,000 localized article pages. Do not extrapolate
its runtime linearly to those larger targets or to the personal site's theme.

The recorded 1,000 × 15 run produces about 1.78 GB of output, largely because
feeds are intentionally uncapped and contain complete article bodies. XML is
about 1.55 GB (87%): root and shared-tag feeds repeat every article, and other
taxonomy feeds repeat subsets, in both Atom and RSS for every locale. Article
HTML itself is about 169 MB; one representative article is 403 words / 2.8 KB
Markdown and 7.4 KB HTML. The fixture has 3–7 prose sections per article. Bound
feed entries or use summaries before drawing capacity conclusions for a larger
production site; this fixture measures the full-content feed policy explicitly.

For the recorded run, `multilingual-1000x15-quiet.json` is the final steady-state
timing report (five samples per mode). `multilingual-1000x15.json` retains the
full differential correctness evidence; its timings are provisional because a
short smoke overlapped part of the earlier run. Both use the same fixture hash.
The quiet report has excluded warmups, not a deliberately cold filesystem cache.
The historical direct-wait4 RSS values are invalid for engine memory and superseded
by the controlled fresh-broker matrix.

## Optional newspaper preparation profile

The default `--profile stress` remains uncapped with full article bodies in feeds;
its fixture files and fingerprints are unchanged. For a separate future newspaper:

```sh
python3 benchmarks/multilingual_suite.py --profile newspaper --feed-limit 7 --articles 24 --languages 2 --runs 1 --warmups 0 --mutations --output benchmarks/results/newspaper-smoke.json
python3 benchmarks/multilingual_suite.py --profile newspaper --articles 1000 --languages 15 --runs 1 --warmups 1 --output benchmarks/results/newspaper-1000x15.json
python3 benchmarks/multilingual_suite.py --profile newspaper --articles 100 --languages 1 --runs 1 --warmups 0 --output benchmarks/results/newspaper-mono.json
```

The newspaper profile defaults to 50 entries per feed as a chosen example, not an
editorial standard. `--feed-limit` adjusts the cap. Summaries use Zola's native
`<!-- more -->` boundary after the introduction; articles retain complete bodies.
Coverage parses every Atom/RSS file, checks the entry cap and checks that full-body
tables are absent. Reports identify profile, feed policy, fixture fingerprint,
total feed bytes and maximum feed entries alongside source, output, search,
cache, wall-time and peak-RSS metrics. Compare only matching profiles, feed
policies, fixture fingerprints, article/locale counts, threads and hosts; this
multilingual harness has no automated baseline comparison. The separate release
harness retains its existing baseline compatibility checks.

Archives and taxonomy terms paginate at 20 entries. One locale is also supported;
translation-addition mutations are skipped when there are no other locales.
Large runs are opt-in through `--articles` and `--languages`. 100,000 published
article pages could mean 100,000 articles in one locale or roughly 6,667 articles
in 15 locales; 100,000 articles in 15 locales means 1.5 million published article
pages. No 100,000-page capacity is verified here. Whole per-locale search JSON
production does not establish acceptable browser memory or latency at that scale.
Unique production photographs, deployment limits and editorial updates require
separate measurements.

A preliminary 8-article, one-locale `--mutations` run exposed a fork regression introduced by commit `0bed47da`
(static copying moved before image pruning): deleting page 5 removes the last reference
to its terminal thumbnail variant, but a warm build can leave that unused file
in `public/processed_images/` while a fresh full oracle omits it. This affected
warm full builds as well as incremental builds before the cleanup fix. Official
upstream copies static assets after processing/pruning images; its controlled
eight-page deletion oracle is exact. The fixed fork also passes both warm full
and incremental deletion oracles. Earlier debug failure artifacts are retained. The strict oracle remains enabled
and reports the mismatch; candidate outputs are not filtered or cleared to hide
it. The 24-article/two-locale smoke passes all five mutation oracles.

The bounded 1,000 × 15 sample (`newspaper-1000x15.json`) produced 243,002,414
output bytes, including 16,559,618 feed bytes across 480 feeds, at most 50 entries
each. One measured build after one warmup took 9.017 seconds full / 8.995 seconds
incremental, with historical RSS measurements now deprecated. This single sample is a sizing
observation, not a timing baseline or an incremental speedup claim; cache-hit
counters were unavailable and persistent-cache disk size was only 25 bytes.

### Controlled matrix with official upstream

`python3 benchmarks/matrix.py --output benchmarks/results/matrix.json`
first builds the local fork using `cargo build --release --locked`, captures its
compiler/profile/environment/source/lock/executable attestation, then refreshes
and builds the isolated official upstream baseline before measurements.
`--prepare-only` performs these preparations without running any samples.
An arbitrary `--binary` requires `--fork-build-metadata` with a matching SHA-256;
`fork_build.py --profile dev --output PATH` prepares attested local debug binaries
for correctness smoke checks.
Fixture generation and hashing are outside build timings. The default matrix uses
100, 1,000, 10,000 monolingual articles and 1,000 articles in 15 locales, with both
unbounded full feeds and bounded summary feeds. Both binaries receive identical
inputs under the recorded common-search-v2 compatibility policy: unsupported
`include_headings` and `include_taxonomies` options are removed; `include_date`
is disabled because official Fuse JSON does not emit dates. This comparison does
not measure the additional search fields.

Each case records application-cache-empty full builds, first incremental cache
population, two warmups per mode, and cyclically ordered measured upstream full, fork
full and fork incremental builds (five samples at <=1,000 pages; three above).
JSON retains raw times, child-specific peak RSS, median/MAD/range, cache-hit log
counters, source/output/feed/search/cache bytes, and fixture/binary identities.
Markdown reports are generated beside JSON. Cold application cache does not
mean cold OS page cache. Three samples provide limited evidence about variance.

The watchdog kills only its own process group at timeout, RSS, disk growth or
free-disk reserve limits. RSS is capped by the configured limit and 40% of
available host/cgroup memory at subprocess launch. Default caps are 120 seconds,
3 GiB RSS, 8 GiB filesystem growth and 8 GiB free-disk reserve. A budget abort
is retained as incomplete, never treated as verified capacity. Larger sizes are
explicit opt-in (`--cases 50000x1 --profiles newspaper`) after reviewing smaller
case resource use. Exact output manifests are checked without filtering stale
files; baseline differences require review and mutation mismatches remain visible.

`matrix.py` is the canonical release comparison entry point. The older
`release_suite.py` and `multilingual_suite.py` remain focused diagnostics and do
not alone constitute release validation against official upstream. Matrix
baseline sync/build errors and strict correctness differences fail the command;
resource-budget aborts are explicitly incomplete. `--offline` is an explicit
exception that uses a previously pinned official checkout and marks its metadata
stale. CI uses tiny fixtures to check baseline and mutation correctness; its
single samples are not performance evidence.

Upstream synchronization happens once at the start of each matrix invocation,
not as a background schedule. The isolated official HEAD checkout remains
unmodified. Its pinned commit, latest stable tag, toolchain, default features,
lockfile and executable hashes are recorded; copying fixtures verifies the same
input fingerprint before either engine runs.

Raw official/fork output hashes are retained even for intentional differences.
The classifier permits only exact fixture CSS/JS minifier results and the known
448×333 / 2200×872 Markdown image dimensions plus first logbook image loading
change. Every other upstream difference requires review and fails validation.
Fork full/incremental and mutation-oracle comparisons remain byte-exact without
these exceptions. Watchdog exit polling contributes at most approximately 5 ms
to observed wall time; this matters most for tiny fixtures. CPU user/system/total
seconds come directly from child `wait4` resource usage.

Resource accounting uses `resource_runner.py`, a freshly executed small broker
which forks the engine and reports the inner child's `wait4` peak RSS, CPU and
wall time. Directly measuring a child forked from the large Python fixture/report
process can inherit the parent's pre-exec RSS high-water floor on Linux. The
outer wrapper's RSS is retained only as explicitly excluded diagnostic evidence.
A control with a 200 MiB parent and a 20 MiB child measured 30.9 MB inner-child
RSS versus 231.8 MB outer-wrapper RSS. The earlier provisional matrix is archived
as `matrix-provisional-invalid-rss.json`; its RSS is invalid and its outer-launch
wall times are superseded by the clean broker matrix. Earlier direct-wait4 RSS
from `multilingual_suite.py` is diagnostic and must not be used for capacity
claims; use the canonical matrix for reliable engine memory measurements.


### Compare each future fork release with the previous release

Keep the completed controlled aggregate as the first history entry. Canonical
`matrix.py` runs automatically embed a matching `fork_build` attestation. A comparison with official upstream alone does not
establish an improvement over an earlier fork release. The postprocessor runs
without building or executing either engine:

```sh
python3 benchmarks/compare_matrix.py benchmarks/results/matrix-final.json --output benchmarks/results/release-history.json
python3 benchmarks/compare_matrix.py benchmarks/results/next-release.json --baseline benchmarks/results/matrix-final.json --output benchmarks/results/release-comparison.json --fail-on-regression
```

The first command explicitly records initial history with no previous-release
claim. Later comparisons require matching fixture fingerprints/policies,
platform/CPU, threads, warmups, feed limit, inner-engine measurement method,
and attested compiler/features/release profile. Missing metrics or incompatible
inputs fail comparison. Fork executable hashes may change by design; changed
official executable hashes and dependency locks are reported explicitly. Added
cases lack a baseline; removed cases are listed. Measurements remain observations,
not proof that a change came from engine code rather than dependencies or host load.

For each matching case, full and incremental wall/CPU/RSS ratios are retained.
The advisory regression threshold requires an increase above 15% and an absolute
floor (0.1 seconds for wall/CPU, 32 MiB for maximum observed peak RSS); wall time
also must exceed three times the larger median absolute deviation. These are
screening thresholds, not significance tests. A possible increase obscured by
wall-time noise is labeled `inconclusive_noise`; absence of a regression flag is
not proof of equivalence or guaranteed safety. `--fail-on-regression` converts
flags into a failing exit status. Linux CI runs synthetic comparison checks and
the 200 MiB parent / 20 MiB child resource-accounting regression checks.

Preparation-only validation (no timing samples):

```sh
python3 benchmarks/matrix.py --prepare-only --output benchmarks/results/prepared.json
```
