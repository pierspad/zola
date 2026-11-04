# Final verification — 2026-11-04

The final release executable is `target/release/zola`, SHA-256
`06ccb30d43c28c3c512223cc320bde01e04934066aedb912656d9ee5e100c5d3`.
The clean build attestation records commit `cd38a39a`, `dirty: false`, locked
default features, LTO, one codegen unit and stripping. The final core fix is
`a1d3d062`; later commits change benchmark proofs and documents only.
Evidence: `results/fork-build-final-svg.json`, `results/final-svg-build.log` and
`results/final-svg-source-scope.json`. No further Cargo rebuild was needed for
benchmark-only changes.

## Correctness and compatibility

All 529 Rust tests pass (one additional test ignored), as do formatting, 49
Python benchmark tests and three Node tests of the actual production search
script. The SVG regression tests include the actual `792pt × 388.8pt` and
`720pt × 432pt` cases, uppercase SVG extensions, pixel/unitless geometry,
fractional/relative geometry, style overrides, and source edits from physical
to pixel dimensions and back with exact cached/full-build oracles.

The strict review found and fixed real defects rather than normalizing them:
optional cache initialization now falls back to a full build, static overrides
win over generated output, resource hashes describe the actual winning bytes,
and ambiguous SVG geometry is left to the browser. Treating SVG point values as
integer HTML pixel dimensions had changed displayed size. The final Markdown
helper accepts only finite positive integral pixel/unitless SVG dimensions;
physical/relative/fractional/viewBox-only/style-dependent geometry gets no added
width/height attributes. Template `get_image_metadata` behavior is unchanged.
The only dependency-lock change adds a direct edge to the already locked
`roxmltree 0.20.0`; no package version changed.

The final executable passed a fresh 24 × 2 three-mode fixture comparison with
byte-exact fork full/incremental output and zero unknown baseline differences.
It also passed real executable-only permissions (`0111`): full, incremental and
repeated incremental builds succeeded with byte-identical output while reading
the executable was denied. See `final-svg-smoke-24x2.json` and
`final-svg-execute-only.json`.

Before the final SVG-only fix, the `09016cb2…` executable passed all ten mutation
scenarios at both 24 × 2 and 10,000 × 1, each against an independent fresh full
oracle and with changed output. Its fresh 10,000 × 1 population comparison also
passed. These reports retain their actual binary scope:
`final-compatibility-mutations-{24x2,10000x1}.json` and
`final-compatibility-population-10000x1.json`. The SVG change was covered by the
new targeted cache/source tests and actual final personal-site comparison;
the larger suites were not needlessly repeated.

## Actual personal site

`final-svg-personal.json` uses a fresh complete input snapshot, including the
current search client and separately generated search dictionaries. It contains
8 authored article bundles / 16 article-language pages and 32 Markdown files
including sections. Original production configuration fork full/incremental
output is byte-exact. Official upstream rejects `infer_updated_from_git`; the
compatible comparison explicitly removes that flag from **both** inputs.
This is not identical configuration support.

The cold compatible comparison removes only the site's
`static/processed_images` cache on both sides and preserves tracked theme assets.
All 27,077 input files have identical pre-build manifests (SHA-256
`7b57fb952da8a4d38b3f73efec41566218211c551bf23316b7de468705fc4410`).
Original production checks separately retain source caches. The older recursive
copy exclusion had removed theme assets and cache files from the official side
only; its image-byte differences were fixture asymmetry, not an encoder defect.

Both original and compatible fork full/incremental outputs are byte-exact.
The complete official/fork manifests contain 299 changed paths, all accounted
for by `final-svg-personal-classification.json`:

| Strict evidence | Paths |
|---|---:|
| Removed localized copy, identical bytes at the unprefixed path | 64 |
| Exact output from the fork's linked CSS/JS minifier | 29 |
| Only verified resource URLs and source-image attributes differ | 206 |
| Unclassified | 0 |

