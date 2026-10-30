+++
title = "CLI usage"
weight = 15
+++

Zola only has 4 commands: `init`, `build`, `serve` and `check`.

You can view the help for the whole program by running `zola --help` and
that for a specific command by running `zola <cmd> --help`.

## init

Creates the directory structure used by Zola at the given directory after asking a few basic configuration questions.
Any choices made during these prompts can be easily changed by modifying `zola.toml`.

```bash
$ zola init my_site
$ zola init
```

If the `my_site` directory already exists, Zola will only populate it if it contains only hidden files (dotfiles are ignored). If no `my_site` argument is passed, Zola will try to populate the current directory.

In case you want to attempt to populate a non-empty directory and are brave, you can use `zola init --force`. Note that this will _not_ overwrite existing folders or files; in those cases you will get a `File exists (os error 17)` error or similar.

You can initialize a git repository and a Zola site directly from within a new folder:

```bash
$ git init
$ zola init
```

## build

This will build the whole site in the `public` directory (if this directory already exists, it is deleted).

```bash
$ zola build
```

You can override the config `base_url` by passing a new URL to the `base-url` flag.

```bash
$ zola build --base-url $DEPLOY_URL
```

This is useful for example when you want to deploy previews of a site to a dynamic URL, such as Netlify
deploy previews.

You can override the default output directory `public` by passing another value to the `output-dir` flag. If this directory already exists, the user will be prompted whether to replace the folder; you can override this prompt by passing the --force flag.

```bash
$ zola build --output-dir $DOCUMENT_ROOT
```

You can point to a config file other than `zola.toml` like so (note that the position of the `config` option is important):

```bash
$ zola --config config.staging.toml build
```

You can also process a project from a different directory with the `root` flag. If building a project 'out-of-tree' with the `root` flag, you may want to combine it with the `output-dir` flag. (Note that like `config`, the position is important):
```bash
$ zola --root /path/to/project build
```

By default, drafts are not loaded. If you wish to include them, pass the `--drafts` flag.

### Persistent incremental builds

Use `zola build --incremental --cache-memory-limit 512` to allow an estimated
512 MiB for retained rendering-cache entries (`2048` means 2 GiB). Omit the option
for unrestricted cache retention. `0` runs the normal renderer and leaves an
existing cache untouched. The option requires `--incremental`.

The allowance covers loaded and newly retained entries using a conservative
estimate of eight times their serialized size plus map overhead. Cache files too
large for the allowance are skipped before decoding; entries that do not fit
are rendered normally and omitted from the next cache. This can reduce reuse,
without changing the generated site. Cache reads and writes stream JSON.
This is a cache allowance, not a total-process RAM limit: site metadata, search,
rendering, templates and temporary allocations also consume memory.

`zola build --incremental` stores reusable rendering results in `.zola-cache/`
inside the project. The first run fills the cache; later runs can reuse unchanged
Markdown and page HTML. Add `.zola-cache/` to your site's `.gitignore`. Removing
that directory safely resets the cache. Ordinary `zola build` does not use it.
Set `RUST_LOG=info` to see the numbers of reused Markdown and page HTML renders.
The `.zola-cache/` directory is reserved: do not select it, or an ancestor
containing it, as the output directory when using `--incremental`.

This is conservative rendering reuse, not a constant-time build: Zola still loads
all content, validates links, rebuilds sections, taxonomies, feeds, search and
sitemaps, and recreates the output directory. Deleted and renamed outputs therefore
disappear as in a clean build. Source assets, template changes, rendering options
and the executable itself invalidate cached work. Cache writes happen only after
a successful build; unreadable or malformed cache files are ignored.

Content with Tera expressions or shortcodes, template-backed heading anchors,
HTML comments/summary markers and unresolved internal links is rendered normally.
Files consulted for Markdown image dimensions are tracked by their actual paths
and contents, including missing files and fallback lookups. Page HTML is reused only
for a small pure template subset: context expressions, control flow, known pure
filters, and static template inheritance/includes. Function calls (including
`resize_image`, `get_page`, `get_section`, and `load_data`), components, custom
filters/tests and uncertain template syntax run normally. This preserves image
processing and other rendering effects. Neighbours, translations, backlinks and
config values participate in page HTML keys. Gains depend on the site's content
and template workload; cache hashing, loading and writing can outweigh savings
on small or mostly uncacheable sites.

