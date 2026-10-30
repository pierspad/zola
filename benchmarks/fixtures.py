"""Reproducible rich Zola workloads and filesystem mutations; no production inputs."""
from pathlib import Path
import shutil

WORKLOAD = 4
ASSETS = Path(__file__).resolve().parent / "assets"


def write(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def page_text(i):
    kinds = ("field-notes", "engineering", "gallery", "reference")
    kind = kinds[i % len(kinds)]
    intro = ("A measured observation connects the logbook image to reproducible field notes.",
             "A technical walkthrough explains cache dependencies and measured build behavior.",
             "A visual essay compares source images, thumbnails, captions, and responsive layouts.",
             "A reference entry collects linked definitions, examples, tables, and practical checks.")[i % 4]
    body = "\n\n".join(
        f"## Observation {j}\n\n{intro} Entry {i}, sample {j}. "
        "The **important detail** is preserved with *emphasis*, inline `code`, "
        "and [the article index](@/articles/_index.md). "
        "We describe a deterministic workload with several paragraphs rather than a single stub.\n\n"
        "> A repeatable observation is useful only when its inputs are recorded.\n\n"
        "- Collect source material\n- Render and check dependencies\n- Compare the complete output\n\n"
        "| Input | Expected result |\n| --- | --- |\n| Markdown | Rendered HTML |\n| Image | Responsive variant |\n\n"
        "```rust\nfn record(sample: usize) -> usize {\n    sample.saturating_add(1)\n}\n```"
        for j in range(3 + i % 5))
    shortcode = '{{ <note label="Dependency-aware annotation" /> }}' if i % 10 == 0 else ""
    return f'''+++
title = "Page {i:05}: {kind}"
date = 2024-01-{i % 28 + 1:02}
description = "Reproducible {kind} article {i}"
template = "{'page_pure.html' if i % 4 == 3 else 'page.html'}"
[taxonomies]
tags = ["tag-{i % 10}", "shared"]
categories = ["{kind}"]
[extra]
kind = "{kind}"
image = "{'logbook.webp' if i % 2 == 0 else 'terminal.webp'}"
variant = {i % 3}
+++
# Field record {i}

{intro}

![Historical logbook](/media/logbook.webp "Source material")

{body}

{shortcode}

![Terminal illustration](/media/terminal.webp "Secondary illustration")
'''


def generate(root, pages):
    write(root, "config.toml", '''base_url = "https://release.example.com"
title = "Release field journal"
compile_sass = true
build_search_index = true
minify_html = true
generate_feeds = true
feed_filenames = ["atom.xml", "rss.xml"]
taxonomies = [
 {name = "tags", paginate_by = 20, feed = true},
 {name = "categories", paginate_by = 20, feed = true}
]
[markdown]
lazy_async_image = true
[markdown.highlighting]
theme = "github-dark"
[search]
index_format = "fuse_json"
include_date = true
include_headings = true
include_taxonomies = true
''')
    write(root, "content/_index.md", '+++\ntitle = "Release fixture"\n+++\n')
    write(root, "content/articles/_index.md", '+++\ntitle = "Articles"\nsort_by = "date"\npaginate_by = 20\n+++\nA collection of deterministic long-form records.\n')
    write(root, "templates/base.html", '''<!doctype html><html lang="en" dir="ltr"><head><meta charset="utf-8"><link rel="canonical" href="{% if current_url is defined %}{{ current_url }}{% else %}{{ get_url(path="404.html") }}{% endif %}"><meta name="description" content="{% if page is defined %}{{ page.description }}{% else %}Deterministic synthetic field journal{% endif %}"><title>{% block title %}Release journal{% endblock title %}</title><link rel="stylesheet" href="/journal.css"><script src="/assets/main.js" defer></script></head><body><header><a href="/">Journal</a><nav><a href="/articles/">Articles</a><a href="/tags/">Tags</a><a href="/categories/">Categories</a></nav></header><main>{% block content %}{% endblock content %}</main><footer>Deterministic release workload</footer></body></html>''')
    write(root, "templates/404.html", '''{% extends "base.html" %}{% block title %}Page not found{% endblock title %}{% block content %}<h1>Page not found</h1>{% endblock content %}''')
    # This workload produces only pagination-first-page aliases. Give these redirect
    # documents destination canonicals matching their immediate refresh.
    write(root, "templates/internal/alias.html", '''{% set code = url | split(pat="/") | nth(n=3) %}{% if code not in ["it", "fr", "de", "es", "pt", "ru", "el", "ar", "he", "hi", "bn", "zh", "ja", "ko"] %}{% set code = "en" %}{% endif %}<!doctype html><html lang="{{ code }}" dir="{% if code == "ar" or code == "he" %}rtl{% else %}ltr{% endif %}"><head><meta charset="utf-8"><title>Listing redirect</title><meta name="description" content="Redirect to the first listing page"><link rel="canonical" href="{{ url }}"><meta http-equiv="refresh" content="0; url={{ url }}"></head><body><a href="{{ url }}">First listing page</a></body></html>''')
    write(root, "templates/index.html", '''{% extends "base.html" %}{% block content %}<h1>{{ section.title }}</h1>{% set articles = get_section(path="articles/_index.md") %}<p>{{ articles.pages | length }} field records</p>{% for page in articles.pages %}{% if loop.index <= 12 %}<article><a href="{{ page.permalink }}">{{ page.title }}</a><p>{{ page.description }}</p></article>{% endif %}{% endfor %}{% endblock content %}''')
    write(root, "templates/section.html", '''{% extends "base.html" %}{% block content %}<h1>{{ section.title }}</h1>{{ section.content | safe }}{% for page in paginator.pages %}<article><a href="{{ page.permalink }}">{{ page.title }}</a><p>{{ page.description }}</p></article>{% endfor %}<nav>Page {{ paginator.current_index }} of {{ paginator.number_pagers }}{% if paginator.previous %}<a href="{{ paginator.previous }}">Previous</a>{% endif %}{% if paginator.next %}<a href="{{ paginator.next }}">Next</a>{% endif %}</nav>{% endblock content %}''')
    write(root, "templates/page.html", '''{% extends "base.html" %}{% block title %}{{ page.title }}{% endblock title %}{% block content %}<article class="{{ page.extra.kind }}"><h1>{{ page.title }}</h1><time>{{ page.date }}</time>{% set width = 160 + page.extra.variant * 40 %}{% set thumb = resize_image(path="static/media/" ~ page.extra.image, width=width, op="fit_width", format="webp", quality=80) %}<figure><img src="{{ thumb.url }}" width="{{ thumb.width }}" height="{{ thumb.height }}" alt="Processed source image"><figcaption>{{ page.extra.kind }}</figcaption></figure><aside>{% for heading in page.toc %}<a href="{{ heading.permalink }}">{{ heading.title }}</a>{% for child in heading.children %}<a href="{{ child.permalink }}">{{ child.title }}</a>{% endfor %}{% endfor %}</aside>{{ page.content | safe }}</article>{% endblock content %}''')
    write(root, "templates/components.html", '{% component note(label: string) %}<aside class="note">{{ label }} — field journal</aside>{% endcomponent %}')
    write(root, "templates/page_pure.html", '''{% extends "base.html" %}{% block title %}{{ page.title }}{% endblock title %}{% block content %}<article class="reference"><h1>{{ page.title }}</h1><time>{{ page.date }}</time><figure><img src="/media/logbook.webp" alt="Source journal"><figcaption>Reference material</figcaption></figure>{{ page.content | safe }}</article>{% endblock content %}''')
    for taxonomy in ("tags", "categories"):
        write(root, f"templates/{taxonomy}/list.html", '''{% extends "base.html" %}{% block content %}<h1>{{ taxonomy.name }}</h1>{% for term in terms %}<a href="{{ term.permalink }}">{{ term.name }} ({{ term.pages | length }})</a>{% endfor %}{% endblock content %}''')
        write(root, f"templates/{taxonomy}/single.html", '''{% extends "base.html" %}{% block content %}<h1>{{ term.name }}</h1>{% for page in paginator.pages %}<a href="{{ page.permalink }}">{{ page.title }}</a>{% endfor %}<p>Page {{ paginator.current_index }} of {{ paginator.number_pagers }}</p>{% if paginator.next %}<a href="{{ paginator.next }}">Next</a>{% endif %}{% endblock content %}''')
    write(root, "sass/_palette.scss", '$ink: #243746; $paper: #f4f0e8; $accent: #8b491e;\n')
    write(root, "sass/journal.scss", '''@import "palette";
body { color: $ink; background: $paper; font-family: system-ui, sans-serif; margin: 0 auto; max-width: 70rem; padding: 2rem;
  a { color: $accent; } article { margin: 2rem 0; } figure img { max-width: 100%; } }
nav, aside { display: flex; gap: 1rem; flex-wrap: wrap; }
table { border-collapse: collapse; td, th { border: 1px solid $ink; padding: .5rem; } }
''')
    write(root, "static/assets/main.css", '/* static CSS */ .loaded { opacity: 1; }\n')
    write(root, "static/assets/main.js", '/* static JS */ document.documentElement.classList.add("loaded");\n')
    for asset in ASSETS.glob("*.webp"):
        target = root / "static/media" / asset.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(asset, target)
    for i in range(pages):
        write(root, f"content/articles/page-{i:05}.md", page_text(i))
    # A few true bundles exercise colocated asset copying without duplicating media 10k times.
    for i in range(min(4, pages)):
        source = root / f"content/articles/page-{i:05}.md"
        bundle = source.with_suffix("")
        bundle.mkdir()
        source.rename(bundle / "index.md")
        shutil.copyfile(ASSETS / "logbook.webp", bundle / "source.webp")
        write(root, f"content/articles/page-{i:05}/caption.txt", f"Source material for record {i}.\n")


MUTATIONS = ("add", "edit", "delete", "rename", "sass", "template", "asset", "media", "shortcode", "config")


def mutate(root, scenario, pages):
    """Apply each scenario once in order; no links point to the removed/renamed page."""
    if scenario == "add":
        write(root, "content/articles/added.md", page_text(pages + 1))
    elif scenario == "edit":
        target = root / "content/articles/page-00004.md"
        text = target.read_text().replace('"tag-4"', '"changed-tag"').replace("engineering article", "edited engineering article")
        target.write_text(text + "\n## Edited record\n\nAn additional paragraph changes the search index and rendered page.\n")
    elif scenario == "delete":
        (root / "content/articles/page-00005.md").unlink()
    elif scenario == "rename":
        (root / "content/articles/page-00006.md").rename(root / "content/articles/renamed-record.md")
    elif scenario == "sass":
        write(root, "sass/_palette.scss", '$ink: #102030; $paper: #f4f0e8; $accent: #a02040;\n')
    elif scenario == "template":
        target = root / "templates/base.html"
        target.write_text(target.read_text().replace("Deterministic release workload", "Updated release workload"))
    elif scenario == "asset":
        write(root, "static/assets/main.js", 'document.documentElement.classList.add("updated");\n')
    elif scenario == "media":
        shutil.copyfile(ASSETS / "logbook.webp", root / "static/media/terminal.webp")
    elif scenario == "shortcode":
        target = root / "templates/components.html"
        target.write_text(target.read_text().replace("field journal", "changed annotation template"))
    elif scenario == "config":
        target = root / "config.toml"
        target.write_text(target.read_text().replace("https://release.example.com", "https://changed.example.com"))
    else:
        raise ValueError(f"unknown mutation: {scenario}")
