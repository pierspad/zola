"""Synthetic Unicode corpus; language labels identify scripts, not real translations."""
from fixtures import generate, page_text, write

VERSION = 2
LANGUAGES = (
    ('en', 'Café naïve façade résumé', False),
    ('it', 'Città perché più già', False),
    ('fr', 'Été cœur français forêt', False),
    ('de', 'Größe Straße übermäßig', False),
    ('es', 'Mañana pingüino corazón', False),
    ('pt', 'Ação coração português', False),
    ('ru', 'Наблюдение журнал проверка', False),
    ('el', 'Παρατήρηση ημερολόγιο δοκιμή', False),
    ('ar', 'ملاحظة دفتر تجربة العربية', True),
    ('he', 'תצפית יומן בדיקה עברית', True),
    ('hi', 'अवलोकन दैनिकी परीक्षण हिन्दी', False),
    ('bn', 'পর্যবেক্ষণ দিনলিপি পরীক্ষা বাংলা', False),
    ('zh', '观察日志测试中文', False),
    ('ja', '観察記録テスト日本語', False),
    ('ko', '관찰 기록 시험 한국어', False),
)
TAXONOMIES = 'taxonomies = [{name="tags", paginate_by=20, feed=true}, {name="categories", paginate_by=20, feed=true}]\n'


def suffix(lang):
    return '' if lang == 'en' else '.' + lang


def article(root, i, lang, marker, summary=False):
    text = page_text(i).replace('@/articles/_index.md', '@/articles/_index' + suffix(lang) + '.md')
    text = text.replace(f'title = "Page {i:05}:', f'title = "{marker} Page {i:05}:')
    # Repeat synthetic script text throughout the long-form body, including headings.
    text = text.replace('## Observation', f'## {marker} Observation')
    text = text.replace('A repeatable observation', marker + ' A repeatable observation')
    if summary:
        text = text.replace("\n\n![Historical logbook]", "\n\n<!-- more -->\n\n![Historical logbook]", 1)
    write(root, f'content/articles/page-{i:05}{suffix(lang)}.md', text)


def generate_multilingual(root, articles, count, profile="stress", feed_limit=50):
    languages = LANGUAGES[:count]
    generate(root, 0)
    config = root / 'config.toml'
    text = config.read_text()
    # default_language belongs in the TOML root, before any tables.
    text = 'default_language = "en"\n' + text
    for lang, _, _ in languages[1:]:
        text += f'\n[languages.{lang}]\ntitle = "Synthetic journal {lang}"\nbuild_search_index = true\ngenerate_feeds = true\nfeed_filenames = ["atom.xml", "rss.xml"]\n' + TAXONOMIES
    if profile == "newspaper":
        text = f"feed_limit = {feed_limit}\n" + text
    config.write_text(text)
    for lang, marker, rtl in languages:
        for stem in ('_index', 'articles/_index'):
            original = root / f'content/{stem}.md'
            text = original.read_text().replace('title = "', f'title = "{marker} ')
            write(root, f'content/{stem}{suffix(lang)}.md', text)
        for i in range(articles):
            article(root, i, lang, marker, summary=profile == "newspaper")
    base = root / 'templates/base.html'
    text = base.read_text().replace('<html lang="en" dir="ltr">', '<html lang="{{ lang }}" dir="{% if lang == "ar" or lang == "he" %}rtl{% else %}ltr{% endif %}">')
    text = text.replace('<main>', '''<nav class="translations">{% if page is defined %}{% for translation in page.translations %}<a hreflang="{{ translation.lang }}" href="{{ translation.permalink }}">{{ translation.lang }}</a>{% endfor %}{% endif %}</nav><main>''')
    text = text.replace('href="/"', 'href="{{ get_url(path="/", lang=lang) }}"')
    for path in ('articles', 'tags', 'categories'):
        text = text.replace(f'href="/{path}/"', f'href="{{{{ get_url(path="{path}/", lang=lang) }}}}"')
    base.write_text(text)
    index = root / 'templates/index.html'
    index.write_text(index.read_text().replace('get_section(path="articles/_index.md")', 'get_section(path="articles/_index.md", lang=lang)'))
    return languages


def mutate_multilingual(root, scenario, articles, languages, summary=False):
    lang, marker, _ = languages[-1]
    if scenario == 'new_translation':
        article(root, articles, 'en', LANGUAGES[0][1], summary)
        # The default article was seeded before cache priming; add its final-language sibling.
        article(root, articles, lang, marker, summary)
    elif scenario == 'new_article_all_languages':
        for code, token, _ in languages:
            article(root, articles + 1, code, token, summary)
    elif scenario == 'edit_translation':
        path = root / f'content/articles/page-00004{suffix(lang)}.md'
        path.write_text(path.read_text().replace('Page 00004:', 'Edited 00004:').replace('"tag-4"', '"changed-tag"') + '\n\n## Unicode edit\n\n' + marker + ' updated.\n')
    elif scenario == 'delete_translation':
        (root / f'content/articles/page-00005{suffix(lang)}.md').unlink()
    elif scenario == 'rename_translation':
        path = root / f'content/articles/page-00006{suffix(lang)}.md'
        path.rename(path.with_name('renamed-record' + suffix(lang) + '.md'))
    else:
        raise ValueError(scenario)
