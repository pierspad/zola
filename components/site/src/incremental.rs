//! Persistent reuse of pure rendering work; malformed cache entries are misses.
use crate::Site;
use content::Page;
use errors::Result;
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::io::{BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{LazyLock, Mutex};
use utils::{table_of_contents::Heading, types::InsertAnchor};
use walkdir::WalkDir;

const HEX_DIGITS: &[u8; 16] = b"0123456789abcdef";
const FALLBACK_MEMORY_LIMIT_BYTES: usize = 256 * 1024 * 1024;
const MIN_AUTO_MEMORY_LIMIT_BYTES: u64 = 16 * 1024 * 1024;

fn hex_encode(bytes: &[u8]) -> String {
    let mut out = Vec::with_capacity(bytes.len() * 2);
    for &b in bytes {
        out.push(HEX_DIGITS[(b >> 4) as usize]);
        out.push(HEX_DIGITS[(b & 0x0f) as usize]);
    }
    String::from_utf8(out).expect("hex digits are valid ASCII")
}

fn digest(bytes: impl AsRef<[u8]>) -> String {
    hex_encode(&Sha256::digest(bytes.as_ref()))
}

fn file_digest(path: &Path) -> std::io::Result<String> {
    let mut reader = BufReader::new(fs_err::File::open(path)?);
    let mut hash = Sha256::new();
    let mut buffer = [0; 64 * 1024];
    loop {
        let n = reader.read(&mut buffer)?;
        if n == 0 {
            break;
        }
        hash.update(&buffer[..n]);
    }
    Ok(hex_encode(&hash.finalize()))
}

pub(crate) fn default_memory_limit_bytes() -> usize {
    detect_memory_limit_bytes().unwrap_or(FALLBACK_MEMORY_LIMIT_BYTES)
}

#[cfg(target_os = "linux")]
fn detect_memory_limit_bytes() -> Option<usize> {
    let meminfo = std::fs::read_to_string("/proc/meminfo").ok();
    let cgroup = std::fs::read_to_string("/proc/self/cgroup").ok();
    let mountinfo = std::fs::read_to_string("/proc/self/mountinfo").ok();
    select_linux_memory_limit_bytes(
        meminfo.as_deref(),
        cgroup.as_deref(),
        mountinfo.as_deref(),
        Path::new("/sys/fs/cgroup"),
    )
}

#[cfg(not(target_os = "linux"))]
fn detect_memory_limit_bytes() -> Option<usize> {
    None
}

#[cfg(any(target_os = "linux", test))]
fn read_cgroup_int(path: &Path) -> Option<u64> {
    let value: u64 = std::fs::read_to_string(path).ok()?.trim().parse().ok()?;
    (value < (1u64 << 60)).then_some(value)
}

#[cfg(any(target_os = "linux", test))]
fn select_linux_memory_limit_bytes(
    meminfo: Option<&str>,
    cgroup_entries: Option<&str>,
    mountinfo: Option<&str>,
    cgroup_root: &Path,
) -> Option<usize> {
    let mut limits: Vec<u64> = Vec::new();
    if let Some(text) = meminfo {
        for line in text.lines() {
            let Some((key, rest)) = line.split_once(':') else {
                continue;
            };
            let Some(kib) = rest.split_whitespace().next().and_then(|v| v.parse::<u64>().ok())
            else {
                continue;
            };
            let bytes = kib.saturating_mul(1024);
            match key.trim() {
                "MemTotal" => limits.push(bytes / 4),
                "MemAvailable" => limits.push(bytes / 2),
                _ => {}
            }
        }
    }
    if let (Some(entries), Some(mounts)) = (cgroup_entries, mountinfo) {
        let mut remaining_values = Vec::new();
        for entry in entries.lines() {
            let mut parts = entry.splitn(3, ':');
            let (_id, Some(controllers), Some(group)) = (parts.next(), parts.next(), parts.next())
            else {
                continue;
            };
            let v2 = controllers.is_empty();
            if !v2 && !controllers.split(',').any(|c| c == "memory") {
                continue;
            }
            for mount in mounts.lines() {
                let Some((before, after)) = mount.split_once(" - ") else {
                    continue;
                };
                let before_fields: Vec<&str> = before.split_whitespace().collect();
                let after_fields: Vec<&str> = after.split_whitespace().collect();
                if before_fields.len() < 5 || after_fields.len() < 3 {
                    continue;
                }
                let fs_type = after_fields[0];
                let fs_opts = after_fields[2];
                let matches_fs = if v2 {
                    fs_type == "cgroup2"
                } else {
                    fs_type == "cgroup" && fs_opts.split(',').any(|o| o == "memory")
                };
                if !matches_fs {
                    continue;
                }
                let mount_root = Path::new(before_fields[3]);
                let mount_point = Path::new(before_fields[4]);
                let Ok(relative) = Path::new(group).strip_prefix(mount_root) else {
                    continue;
                };
                let Ok(mount_rel) = mount_point.strip_prefix("/sys/fs/cgroup") else {
                    continue;
                };
                let base = if mount_rel.as_os_str().is_empty() {
                    cgroup_root.to_path_buf()
                } else {
                    cgroup_root.join(mount_rel)
                };
                let mut current = if relative.as_os_str().is_empty() {
                    base.clone()
                } else {
                    base.join(relative)
                };
                loop {
                    let (max_name, cur_name) = if v2 {
                        ("memory.max", "memory.current")
                    } else {
                        ("memory.limit_in_bytes", "memory.usage_in_bytes")
                    };
                    if let (Some(limit), Some(used)) = (
                        read_cgroup_int(&current.join(max_name)),
                        read_cgroup_int(&current.join(cur_name)),
                    ) {
                        remaining_values.push(limit.saturating_sub(used));
                    }
                    if current == base || !current.pop() {
                        break;
                    }
                }
            }
        }
        if let Some(min_remaining) = remaining_values.into_iter().min() {
            limits.push(min_remaining / 2);
        }
    }
    let chosen = limits.into_iter().min()?.max(MIN_AUTO_MEMORY_LIMIT_BYTES);
    usize::try_from(chosen).ok().or(Some(usize::MAX))
}
fn stable_bytes(value: &impl Serialize) -> serde_json::Result<Vec<u8>> {
    // Tera maps use randomized hashing. Normalize through JSON's ordered map.
    serde_json::to_vec(&serde_json::to_value(value)?)
}
#[derive(Debug, Clone, Serialize, Deserialize)]
struct Entry {
    content: String,
    summary: Option<String>,
    toc: Vec<Heading>,
    internal_links: Vec<(String, Option<String>)>,
    external_links: Vec<String>,
    links: Vec<(String, Option<String>)>,
    images: Vec<(PathBuf, Option<String>)>,
}
#[derive(Debug, Default, Serialize, Deserialize)]
struct Entries {
    markdown: HashMap<String, Entry>,
    html: HashMap<String, String>,
}
#[derive(Debug)]
pub(crate) struct MarkdownCache {
    path: PathBuf,
    fingerprint: String,
    entries: Mutex<Entries>,
    used: Mutex<Entries>,
    pure_templates: HashSet<String>,
    default_summary_template: bool,
    markdown_hits: AtomicUsize,
    html_hits: AtomicUsize,
    memory_limit: usize,
    retained_bytes: AtomicUsize,
    image_fingerprints: Mutex<HashMap<PathBuf, Option<String>>>,
}
impl MarkdownCache {
    pub fn open(site: &Site, config_dir: &std::path::Path, memory_limit: usize) -> Result<Self> {
        let mut inputs = BTreeMap::new();
        inputs.insert("engine".into(), file_digest(&std::env::current_exe()?)?.into_bytes());
        inputs.insert(
            "version".to_owned(),
            concat!("render-v2-", env!("CARGO_PKG_VERSION")).as_bytes().to_vec(),
        );
        inputs.insert("markdown".into(), stable_bytes(&site.config.markdown)?);
        inputs.insert("slugify".into(), stable_bytes(&site.config.slugify)?);
        inputs.insert("link_checker".into(), stable_bytes(&site.config.link_checker)?);
        inputs.insert("base_url".into(), site.config.base_url.as_bytes().to_vec());
        inputs.insert("language".into(), site.config.default_language.as_bytes().to_vec());
        let mut sources = BTreeMap::new();
        // Markdown reads local image dimensions, so include asset bytes, not mtimes.
        let mut roots =
            vec![site.content_path.clone(), site.static_path.clone(), site.templates_path.clone()];
        let theme_dir = site.config.theme.as_ref().map(|t| site.base_path.join("themes").join(t));
        let theme_templates = theme_dir.as_ref().map(|d| d.join("templates"));
        let theme_icons = theme_dir.as_ref().map(|d| d.join("icons"));
        if let Some(ref td) = theme_dir {
            roots.push(td.clone());
        }
        if let Some(h) = &site.config.markdown.highlighting {
            for path in h.extra_grammars.iter().chain(&h.extra_themes) {
                let path = config_dir.join(path);
                inputs
                    .insert(path.to_string_lossy().into_owned(), file_digest(&path)?.into_bytes());
            }
        }
        let mut asset_paths = Vec::new();
        for root in roots {
            if !root.exists() {
                continue;
            }
            for entry in WalkDir::new(&root).follow_links(true).into_iter().filter_entry(|e| {
                if e.file_name() == ".git" {
                    return false;
                }
                if let Some(ref icons) = theme_icons
                    && e.path() == icons
                {
                    return false;
                }
                true
            }) {
                let entry = entry?;
                if !entry.file_type().is_file() {
                    continue;
                }
                let entry_path = entry.path();
                if entry_path.extension().is_some_and(|e| e == "md") {
                    let mut prefix = [0; 3];
                    let count = fs_err::File::open(entry_path)?.read(&mut prefix)?;
                    // Actual Markdown sources are separately keyed. A binary image
                    // named *.md must still participate in asset invalidation.
                    if count == 3 && (prefix == *b"+++" || prefix == *b"---") {
                        continue;
                    }
                }
                let relative = entry_path.strip_prefix(&site.templates_path).ok().or_else(|| {
                    theme_templates.as_ref().and_then(|p| entry_path.strip_prefix(p).ok())
                });
                if let Some(relative) = relative {
                    match fs_err::read_to_string(entry_path) {
                        Ok(source) => {
                            let name = relative.to_string_lossy().replace('\\', "/");
                            inputs.insert(
                                entry_path.to_string_lossy().into_owned(),
                                digest(source.as_bytes()).into_bytes(),
                            );
                            if entry_path.starts_with(&site.templates_path)
                                || !sources.contains_key(&name)
                            {
                                sources.insert(name, source);
                            }
                            continue;
                        }
                        Err(err) if err.kind() == std::io::ErrorKind::InvalidData => {}
                        Err(err) => return Err(err.into()),
                    }
                }
                asset_paths.push(entry_path.to_path_buf());
            }
        }
        let asset_digests: Vec<(String, Vec<u8>)> = asset_paths
            .par_iter()
            .map(|entry_path| {
                let hash = file_digest(entry_path)?;
                Ok((entry_path.to_string_lossy().into_owned(), hash.into_bytes()))
            })
            .collect::<std::io::Result<Vec<_>>>()?;
        for (entry_path, hash) in asset_digests {
            inputs.insert(entry_path, hash);
        }
        let pure_templates = sources
            .keys()
            .filter(|n| pure_template(n, &sources, &mut HashSet::new()))
            .cloned()
            .collect();
        let fingerprint = digest(stable_bytes(&inputs)?);
        let path = site.base_path.join(".zola-cache").join("render-v2.json");
        // A conservative allowance includes deserialization overhead. Oversized
        // files are misses before allocating their contents.
        let entries: Entries = fs_err::metadata(&path)
            .ok()
            .filter(|m| m.len() <= (memory_limit / 8) as u64)
            .and_then(|_| fs_err::File::open(&path).ok())
            .and_then(|f| serde_json::from_reader(BufReader::new(f)).ok())
            .unwrap_or_default();
        let retained_bytes = entries_charge(&entries);
        let entries = if retained_bytes <= memory_limit { entries } else { Entries::default() };
        let retained_bytes = entries_charge(&entries);
        Ok(Self {
            memory_limit,
            retained_bytes: AtomicUsize::new(retained_bytes),
            path,
            fingerprint,
            entries: Mutex::new(entries),
            used: Mutex::new(Entries::default()),
            default_summary_template: !sources.contains_key("summary-cutoff.html"),
            pure_templates,
            markdown_hits: AtomicUsize::new(0),
            html_hits: AtomicUsize::new(0),
            image_fingerprints: Mutex::new(HashMap::new()),
        })
    }
    pub fn key(&self, page: &Page, anchor: InsertAnchor) -> Option<String> {
        // Tera content, heading templates and summary templates can read arbitrary
        // data or enqueue image operations. Always execute those normally.
        let has_summary = page.raw_content.contains("<!-- more -->");
        // Only the native marker is safe. Custom cutoff templates can execute
        // arbitrary functions; all other comments retain the conservative miss.
        if ["{{", "{%", "{#"].iter().any(|s| page.raw_content.contains(s))
            || page.raw_content.replace("<!-- more -->", "").contains("<!--")
            || (has_summary && !self.default_summary_template)
            || anchor.uses_template()
        {
            return None;
        }
        let assets: BTreeMap<_, _> = page.colocated_assets.iter().collect();
        Some(digest(
            stable_bytes(&(
                &self.fingerprint,
                &page.raw_content,
                &page.file.relative,
                &page.permalink,
                &page.lang,
                anchor,
                assets,
            ))
            .ok()?,
        ))
    }
    fn image_fingerprint(&self, path: &PathBuf) -> Option<String> {
        let mut fingerprints = self.image_fingerprints.lock().unwrap();
        fingerprints.entry(path.clone()).or_insert_with(|| file_digest(path).ok()).clone()
    }
    pub fn restore(
        &self,
        key: &str,
        page: &mut Page,
        permalinks: &HashMap<String, String>,
    ) -> bool {
        let mut entries = self.entries.lock().unwrap();
        let Some(entry) = entries.markdown.get(key) else {
            return false;
        };
        if entry.links.iter().any(|(p, u)| permalinks.get(p) != u.as_ref()) {
            return false;
        }
        if entry.images.iter().any(|(path, fingerprint)| {
            self.image_fingerprint(path) != *fingerprint
                || (fingerprint.is_none() && !matches!(path.try_exists(), Ok(false)))
        }) {
            return false;
        }
        self.markdown_hits.fetch_add(1, Ordering::Relaxed);
        page.content.clone_from(&entry.content);
        page.summary.clone_from(&entry.summary);
        page.toc.clone_from(&entry.toc);
        page.internal_links.clone_from(&entry.internal_links);
        page.external_links.clone_from(&entry.external_links);
        page.permalink_dependencies.clone_from(&entry.links);
        page.image_dependencies = entry.images.iter().map(|(path, _)| path.clone()).collect();
        page.raw_content.clear();
        let entry = entries.markdown.remove(key).unwrap();
        self.used.lock().unwrap().markdown.insert(key.to_owned(), entry);
        true
    }
    pub fn insert(&self, key: String, page: &Page, permalinks: &HashMap<String, String>) {
        if page.permalink_dependencies.iter().any(|(_, url)| url.is_none()) {
            return;
        }
        let mut dependencies: Vec<_> =
            page.permalink_dependencies.iter().map(|(p, _)| p.clone()).collect();
        if let Some(stem) = page.file.relative.strip_suffix(&format!(".{}.md", page.lang)) {
            dependencies.push(format!("{stem}.md"));
        }
        let entry = Entry {
            content: page.content.clone(),
            summary: page.summary.clone(),
            toc: page.toc.clone(),
            internal_links: page.internal_links.clone(),
            external_links: page.external_links.clone(),
            images: page
                .image_dependencies
                .iter()
                .map(|path| (path.clone(), self.image_fingerprint(path)))
                .collect(),
            links: dependencies
                .into_iter()
                .map(|p| {
                    let url = permalinks.get(&p).cloned();
                    (p, url)
                })
                .collect(),
        };
        if self.reserve(entry_charge(&key, &entry)) {
            self.used.lock().unwrap().markdown.insert(key, entry);
        }
    }
    fn reserve(&self, bytes: usize) -> bool {
        reserve_bytes(&self.retained_bytes, self.memory_limit, bytes)
    }
    pub fn html_key(&self, site: &Site, page: &Page) -> Option<String> {
        let template = page.meta.template.as_deref().unwrap_or("page.html");
        if !self.pure_templates.contains(template) {
            return None;
        }
        Some(digest(
            stable_bytes(&(
                &self.fingerprint,
                template,
                &site.cache.pages.get(&page.file.path)?.value,
                &site.cache.configs.get(&page.lang)?,
                &page.permalink,
                &page.path,
                &page.lang,
            ))
            .ok()?,
        ))
    }
    pub fn html(&self, key: &str) -> Option<String> {
        let content = self.entries.lock().unwrap().html.remove(key)?;
        self.html_hits.fetch_add(1, Ordering::Relaxed);
        self.used.lock().unwrap().html.insert(key.to_owned(), content.clone());
        Some(content)
    }
    pub fn insert_html(&self, key: String, content: String) {
        if self.reserve(entry_charge(&key, &content)) {
            self.used.lock().unwrap().html.insert(key, content);
        }
    }
    pub fn save(&self) {
        log::info!(
            "Incremental cache: reused {} Markdown renders and {} page HTML renders",
            self.markdown_hits.load(Ordering::Relaxed),
            self.html_hits.load(Ordering::Relaxed)
        );
        log::info!(
            "Incremental cache: estimated retained bytes {} / {}",
            self.retained_bytes.load(Ordering::Relaxed),
            self.memory_limit
        );
        let result = (|| -> Result<()> {
            fs_err::create_dir_all(self.path.parent().unwrap())?;
            let temporary = self.path.with_extension(format!("{}.tmp", std::process::id()));
            let mut writer = BufWriter::new(fs_err::File::create(&temporary)?);
            serde_json::to_writer(&mut writer, &*self.used.lock().unwrap())?;
            writer.flush()?;
            fs_err::rename(temporary, &self.path)?;
            Ok(())
        })();
        if let Err(e) = result {
            log::warn!("Could not save incremental cache: {e}");
        }
    }
}
fn reserve_bytes(retained: &AtomicUsize, limit: usize, bytes: usize) -> bool {
    let mut used = retained.load(Ordering::Relaxed);
    loop {
        let Some(total) = used.checked_add(bytes).filter(|total| *total <= limit) else {
            return false;
        };
        match retained.compare_exchange_weak(used, total, Ordering::Relaxed, Ordering::Relaxed) {
            Ok(_) => return true,
            Err(actual) => used = actual,
        }
    }
}
fn entry_charge(key: &str, value: &impl Serialize) -> usize {
    // Include serialized map keys/framing in the same eight-times allowance as
    // values, so an admitted partial cache also passes the next file preflight.
    cache_charge(value).saturating_add(cache_charge(&key)).saturating_add(512)
}
fn entries_charge(entries: &Entries) -> usize {
    entries
        .markdown
        .iter()
        .map(|(key, value)| entry_charge(key, value))
        .chain(entries.html.iter().map(|(key, value)| entry_charge(key, value)))
        .fold(0usize, usize::saturating_add)
}
// Count without constructing a second JSON buffer. Eight times wire bytes
// covers owned strings, vectors, map slots and allocator overhead conservatively;
// this is an estimate, not an operating-system RSS limit.
fn cache_charge(value: &impl Serialize) -> usize {
    struct Counter(usize);
    impl Write for Counter {
        fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
            self.0 = self.0.saturating_add(bytes.len());
            Ok(bytes.len())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }
    let mut count = Counter(0);
    if serde_json::to_writer(&mut count, value).is_err() {
        return usize::MAX;
    }
    count.0.saturating_mul(8)
}
static TAG_RE: LazyLock<regex::Regex> =
    LazyLock::new(|| regex::Regex::new(r"(?s)\{\{(.*?)\}\}|\{%(.*?)%\}").unwrap());
static FILTER_RE: LazyLock<regex::Regex> =
    LazyLock::new(|| regex::Regex::new(r"\|\s*([a-zA-Z_][a-zA-Z_0-9]*)").unwrap());
static DEPENDENCY_RE: LazyLock<regex::Regex> = LazyLock::new(|| {
    regex::Regex::new(r#"^\s*(?:extends|include)\s+["']([^"']+)["']\s*$"#).unwrap()
});

// Closed template subset. No calls, unknown filters/tests/tags, dynamic includes,
// components or implicit external dependencies. Inspect inheritance recursively.
fn pure_template(
    name: &str,
    sources: &BTreeMap<String, String>,
    visiting: &mut HashSet<String>,
) -> bool {
    if !visiting.insert(name.to_owned()) {
        return false;
    }
    let Some(source) = sources.get(name) else {
        return false;
    };
    let tags = &*TAG_RE;
    let filter = &*FILTER_RE;
    let dependency = &*DEPENDENCY_RE;
    for capture in tags.captures_iter(source) {
        let expression = capture
            .get(1)
            .or_else(|| capture.get(2))
            .unwrap()
            .as_str()
            .trim()
            .trim_matches('-')
            .trim();
        if expression.contains('(')
            || expression.split_whitespace().any(|word| word == "is")
            || expression.contains("::")
        {
            return false;
        }
        // Quoted delimiters would require a full lexer to identify tag boundaries.
        // Only static dependency declarations can contain quoted strings.
        if (expression.contains('\'') || expression.contains('"'))
            && !dependency.is_match(expression)
        {
            return false;
        }
        for f in filter.captures_iter(expression) {
            if ![
                "safe",
                "escape",
                "escape_xml",
                "length",
                "upper",
                "lower",
                "capitalize",
                "title",
                "trim",
                "striptags",
                "first",
                "last",
                "reverse",
                "sort",
                "unique",
                "join",
                "json_encode",
                "urlencode",
                "urlencode_strict",
                "linebreaksbr",
                "wordcount",
                "abs",
                "round",
                "int",
                "float",
                "as_str",
            ]
            .contains(&&f[1])
            {
                return false;
            }
        }
        if capture.get(2).is_some() {
            let tag = expression.split_whitespace().next().unwrap_or("");
            if ["extends", "include"].contains(&tag) {
                let Some(d) = dependency.captures(expression) else {
                    return false;
                };
                if !pure_template(&d[1], sources, &mut visiting.clone()) {
                    return false;
                }
            } else if ![
                "block",
                "endblock",
                "if",
                "elif",
                "else",
                "endif",
                "for",
                "endfor",
                "set",
                "set_global",
                "break",
                "continue",
            ]
            .contains(&tag)
            {
                return false;
            }
        }
    }
    true
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn partial_cache_remains_loadable_under_the_same_allowance() {
        let temp = tempfile::tempdir().unwrap();
        std::fs::write(temp.path().join("config.toml"), "base_url='https://example.com'").unwrap();
        std::fs::create_dir_all(temp.path().join("templates")).unwrap();
        let site = Site::new(temp.path(), "config.toml").unwrap();
        let cache = MarkdownCache::open(&site, &site.config_dir, 4096).unwrap();
        for n in 0..8 {
            cache.insert_html(format!("{n:064}"), "x".repeat(200));
        }
        assert_eq!(cache.used.lock().unwrap().html.len(), 1);
        cache.save();
        assert!(std::fs::metadata(&cache.path).unwrap().len() <= 4096 / 8);
        let warm = MarkdownCache::open(&site, &site.config_dir, 4096).unwrap();
        assert_eq!(warm.entries.lock().unwrap().html.len(), 1);
        assert_eq!(warm.html(&format!("{:064}", 0)), Some("x".repeat(200)));
        assert_eq!(warm.html_hits.load(Ordering::Relaxed), 1);
    }
    #[test]
    fn concurrent_admission_stays_within_allowance() {
        let retained = AtomicUsize::new(0);
        std::thread::scope(|scope| {
            for _ in 0..16 {
                let retained = &retained;
                scope.spawn(move || {
                    for _ in 0..1000 {
                        reserve_bytes(retained, 1000, 7);
                    }
                });
            }
        });
        assert_eq!(retained.load(Ordering::Relaxed), 994);
        assert!(!reserve_bytes(&retained, usize::MAX, usize::MAX));
        assert!(reserve_bytes(&retained, 1000, 6));
        assert!(!reserve_bytes(&retained, 1000, 1));
    }
    #[test]
    fn purity_checks_entire_inheritance() {
        let mut sources = BTreeMap::from([
            ("page.html".into(), "{% extends 'base.html' %}{{ page.content | safe }}".into()),
            ("base.html".into(), "{{ config.title }}".into()),
        ]);
        assert!(pure_template("page.html", &sources, &mut HashSet::new()));
        for impure in [
            "{{ resize_image(path='x') }}",
            "{{ page.content | markdown }}",
            "{% include dynamic %}",
            "{{ now() }}",
            "{{ x is custom }}",
            "{% Widget %}",
        ] {
            sources.insert("base.html".into(), impure.into());
            assert!(!pure_template("page.html", &sources, &mut HashSet::new()), "{impure}");
        }
    }
    #[test]
    fn auto_memory_limit_respects_host_and_cgroup() {
        let temp = tempfile::tempdir().unwrap();
        let cg_root = temp.path();
        std::fs::create_dir_all(cg_root.join("runner")).unwrap();
        // 16 GiB total (-> 4 GiB), 10 GiB available (-> 5 GiB), cgroup 2 GiB remaining (-> 1 GiB)
        std::fs::write(cg_root.join("memory.max"), "max\n").unwrap();
        std::fs::write(cg_root.join("memory.current"), "1073741824\n").unwrap();
        std::fs::write(
            cg_root.join("runner/memory.max"),
            format!("{}\n", 3u64 * 1024 * 1024 * 1024),
        )
        .unwrap();
        std::fs::write(
            cg_root.join("runner/memory.current"),
            format!("{}\n", 1024u64 * 1024 * 1024),
        )
        .unwrap();
        let meminfo = "MemTotal:       16777216 kB\nMemAvailable:   10485760 kB\n";
        let cgroup = "0::/runner\n";
        let mountinfo = "1 0 0:1 / /sys/fs/cgroup rw - cgroup2 cgroup2 rw\n";
        let limit =
            select_linux_memory_limit_bytes(Some(meminfo), Some(cgroup), Some(mountinfo), cg_root)
                .unwrap();
        assert_eq!(limit, 1024 * 1024 * 1024);

        // No cgroup limit: uses min(MemTotal/4, MemAvailable/2)
        let host_only =
            select_linux_memory_limit_bytes(Some(meminfo), None, None, cg_root).unwrap();
        assert_eq!(host_only, 4 * 1024 * 1024 * 1024);
    }
}
