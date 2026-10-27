use core::time;
use std::path::Path;
use std::{cmp, collections::HashMap, thread};

use config::LinkCheckerLevel;
use globset::GlobSet;
use log;
use rayon::prelude::*;

use crate::Site;
use errors::{Result, bail};
use rayon;
use url::Url;
use utils::anchors::is_special_anchor;

/// Check whether all internal links pointing to explicit anchor fragments are valid.
///
/// This is very similar to `check_external_links`, although internal links checking
/// is always performed (while external ones only conditionally in `zola check`).  If broken links
/// are encountered, the `internal_level` setting in config.toml will determine whether they are
/// treated as warnings or errors.
pub fn check_internal_links_with_anchors(site: &Site) -> Vec<String> {
    log::info!("Checking all internal links with anchors.");

    // Chain all internal links, from both sections and pages.
    let page_links = site
        .library
        .pages
        .values()
        .flat_map(|p| p.internal_links.iter().map(move |l| (&p.file.path, l)));
    let section_links = site
        .library
        .sections
        .values()
        .flat_map(|p| p.internal_links.iter().map(move |l| (&p.file.path, l)));
    let all_links = page_links.chain(section_links);

    // Group links by target markdown file and anchor:
    // md_path -> (anchor -> Vec<page_path>)
    let mut targets_by_file: HashMap<&str, HashMap<&str, Vec<&Path>>> = HashMap::new();
    let mut anchors_total = 0;

    for (page_path, link) in all_links {
        if let (md_path, Some(anchor)) = link
            && !is_special_anchor(anchor)
        {
            anchors_total += 1;
            targets_by_file
                .entry(md_path.as_str())
                .or_default()
                .entry(anchor.as_str())
                .or_default()
                .push(page_path.as_path());
        }
    }

    let content_dir = site.base_path.join("content");

    // Check for targets existence (including anchors), then keep only the faulty
    // entries for error reporting purposes.
    // Target files and anchors are checked once, even when referenced by many pages.
    let missing_targets: Vec<(&Path, &str, &str)> = targets_by_file
        .par_iter()
        .flat_map(|(md_path, anchors)| {
            // There are a few `expect` here since the presence of the .md file will
            // already have been checked in the markdown rendering
            let mut full_path = content_dir.clone();
            for part in md_path.split('/') {
                full_path.push(part);
            }

            let mut faulty = Vec::new();
            // NOTE: This will also match _index.foobar.md where foobar is not a language
            // as well as any other string containing "_index." which is now referenced as
            // unsupported page path in the docs.
            if md_path.contains("_index.") {
                let section = site.library.sections.get(&full_path).unwrap_or_else(|| {
                    let first_page = anchors.values().next().and_then(|v| v.first()).unwrap();
                    panic!(
                        "Couldn't find section {} in check_internal_links_with_anchors from page {:?}",
                        md_path,
                        first_page.strip_prefix(&site.base_path).unwrap()
                    )
                });
                for (&anchor, pages) in anchors {
                    if !section.has_anchor(anchor) {
                        for page_path in pages {
                            faulty.push((*page_path, *md_path, anchor));
                        }
                    }
                }
            } else {
                let page = site.library.pages.get(&full_path).unwrap_or_else(|| {
                    let first_page = anchors.values().next().and_then(|v| v.first()).unwrap();
                    panic!(
                        "Couldn't find page {} in check_internal_links_with_anchors from page {:?}",
                        md_path,
                        first_page.strip_prefix(&site.base_path).unwrap()
                    )
                });
                for (&anchor, pages) in anchors {
                    if !(page.has_anchor(anchor) || page.has_anchor_id(anchor)) {
                        for page_path in pages {
                            faulty.push((*page_path, *md_path, anchor));
                        }
                    }
                }
            }
            faulty
        })
        .collect();

    // Format faulty entries into error messages, and collect them.
    let mut messages = missing_targets
        .into_iter()
        .map(|(page_path, md_path, anchor)| {
            format!(
                "The anchor in the link `@/{}#{}` in {} does not exist.",
                md_path,
                anchor,
                page_path.to_string_lossy(),
            )
        })
        .collect::<Vec<_>>();
    messages.sort_by(|a, b| b.cmp(a));

    // Finally emit a summary, and return overall anchors-checking result.
    if messages.is_empty() {
        log::info!("> Successfully checked {} internal link(s) with anchors.", anchors_total);
    } else {
        log::warn!(
            "> Checked {} internal link(s) with anchors: {} target(s) missing.",
            anchors_total,
            messages.len(),
        );
    }
    messages
}

fn should_skip_by_prefix(link: &str, skip_prefixes: &[String]) -> bool {
    skip_prefixes.iter().any(|prefix| link.starts_with(prefix))
}

