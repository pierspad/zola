# Personal-site browser verification

Verified 2026-11-03 with an actual ChatGPT in-app browser (IAB), using its browser UI and read-only DOM inspection. This is not a Node browser simulation. The browser bridge does not expose a reliable engine/version identifier in its documented surface; no browser-version or LCP claim is made.

## Isolation and provenance

Both builds use `benchmarks/work/remaining-personal-prepared/{site,official}` with the same compatible inputs (the unsupported upstream `infer_updated_from_git` option removed in both), complete prepush-generated dictionaries, and localhost base URLs. Production config, content and footer were not edited. Dedicated absolute `browser-public` output paths are required; a relative output path initially failed the theme's cache-busted CSS lookup and was replaced with an absolute path.

| Binary | SHA-256 |
|---|---|
| `target/release/zola` | `d2a648f5baa237de26bfa5cf130cbc73ce550ad2390f99ff09f39b78cb082e75` |
| `benchmarks/work/upstream-target/release/zola` | `d0bee1ddea6a4689cf5e0c1fda1860fd9429f99aec51309438d273abd2bc8ad8` |

The tested final source `static/search.js` SHA-256 is `57c22604e15f794bf21c8d02e5b4728cfdda2e2f89b913d8681b8625e6f1d9ff`. Both copies were refreshed from this exact source before the final browser run. Root commit `115ed98a` contains the client fixes and regression tests. The fork minifies this JavaScript/CSS, while upstream emits the original source.

## Actual functionality

Both fork and upstream builds passed these same checks after the fixes:

- English search activation opens the modal and focuses `#search-input`. `thesis` returns `Thesis templates` and `17.0.0.0`.
- ArrowDown selects the first result; Enter navigates to `/en/17.0.0.0/2026-10-21-template-tesi/`, which renders the expected `Thesis templates` heading and article controls.
- The visible language link navigates to the Italian article and changes the document language. Italian activation fetches the Italian dictionary.
- Both `perche` and `perché` return the same four titles, led by `Perché li chiamiamo ([a-zA-Z]+)log?`, followed by the Vesta, Pacman IgnorePkg and Powerlevel10k articles. The expected primary title was selected from source content, not inferred from search output.
- `zzqxnonexistent987` produces zero result items and an empty result area; it does not display a dedicated “no results” message.
- Escape clears results and closes the modal, restoring focus to `#search`. Queued animation-frame/timer callbacks cannot move focus back to the hidden input.

Search input is debounced by 120 ms. The final checks wait for actual visible result items before keyboard navigation; immediate post-fill snapshots can legitimately precede result updates.

The initial browser run revealed two shared client defects: preload plus immediate modal activation fetched the same dictionary twice; Escape could leave focus in the hidden input or allow queued focus callbacks to reclaim it. The shared client fixes deduplicate pending language fetches, remove failed pending entries to permit retry, cache valid empty dictionaries, restore opener focus, and guard delayed focus by modal state. Three Node regression tests execute the actual complete source with minimal DOM fixtures; these tests supplement the actual browser verification and are not described as browser tests.

## Observed delivery

`local_search_server.py` serves only localhost, logs actual requests, and negotiates test Brotli/gzip with `Cache-Control: no-store`. The browser sent `Accept-Encoding: gzip, deflate, br, zstd`, and compressible responses used Brotli quality 5. These are response-body bytes, excluding HTTP headers/TLS, not production CDN measurements.

| Final initial English home delivery before search activation | Fork | Upstream |
|---|---:|---:|
| Actual requests | 57 | 57 |
| Raw body bytes summed | 378,308 | 439,006 |
| Encoded body bytes summed | 206,613 | 222,662 |

The initial batch includes the lazy loader but excludes `search.js`, search CSS and dictionaries. It includes the browser's actual image/font/data requests; it is not a controlled cold-load latency benchmark.

| Search resource | Fork raw / Brotli bytes | Upstream raw / Brotli bytes |
|---|---:|---:|
| `/search.js` | 8,073 / 2,364 | 12,542 / 3,451 |
| `/search-custom.css` | 1,475 / 325 | 4,663 / 1,623 |
| `/search_dicts/search_dict.en.json` | 12,314 / 4,271 | 12,314 / 4,271 |
| `/search_dicts/search_dict.it.json` | 12,454 / 4,518 | 12,454 / 4,518 |

Final English activation transfers one script, one stylesheet and exactly one English dictionary: fork 21,862 raw / 6,960 Brotli body bytes; upstream 29,519 / 9,345. Italian activation after article/language navigation transfers one script, one stylesheet and exactly one Italian dictionary: fork 22,002 / 7,207; upstream 29,659 / 9,592. The no-store server and cross-document navigation redeliver script/CSS; this is not a claim that they are fetched once per whole browsing session.

Across the final EN/IT journey each language dictionary was fetched exactly once on each generator. Summed actual search requests equal 43,864 raw / 14,167 encoded bytes for fork and 59,178 / 18,937 for upstream. Unique-path bytes are lower because script/CSS repeat after navigation. Before the fix the English dictionary was fetched twice on initial activation (2 × 12,314 raw / 4,271 encoded).

All logged requests returned HTTP 200: 343 fork and 288 upstream across pre-fix, intermediate and final runs. This verifies the visited routes and their requested dependencies, not every possible site URL. No external form submissions or external navigation were performed.