## serve

This will build and serve the site using a local server. You can also specify
the interface/port combination to use if you want something different than the default (`127.0.0.1:1111`).

You can also specify different addresses for the interface and base_url using `--interface` and `-u`/`--base-url`, respectively, if for example you are running Zola in a Docker container.

> By default, devices from the local network **won't** be able to access the served pages. This may be of importance when you want to test page interaction and layout on your mobile device or tablet. If you set the interface to `0.0.0.0` however, devices from your local network will be able to access the served pages by requesting the local ip-address of the machine serving the pages and port used.
>
> In order to have everything work correctly, you might also have to alter the `base-url` flag to your local ip or set it to `/` to use server-base relative paths.

Use the `--open` flag to automatically open the locally hosted instance in your
web browser.

Before starting, Zola will delete the output directory (by default `public` in project root) to start from a clean slate.

If you are specifying the directory but are also using the `output-dir` flag, Zola will not use the specified directory if it already exists unless the --force flag is used.

```bash
$ zola serve
$ zola serve --port 2000
$ zola serve --interface 0.0.0.0
$ zola serve --interface 0.0.0.0 --port 2000
$ zola serve --interface 0.0.0.0 --base-url 127.0.0.1
$ zola serve --interface 0.0.0.0 --base-url /
$ zola serve --interface 0.0.0.0 --port 2000 --output-dir www/public
$ zola serve --open
```

The serve command will watch all your content and provide live reload without
a hard refresh if possible. If you are using WSL2 on Windows, make sure to store the website on the WSL file system.

Some changes cannot be handled automatically and thus live reload may not always work. If you
fail to see your change or get an error, try restarting `zola serve`.

By default, the live reload will be debounced by one full second so as to more
gracefully handle multiple changes to your input files in rapid succession. You
have control over that debouncing duration with the `--debounce <duration_ms>`
flag.  
You may use `-d1` to (virtually) disable it altogether: for technical reasons
(and keeping things simple), a "debounce" of 0 is not supported.

You can also point to a config file other than `zola.toml` like so (note that the position of the `config` option is important):

```bash
$ zola --config config.staging.toml serve
```

By default, drafts are not loaded. If you wish to include them, pass the `--drafts` flag.

## check

The check subcommand will try to build all pages just like the build command would, but without writing any of the
results to disk. Additionally, it will also check all external links in Markdown files by trying to fetch
them (links in the template files are not checked).

You can skip link checking for all the external links by `--skip-external-links` flag.

By default, drafts are not loaded. If you wish to include them, pass the `--drafts` flag.

## Colored output

Colored output is used if your terminal supports it.

*Note*: coloring is automatically disabled when the output is redirected to a pipe or a file (i.e., when the standard output is not a TTY).

You can disable this behavior by exporting one of the following two environment variables:

- `NO_COLOR` (the value does not matter)
- `CLICOLOR=0`

To force the use of colors, you can set the following environment variable:

- `CLICOLOR_FORCE=1`

## Extra information

Zola can provide detailed logging about its behavior via the `RUST_LOG` variable:

- To see timing information from Zola, set `RUST_LOG=zola=info,site=debug`.
- To see debug information, set `RUST_LOG=debug`. *Note*: The output will be **very noisy**, use with caution.
- To disable all log output entirely, set `RUST_LOG=off`.

See the [env_logger documentation](https://docs.rs/env_logger/0.11.8/env_logger/#enabling-logging) for a full reference on `RUST_LOG`.

### Automatic cache allowance

Run `python3 scripts/build_with_cache.py --binary target/release/zola` from
this repository (or supply an absolute binary path from a site directory).
The wrapper always enables incremental content builds. It chooses the smallest
of one quarter of physical RAM, half of available RAM, and half of remaining
ancestor cgroup memory, in MiB. Unknown measurements are omitted; if all are
unknown the allowance is 256 MiB. Linux checks host memory and cgroup v1/v2;
Windows checks physical memory; macOS currently checks total physical memory
only. This estimates retained cache memory, not total process RSS.

Override with `--cache-memory-limit MIB` or `ZOLA_CACHE_MEMORY_LIMIT_MIB`;
zero disables cache reuse. Pass build options after `--`. The wrapper logs its
measurements and replaces itself with Zola, preserving exit status and signals.
Plain `zola build` continues to perform a full build. Benchmark full-build
oracles must call the binary directly.