fn should_skip_by_file(file_path: &Path, glob_set: &GlobSet) -> bool {
    glob_set.is_match(file_path)
}

fn get_link_domain(link: &str) -> Result<String> {
    match Url::parse(link) {
        Ok(url) => match url.host_str().map(String::from) {
            Some(domain_str) => Ok(domain_str),
            None => bail!("could not parse domain `{}` from link", link),
        },
        Err(err) => bail!("could not parse domain `{}` from link: `{}`", link, err),
    }
}

/// Checks all external links and returns all the errors that were encountered.
/// Empty vec == all good
pub fn check_external_links(site: &Site) -> Vec<String> {
    let mut messages: Vec<String> = vec![];
    let mut skipped_link_count: u32 = 0;
    let mut invalid_url_links: u32 = 0;

    // Group external links by domain and unique URL:
    // domain -> (external_link -> Vec<referring_file_path>)
    let mut links_by_domain: HashMap<String, HashMap<&str, Vec<&Path>>> = HashMap::new();

    // First we look at all the external links, skip those the user wants to skip and record
    // the ones that have invalid URLs
    let ignored_files_globset = site.config.link_checker.ignored_files_globset.as_ref().unwrap();

    let page_links = site.library.pages.values().map(|p| (&p.file.path, &p.external_links));
    let section_links = site.library.sections.values().map(|s| (&s.file.path, &s.external_links));

    for (file_path, links) in page_links.chain(section_links) {
        for link in links {
            if should_skip_by_prefix(link, &site.config.link_checker.skip_prefixes)
                || should_skip_by_file(file_path, ignored_files_globset)
            {
                skipped_link_count += 1;
            } else {
                match get_link_domain(link) {
                    Ok(domain) => {
                        links_by_domain
                            .entry(domain)
                            .or_default()
                            .entry(link.as_str())
                            .or_default()
                            .push(file_path.as_path());
                    }
                    Err(err) => {
                        // We could use the messages.len() to keep track of them for below
                        // but it's more explicit this way
                        invalid_url_links += 1;
                        messages.push(err.to_string());
                    }
                }
            }
        }
    }

    let unique_links_count: usize = links_by_domain.values().map(|urls| urls.len()).sum();

    log::info!(
        "Checking {} external link(s). Skipping {} external link(s).{}",
        unique_links_count,
        skipped_link_count,
        if invalid_url_links == 0 {
            "".to_string()
        } else {
            format!(" {} link(s) had unparseable URLs.", invalid_url_links)
        }
    );

    // error out if we're in error mode and any external URLs couldn't be parsed
    if site.config.link_checker.external_level == LinkCheckerLevel::Error && !messages.is_empty() {
        return messages;
    }

    if links_by_domain.is_empty() {
        return messages;
    }

    let cpu_count = match thread::available_parallelism() {
        Ok(count) => count.get(),
        Err(_) => 1,
    };
    // create thread pool with lots of threads so we can fetch
    // (almost) all pages simultaneously, limiting all links for a single
    // domain to one thread to avoid rate-limiting
    let num_threads = cmp::min(links_by_domain.len(), cmp::max(8, cpu_count));
    match rayon::ThreadPoolBuilder::new().num_threads(num_threads).build() {
        Ok(pool) => {
            let errors = pool.install(|| {
                links_by_domain
                    .par_iter()
                    .map(|(_, urls)| {
                        let mut num_urls_left = urls.len();
                        urls.iter()
                            .filter_map(move |(&external_link, referring_pages)| {
                                num_urls_left -= 1;

                                let res = link_checker::check_url(
                                    external_link,
                                    &site.config.link_checker,
                                );

                                if num_urls_left > 0 {
                                    // Prevent rate-limiting, wait before next crawl unless we're done with this domain
                                    thread::sleep(time::Duration::from_millis(500));
                                }

                                if link_checker::is_valid(&res) {
                                    None
                                } else {
                                    Some(referring_pages.iter().map(move |file_path| {
                                        (*file_path, external_link, res.clone())
                                    }))
                                }
                            })
                            .flatten()
                            .collect::<Vec<_>>()
                    })
                    .flatten()
                    .collect::<Vec<_>>()
            });

            log::info!(
                "> Checked {} external link(s): {} error(s) found.",
                unique_links_count,
                errors.len()
            );

            for (page_path, link, check_res) in errors {
                messages.push(format!(
                    "Broken link in {} to {} : {}",
                    page_path.to_string_lossy(),
                    link,
                    link_checker::message(&check_res)
                ));
            }
        }
        Err(pool_err) => messages.push(pool_err.to_string()),
    }

    messages
}