## Limits and retained evidence

Both generators produced the same preexisting browser console error on cross-document article navigation: `InvalidStateError: Transition was aborted because of invalid state. Page already revealed`. The expected destination and article still rendered. The site uses both native cross-document transitions and a custom `document.startViewTransition(performDomSwap)` path; the browser-specific reveal warning has not been treated as a fork regression or suppressed speculatively. This is a non-clean console finding, not an all-console-errors pass.

This verifies the real personal client with 12 documents per language. It does not establish that the client can download/parse/search a 50k or 100k full index, nor that synthetic rank/engine timings represent browser interaction latency. Large-index guard outcomes remain explicit in the capacity report. No LCP, Lighthouse, production network, assistive-technology audit or multi-browser performance claim is made.

Local retained evidence under ignored `benchmarks/results/`:

- `browser-personal-fork.jsonl` and `browser-personal-official.jsonl`: request path/status/encoding/body-byte traces, including pre-fix runs.
- `browser-personal-phases.json`: line offsets delimiting post-fix and final runs.
- `browser-personal-summary.json`: binary/source hashes, final search request records and initial delivery paths/totals.

Re-run the root regression tests with `node --test tests/search-loading.test.cjs`. Rebuild each isolated copy with its respective binary, localhost `--base-url`, and an absolute dedicated `--output-dir`; launch `local_search_server.py` on ports 8765 and 8766; then repeat the UI checks above in an actual browser. The servers implement test compression, not production caching policy.

## Canonical capacity payload sizes

After the capacity oracle exited, the retained upstream canonical Fuse indexes were compressed incrementally in 1 MiB chunks without JSON parsing, browser loading or a Node query. The synthetic corpus is highly repetitive, so encoded sizes must not be generalized to real content. Compression does not remove decoded JSON size or client parse/search memory costs.

| Canonical English full index | Raw bytes | gzip level 6 bytes | Brotli quality 5 bytes |
|---|---:|---:|---:|
| 50,000 documents | 157,093,601 | 2,339,762 | 604,590 |
| 100,000 documents | 314,253,601 | 4,677,571 | 1,216,346 |

Inputs are `benchmarks/work/remaining-capacity-{50000x1,100000x1}-final/official/public/search_index.en.json`. The upstream copies retain the exact count; the fork 100k copy was subsequently mutated to 100,001 for incremental verification. Both full indexes exceed the synthetic runtime's 128 MiB decoded-file guard (134,217,728 bytes). A skipped guarded browser/runtime case is an explicit frontend architecture limitation, not evidence of supported 100k browser search. Partitioned dictionaries or server-side search should be evaluated for that scale. The actual personal dictionary remains under 15 KB per language, a separate verified scope. Machine-readable byte counts are retained in `benchmarks/results/canonical-capacity-compression.json`; compression duration is diagnostic only and not a performance comparison.

## Final release follow-up — 2026-11-04

The final release binary was separately checked in the actual IAB after the final core fixes. Its SHA-256 is `09016cb2b33af866484bbb349078d02408d6a2176e9eaafe63c64d2d367c4778` (`target/release/zola`, core source frozen at `531ec3c4`). This section is new evidence for that binary; the preceding upstream comparison and delivery totals retain their original provenance.

The fresh input snapshot was `benchmarks/work/final-compatibility-personal/site`, with all current personal inputs, the real isolated prepush dictionaries (12 documents per language), and root `static/search.js` SHA-256 `57c22604e15f794bf21c8d02e5b4728cfdda2e2f89b913d8681b8625e6f1d9ff`. The compatible snapshot removes `infer_updated_from_git`; the separate core verification covers the original feature config. The binary successfully built this snapshot with `--base-url http://127.0.0.1:8767` and the absolute external output directory `/home/ribben/Desktop/pierspad/github/sito-personale/zola/benchmarks/work/final-browser-public`. The emitted `robots.txt` is byte-for-byte identical to the root personal `static/robots.txt`. Production files were not edited.

The browser journey passed English activation and input focus; `thesis` returned the expected two titles; ArrowDown selected the first result and Enter opened the expected Thesis templates article. The visible language link opened its Italian translation. `perche` and `perché` returned the same four results listed above. The source-backed Italian body word `informatici` returned the expected etymology article even though it is absent from that article's title and description. `zzqxnonexistent987` returned zero items. Escape closed the modal and restored focus to `#search`; reopening used the already fetched dictionary.

This is indexed-snippet search: a diagnostic query for `clessidra`, which occurs later in the same source article but outside its generated snippet, returned no result. This does not establish whole-article body search.

The local request trace contains 109 requests, all HTTP 200, including exactly one English and one Italian dictionary fetch. Script/CSS repeat across document navigation as expected under the test server's no-store policy. No requested resource returned 404 in the visited journey. The existing cross-document `InvalidStateError: Transition was aborted because of invalid state. Page already revealed` was again observed; no additional warning/error was captured. This remains a local functional check, with no LCP, production latency, large-index browser or browser-version claim. The test server was stopped after verification.

New retained local evidence is `benchmarks/results/browser-final-09016-requests.jsonl` and `benchmarks/results/browser-final-09016-summary.json`. These are separate from the earlier browser logs.