The classifier recomputes complete manifests and rejects incomplete changed-path
lists. Resource URL hashes must match actual asset bytes. Replacements affect
only parsed start-tag attribute spans, never script literals or arbitrary text.
Added raster dimensions require identical source bytes and actual decoded sizes;
SVG proofs accept only integral pixel/unitless dimensions.

Lazy-to-eager exceptions require a first-native-Markdown-image source proof:
the locked Markdown parser reads the exact post-front-matter source, ignoring
raw HTML and fenced examples. Source SHA-256, parser provenance and article URL
are recorded; the classifier re-runs the parser and matches a unique resolved
URL **and native alt text**. This distinguishes Vesta's banner from its native
Markdown image and rejects duplicate same-URL/same-alt candidates. The six
Italian/English source proofs are in `final-svg-native-image-proofs.json`.
Feed comparisons resolve relative images against each article URL, require exact
HTML escaping roundtrips, and replace only the content span inside the
corresponding entry; surrounding XML remains byte-exact. Classified deliberate
URL/loading changes are not a claim of old-URL compatibility or byte identity.
Earlier permissive provisional zero-unknown claims are superseded by these
stricter final proofs.

Three independent-process samples per mode, with rotated order:

| Personal compatible mode | Median seconds | MAD seconds | Maximum peak MiB |
|---|---:|---:|---:|
| Official full | 0.205277 | 0.002509 | 80.50 |
| Fork full | 0.221231 | 0.003795 | 80.52 |
| Fork incremental | 0.576938 | 0.013228 | 140.99 |

The retained incremental runs record 8 Markdown hits and zero page-HTML hits.
The approximately 0.37-second incremental overhead over official full remains
below the user's stated one-second tolerance. These tiny host-sensitive samples
do not prove a causal speed ranking or that the fork is always faster.

Actual output sizes (`KB = 1,000 bytes`, uncompressed filesystem bytes):

| Output | Files | Bytes | KB |
|---|---:|---:|---:|
| Official compatible | 631 | 23,049,373 | 23,049.373 |
| Fork compatible | 567 | 17,640,916 | 17,640.916 |
| English custom search dictionary, identical in both | 1 | 12,314 | 12.314 |
| Italian custom search dictionary, identical in both | 1 | 12,454 | 12.454 |

`final-svg-output-sizes.json` also records per-extension totals and dictionary
hashes. The smaller output includes intentional localized-asset deduplication;
it is not a claim that all historical asset URLs remain available.

## Browser, capacity and remaining limits

The final `06ccb30d…` executable built the actual site into an absolute external
output directory. Both generated Italian/English Vesta pages omit forced SVG
width/height attributes. The integrated browser became unavailable (empty
browser inventory), so a fresh actual-browser geometry/search pass on this
executable could not be completed. No new visual or LCP claim is made.

The immediately preceding `09016cb2…` executable's actual integrated-browser
smoke remains separate evidence: 109 requests, all HTTP 200, exactly one search
fetch per locale, English keyboard navigation, Italian accented/body-snippet
queries, no-results and Escape/focus restoration; resource hashes and custom
`robots.txt` bytes passed. The later core change affects only SVG dimension
attributes. See [PERSONAL_BROWSER_VERIFICATION.md](PERSONAL_BROWSER_VERIFICATION.md)
for precise provenance and the final browser limitation.

Large capacity checks in `QUALITY.md` retain the older `d2a648f5…` scope. Single
100,000-article population observations were official 74.774 s / 4.870 GiB,
fork full 79.572 s / 4.835 GiB and incremental 78.724 s / 5.921 GiB. Warm no-op
and add-to-100,001 checks matched exact fresh full oracles. They were not rerun
for the later compatibility/SVG fixes and do not establish a speed ranking.
The controlled 1,000 × 15 repeated timing did not reproduce a stable 4.7%
regression; it also does not prove the fork always faster.

At 100,000 articles, the whole decoded Fuse index exceeds the 128 MiB client
guard: compression does not solve decoded memory. Partitioned or server search
remains future work; giant-index browser queries are not certified. The earlier
nonblocking View Transition console warning remains documented. No unrelated
server-search feature was added during verification.
