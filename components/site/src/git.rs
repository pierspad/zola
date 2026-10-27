use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::process::Command;

use content::Page;

/// Incurs a single `git log` call to retrieve the most recent commit date for all files in the `content` directory.
pub fn infer_all_pages_updated_from_git(base_path: &Path) -> HashMap<PathBuf, String> {
    let output = match Command::new("git")
        .arg("-C")
        .arg(base_path)
        .args([
            "-c",
            "core.quotepath=false",
            "log",
            "--format=COMMIT:%cs",
            "--name-only",
            "--relative",
            "--",
            "content",
        ])
        .output()
    {
        Ok(out) => out,
        Err(_) => return HashMap::new(),
    };

    if !output.status.success() {
        return HashMap::new();
    }

    let stdout = match std::str::from_utf8(&output.stdout) {
        Ok(s) => s,
        Err(_) => return HashMap::new(),
    };

    parse_git_log(stdout, base_path)
}

/// Parses the output of `git log --format=COMMIT:%cs --name-only --relative -- content`.
pub(crate) fn parse_git_log(stdout: &str, base_path: &Path) -> HashMap<PathBuf, String> {
    let mut dates = HashMap::new();
    let mut current_date: Option<String> = None;

    for line in stdout.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }

        if let Some(date) = line.strip_prefix("COMMIT:") {
            let date = date.trim();
            if !date.is_empty() {
                current_date = Some(date.to_string());
            }
        } else if let Some(ref date) = current_date {
            if !line.ends_with(".md") {
                continue;
            }
            let rel_path: PathBuf = line.split('/').collect();
            let full_path = base_path.join(rel_path);
            dates.entry(full_path).or_insert_with(|| date.clone());
        }
    }

    dates
}

/// Query git for the most recent commit date of a single file.
pub fn infer_page_updated_from_git(base_path: &Path, file_path: &Path) -> Option<String> {
    let arg_path = file_path.strip_prefix(base_path).unwrap_or(file_path);
    let output = Command::new("git")
        .arg("-C")
        .arg(base_path)
        .args(["log", "-1", "--format=%cs", "--"])
        .arg(arg_path)
        .output()
        .ok()?;

    if !output.status.success() {
        return None;
    }

    let stdout = std::str::from_utf8(&output.stdout).ok()?;
    let trimmed = stdout.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}

/// Applies inferred git commit date to a page if `page.meta.updated` is None.
/// Guards against same-day or earlier commit noise: if the commit date is on or before
/// the page creation date, `updated` is reset to None.
pub fn apply_inferred_updated(page: &mut Page, git_date: &str) {
    if page.meta.updated.is_some() {
        return;
    }

    page.meta.updated = Some(git_date.to_string());
    page.meta.date_to_datetime();

    if let (Some(created_dt), Some(updated_dt)) = (page.meta.datetime, page.meta.updated_datetime)
        && (updated_dt.year(), u8::from(updated_dt.month()), updated_dt.day())
            <= (created_dt.year(), u8::from(created_dt.month()), created_dt.day())
    {
        page.meta.updated = None;
        page.meta.updated_datetime = None;
        page.meta.updated_datetime_tuple = None;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_git_log() {
        let stdout = r#"
COMMIT:2026-10-27

content/posts/recent.md
content/posts/older.md

COMMIT:2026-10-20

content/posts/older.md
content/posts/ancient.md
"#;
        let base_path = Path::new("/mock/site");
        let dates = parse_git_log(stdout, base_path);

        assert_eq!(dates.get(&base_path.join("content/posts/recent.md")), Some(&"2026-10-27".to_string()));
        // older.md should keep the most recent commit date (2026-10-27), not the older one (2026-10-20)
        assert_eq!(dates.get(&base_path.join("content/posts/older.md")), Some(&"2026-10-27".to_string()));
        assert_eq!(dates.get(&base_path.join("content/posts/ancient.md")), Some(&"2026-10-20".to_string()));
    }

    #[test]
    fn test_apply_inferred_updated_no_date() {
        let mut page = Page::default();
        apply_inferred_updated(&mut page, "2026-10-27");
        assert_eq!(page.meta.updated, Some("2026-10-27".to_string()));
        assert!(page.meta.updated_datetime.is_some());
        assert_eq!(page.meta.updated_datetime_tuple, Some((2026, 10, 27)));
    }

    #[test]
    fn test_apply_inferred_updated_older_creation_date() {
        let mut page = Page::default();
        page.meta.date = Some("2025-01-01".to_string());
        page.meta.date_to_datetime();

        apply_inferred_updated(&mut page, "2026-10-27");
        assert_eq!(page.meta.updated, Some("2026-10-27".to_string()));
        assert!(page.meta.updated_datetime.is_some());
        assert_eq!(page.meta.updated_datetime_tuple, Some((2026, 10, 27)));
    }

    #[test]
    fn test_apply_inferred_updated_same_day() {
        let mut page = Page::default();
        page.meta.date = Some("2026-10-27".to_string());
        page.meta.date_to_datetime();

        apply_inferred_updated(&mut page, "2026-10-27");
        assert_eq!(page.meta.updated, None);
        assert_eq!(page.meta.updated_datetime, None);
        assert_eq!(page.meta.updated_datetime_tuple, None);
    }

    #[test]
    fn test_apply_inferred_updated_future_creation_date() {
        let mut page = Page::default();
        page.meta.date = Some("2099-01-01".to_string());
        page.meta.date_to_datetime();

        apply_inferred_updated(&mut page, "2026-10-27");
        assert_eq!(page.meta.updated, None);
        assert_eq!(page.meta.updated_datetime, None);
        assert_eq!(page.meta.updated_datetime_tuple, None);
    }

    #[test]
    fn test_apply_inferred_updated_explicit_preserved() {
        let mut page = Page::default();
        page.meta.date = Some("2025-01-01".to_string());
        page.meta.updated = Some("2025-06-01".to_string());
        page.meta.date_to_datetime();

        apply_inferred_updated(&mut page, "2026-10-27");
        assert_eq!(page.meta.updated, Some("2025-06-01".to_string()));
        assert_eq!(page.meta.updated_datetime_tuple, Some((2025, 6, 1)));
    }
}
