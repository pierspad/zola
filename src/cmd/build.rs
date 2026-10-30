use std::path::Path;

use errors::{Error, Result};
use site::Site;

use crate::messages;

pub fn build(
    root_dir: &Path,
    config_file: &Path,
    base_url: Option<&str>,
    output_dir: Option<&Path>,
    force: bool,
    include_drafts: bool,
    minify: bool,
    incremental: bool,
    cache_memory_limit: Option<usize>,
) -> Result<()> {
    let mut site = Site::new(root_dir, config_file)?;
    if let Some(output_dir) = output_dir {
        if !force && output_dir.exists() {
            return Err(Error::msg(format!(
                "Directory '{}' already exists. Use --force to overwrite.",
                output_dir.display(),
            )));
        }

        site.set_output_path(output_dir);
    }
    if let Some(b) = base_url {
        site.set_base_url(b.to_string());
    }
    if include_drafts {
        site.include_drafts();
    }
    if minify {
        site.minify();
    }
    if incremental {
        let bytes = cache_memory_limit
            .map(|mib| {
                mib.checked_mul(1024 * 1024)
                    .ok_or_else(|| Error::msg("Cache memory limit is too large"))
            })
            .transpose()?;
        site.enable_incremental_with_memory_limit(bytes.unwrap_or(usize::MAX))?;
    }
    site.load()?;
    messages::notify_site_size(&site);
    messages::warn_about_ignored_pages(&site);
    site.build()?;
    site.save_incremental();
    Ok(())
}
