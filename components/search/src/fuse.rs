use std::collections::BTreeMap;
use time::format_description::well_known::Rfc3339;

use config::Search;
use content::Library;
use errors::Result;
use rayon::prelude::*;

use crate::{clean_and_truncate_body, collect_index_items, extract_headings};

/// build index in Fuse.js format.
pub fn build_index(lang: &str, library: &Library, config: &Search) -> Result<String> {
    #[derive(serde::Serialize)]
    struct FuseIndexItem<'a> {
        url: &'a str,
        #[serde(skip_serializing_if = "Option::is_none")]
        title: Option<&'a str>,
        #[serde(skip_serializing_if = "Option::is_none")]
        description: Option<&'a str>,
        #[serde(skip_serializing_if = "Option::is_none")]
        body: Option<String>, // AMMONIA.clean has to allocate anyway
        #[serde(skip_serializing_if = "Option::is_none")]
        date: Option<String>,
        #[serde(skip_serializing_if = "Option::is_none")]
        headings: Option<Vec<&'a str>>,
        #[serde(skip_serializing_if = "Option::is_none")]
        taxonomies: Option<&'a BTreeMap<String, Vec<String>>>,
        #[serde(skip_serializing_if = "Option::is_none")]
        path: Option<&'a str>,
    }
    let items = collect_index_items(lang, library);
    let mut index: Vec<FuseIndexItem> = items
        .par_iter()
        .map(|item| FuseIndexItem {
            url: item.url,
            title: match config.include_title {
                true => Some(item.title.as_deref().unwrap_or_default()),
                false => None,
            },
            description: match config.include_description {
                true => Some(item.description.as_deref().unwrap_or_default()),
                false => None,
            },
            body: match config.include_content {
                true => Some(clean_and_truncate_body(config.truncate_content_length, item.content)),
                false => None,
            },
            date: match config.include_date {
                true => item.datetime.as_ref().and_then(|d| d.format(&Rfc3339).ok()),
                false => None,
            },
            headings: match config.include_headings {
                true => Some(extract_headings(item.toc)),
                false => None,
            },
            taxonomies: match config.include_taxonomies {
                true => item.taxonomies.filter(|t| !t.is_empty()),
                false => None,
            },
            path: match config.include_path {
                true => Some(item.path),
                false => None,
            },
        })
        .collect();
    index.sort_by(|a, b| a.url.cmp(b.url));
    Ok(serde_json::to_string(&index)?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use config::Config;
    use content::{Page, Section};
    use std::path::PathBuf;
    use time::OffsetDateTime;
    use utils::table_of_contents::Heading;

    fn create_test_library() -> Library {
        let config = Config::default();
        let mut library = Library::new(&config);

        let mut section = Section::default();
        section.file.path = PathBuf::from("content/_index.md");
        section.permalink = "http://example.com/".to_string();
        section.lang = "en".to_string();
        section.meta.title = Some("Home".to_string());
        section.meta.in_search_index = true;
        section.meta.render = false;

        let mut page = Page::default();
        page.file.path = PathBuf::from("content/first.md");
        page.permalink = "http://example.com/first/".to_string();
        page.lang = "en".to_string();
        page.meta.title = Some("First Page".to_string());
        page.meta.in_search_index = true;
        page.meta.render = false;
        page.meta.datetime = Some(OffsetDateTime::parse("2023-01-31T00:00:00Z", &Rfc3339).unwrap());
        page.toc = vec![
            Heading {
                title: "Introduction".to_string(),
                children: vec![Heading {
                    title: "Sub intro".to_string(),
                    children: vec![],
                    ..Default::default()
                }],
                ..Default::default()
            },
            Heading { title: "Conclusion".to_string(), children: vec![], ..Default::default() },
        ];
        let mut taxonomies = BTreeMap::new();
        taxonomies.insert("tags".to_string(), vec!["Rust".to_string(), "Zola".to_string()]);
        taxonomies.insert("categories".to_string(), vec!["Dev".to_string()]);
        page.meta.taxonomies = taxonomies;

        section.pages.push(page.file.path.clone());
        library.insert_section(section);
        library.insert_page(page);

        library
    }

    #[test]
    fn default_fuse_index_omits_extra_fields() {
        let library = create_test_library();
        let config = Search::default();
        let json = build_index("en", &library, &config).unwrap();
        let items: Vec<serde_json::Value> = serde_json::from_str(&json).unwrap();
        assert_eq!(items.len(), 2);

        for item in &items {
            assert!(item.get("date").is_none());
            assert!(item.get("headings").is_none());
            assert!(item.get("taxonomies").is_none());
        }
    }

    #[test]
    fn fuse_index_with_date() {
        let library = create_test_library();
        let mut config = Search::default();
        config.include_date = true;
        let json = build_index("en", &library, &config).unwrap();
        let items: Vec<serde_json::Value> = serde_json::from_str(&json).unwrap();

        let page_item = items.iter().find(|i| i["url"] == "http://example.com/first/").unwrap();
        assert_eq!(page_item["date"], "2023-01-31T00:00:00Z");

        let section_item = items.iter().find(|i| i["url"] == "http://example.com/").unwrap();
        assert!(section_item.get("date").is_none());
    }

    #[test]
    fn fuse_index_with_headings() {
        let library = create_test_library();
        let mut config = Search::default();
        config.include_headings = true;
        let json = build_index("en", &library, &config).unwrap();
        let items: Vec<serde_json::Value> = serde_json::from_str(&json).unwrap();

        let page_item = items.iter().find(|i| i["url"] == "http://example.com/first/").unwrap();
        let headings = page_item["headings"].as_array().unwrap();
        assert_eq!(headings, &vec!["Introduction", "Sub intro", "Conclusion"]);

        let section_item = items.iter().find(|i| i["url"] == "http://example.com/").unwrap();
        assert_eq!(section_item["headings"].as_array().unwrap(), &Vec::<serde_json::Value>::new());
    }

    #[test]
    fn fuse_index_with_taxonomies() {
        let library = create_test_library();
        let mut config = Search::default();
        config.include_taxonomies = true;
        let json = build_index("en", &library, &config).unwrap();
        let items: Vec<serde_json::Value> = serde_json::from_str(&json).unwrap();

        let page_item = items.iter().find(|i| i["url"] == "http://example.com/first/").unwrap();
        let tax = &page_item["taxonomies"];
        assert_eq!(tax["tags"], serde_json::json!(["Rust", "Zola"]));
        assert_eq!(tax["categories"], serde_json::json!(["Dev"]));

        let section_item = items.iter().find(|i| i["url"] == "http://example.com/").unwrap();
        assert!(section_item.get("taxonomies").is_none());
    }
}
