use site::Site;
use std::collections::BTreeMap;
use std::path::Path;
use walkdir::WalkDir;

fn write(root: &Path, path: &str, text: &str) {
    let path = root.join(path);
    std::fs::create_dir_all(path.parent().unwrap()).unwrap();
    std::fs::write(path, text).unwrap();
}

fn build(root: &Path, incremental: bool) -> errors::Result<()> {
    let mut site = Site::new(root, "config.toml")?;
    if incremental {
        site.enable_incremental()?;
    }
    site.load()?;
    site.build()?;
    site.save_incremental();
    Ok(())
}

fn manifest(root: &Path) -> BTreeMap<String, Vec<u8>> {
    let output = root.join("public");
    WalkDir::new(&output)
        .into_iter()
        .map(|entry| entry.unwrap())
        .filter(|e| e.file_type().is_file())
        .map(|e| {
            (
                e.path().strip_prefix(&output).unwrap().to_string_lossy().into_owned(),
                std::fs::read(e.path()).unwrap(),
            )
        })
        .collect()
}

fn assert_matches_clean(root: &Path) {
    build(root, true).unwrap();
    let cached = manifest(root);
    build(root, false).unwrap();
    assert_eq!(cached, manifest(root));
}

#[test]
fn persistent_cache_tracks_links_asset_owners_and_failed_builds() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    let config = "base_url='https://example.com'\n[link_checker]\ninternal_level='warn'\n";
    write(root, "config.toml", config);
    write(root, "templates/page.html", "{{ page.content | safe }}");
    write(
        root,
        "templates/index.html",
        "{% for p in section.pages %}{{ p.content | safe }}{% endfor %}",
    );
    write(root, "content/_index.md", "+++\n+++\n");
    write(
        root,
        "content/source.md",
        "+++\ntitle='Source'\n+++\n[missing](@/target.md)\n[asset](@/bundle/photo.png)\n",
    );
    write(root, "content/bundle/index.md", "+++\ntitle='Bundle'\nslug='old'\n+++\n# Bundle\n");
    write(root, "content/bundle/photo.png", "asset");
    assert_matches_clean(root);
    write(root, "content/target.md", "+++\ntitle='Target'\n+++\n# Target\n");
    assert_matches_clean(root);
    // Exercise an actual hit before changing a dependency.
    assert_matches_clean(root);
    write(root, "content/bundle/index.md", "+++\ntitle='Bundle'\nslug='new'\n+++\n# Bundle\n");
    assert_matches_clean(root);
    assert!(
        std::fs::read_to_string(root.join("public/source/index.html"))
            .unwrap()
            .contains("/new/photo.png")
    );
    std::fs::remove_file(root.join("content/target.md")).unwrap();
    assert_matches_clean(root);
    write(root, "config.toml", &config.replace("'warn'", "'error'"));
    assert!(build(root, true).is_err());
    write(root, "config.toml", config);
    assert_matches_clean(root);
    write(root, ".zola-cache/render-v2.json", "{broken");
    assert_matches_clean(root);
    write(root, "content/target.md", "+++\ntitle='Target'\n+++\n# Target\n");
    write(root, "content/source.md", "+++\n+++\n[target](@/target.md#target)\n");
    assert_matches_clean(root);
    write(root, "config.toml", &config.replace("'warn'", "'error'"));
    build(root, true).unwrap();
    write(root, "content/target.md", "+++\ntitle='Target'\n+++\n# Different heading\n");
    assert!(build(root, true).is_err());
}

#[test]
fn image_dependencies_track_decoded_traversal_missing_files_and_symlinks() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    write(root, "config.toml", "base_url='https://example.com'\n");
    write(root, "templates/page.html", "{{ page.content | safe }}");
    write(root, "templates/index.html", "{{ section.content | safe }}");
    write(root, "content/_index.md", "+++\n+++\n");
    write(
        root,
        "content/nested/source.md",
        "+++\n+++\n![entity](..&#47;..&#47;logo.svg)\n![percent](%2e%2e/%2e%2e/logo.svg)\n",
    );
    // Missing image candidates must invalidate when the file later appears.
    assert_matches_clean(root);
    write(
        root,
        "logo.svg",
        r#"<svg xmlns="http://www.w3.org/2000/svg" width="12" height="23"></svg>"#,
    );
    assert_matches_clean(root);
    assert!(
        std::fs::read_to_string(root.join("public/nested/source/index.html"))
            .unwrap()
            .contains("width=\"12\"")
    );
    write(
        root,
        "logo.svg",
        r#"<svg xmlns="http://www.w3.org/2000/svg" width="34" height="45"></svg>"#,
    );
    assert_matches_clean(root);
    assert!(
        std::fs::read_to_string(root.join("public/nested/source/index.html"))
            .unwrap()
            .contains("width=\"34\"")
    );
    #[cfg(unix)]
    {
        let outside = tempfile::tempdir().unwrap();
        write(
            outside.path(),
            "logo.svg",
            r#"<svg xmlns="http://www.w3.org/2000/svg" width="56" height="67"></svg>"#,
        );
        std::fs::remove_file(root.join("logo.svg")).unwrap();
        std::os::unix::fs::symlink(outside.path().join("logo.svg"), root.join("logo.svg")).unwrap();
        assert_matches_clean(root);
        write(
            outside.path(),
            "logo.svg",
            r#"<svg xmlns="http://www.w3.org/2000/svg" width="78" height="89"></svg>"#,
        );
        assert_matches_clean(root);
    }
}

#[test]
fn native_summary_cache_restores_metadata_and_rejects_dynamic_cutoffs() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    write(root, "config.toml", "base_url='https://example.com'\n");
    write(
        root,
        "templates/page.html",
        "{{ page.content | safe }}{{ page.summary | safe }}{% for h in page.toc %}{{ h.id }}{% endfor %}",
    );
    write(root, "templates/index.html", "{{ section.content | safe }}");
    write(root, "content/_index.md", "+++\n+++\n");
    write(
        root,
        "content/post.md",
        "+++\n+++\n# First\n\nSummary\n\n<!-- more -->\n\n# Second\n\nBody\n",
    );
    assert_matches_clean(root);
    assert_matches_clean(root);
    let cache: serde_json::Value =
        serde_json::from_slice(&std::fs::read(root.join(".zola-cache/render-v2.json")).unwrap())
            .unwrap();
    assert!(
        cache["markdown"]
            .as_object()
            .unwrap()
            .values()
            .any(|v| v["summary"].as_str().is_some_and(|s| s.contains("Summary")))
    );
    // An inline marker leaves an open paragraph and invokes the cutoff template.
    write(root, "content/post.md", "+++\n+++\nFirst <!-- more --> rest\n");
    write(
        root,
        "templates/summary-cutoff.html",
        "{{ load_data(path='cutoff.txt', format='plain') }}",
    );
    write(root, "cutoff.txt", "OLD");
    assert_matches_clean(root);
    write(root, "cutoff.txt", "NEW");
    assert_matches_clean(root);
    assert!(std::fs::read_to_string(root.join("public/post/index.html")).unwrap().contains("NEW"));
}

#[test]
fn deleting_last_image_variant_matches_fresh_full_and_incremental_builds() {
    for incremental in [false, true] {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path();
        write(root, "config.toml", "base_url='https://example.com'\n");
        write(root, "templates/index.html", "{{ section.content | safe }}");
        write(root, "content/_index.md", "+++\n+++\n");
        let image = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../test_site/content/posts/with-assets/zola.png");
        std::fs::create_dir_all(root.join("static")).unwrap();
        std::fs::copy(image, root.join("static/photo.png")).unwrap();
        write(
            root,
            "templates/page.html",
            "{% set image = resize_image(path='photo.png', width=8, op='fit_width') %}{{ image.url }}",
        );
        write(root, "content/post.md", "+++\n+++\nHello\n");
        build(root, incremental).unwrap();
        assert!(manifest(root).keys().any(|p| p.starts_with("processed_images/")));
        let generated =
            manifest(root).keys().find(|p| p.starts_with("processed_images/")).unwrap().clone();
        // Unrelated theme assets and a theme asset shadowed by a generated
        // filename must survive pruning of the site's processed-image cache.
        write(root, "config.toml", "base_url='https://example.com'\ntheme='sample'\n");
        write(root, "themes/sample/theme.toml", "name='sample'\n");
        write(root, "themes/sample/templates/page.html", "unused");
        write(root, &format!("themes/sample/static/{generated}"), "theme fallback");
        write(root, "themes/sample/static/processed_images/unrelated.txt", "keep");
        write(root, "templates/page.html", "{{ page.content | safe }}");
        build(root, incremental).unwrap();
        let warm = manifest(root);
        assert_eq!(warm.get(&generated).unwrap(), b"theme fallback");
        assert_eq!(warm.get("processed_images/unrelated.txt").unwrap(), b"keep");
        assert_eq!(warm.keys().filter(|p| p.starts_with("processed_images/")).count(), 2);
        // Remove the processor cache, making this a true fresh oracle.
        std::fs::remove_dir_all(root.join("static/processed_images")).unwrap();
        build(root, false).unwrap();
        assert_eq!(warm, manifest(root));
    }
}

#[test]
fn cache_memory_allowances_fall_back_without_changing_output() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    write(root, "config.toml", "base_url='https://example.com'\n");
    write(root, "templates/page.html", "{{ page.content | safe }}");
    write(root, "templates/index.html", "{{ section.content | safe }}");
    write(root, "content/_index.md", "+++\n+++\n# Home");
    for n in 0..24 {
        write(
            root,
            &format!("content/{n}.md"),
            &format!("+++\ntitle='Page {n}'\n+++\n{}", "paragraph text ".repeat(100)),
        );
    }
    build(root, false).unwrap();
    let expected = manifest(root);
    let cache_path = root.join(".zola-cache/render-v2.json");
    for allowance in [1024 * 1024, 1024 * 1024, 1, 0, 4096, 4096] {
        let previous = std::fs::read(&cache_path).ok();
        let mut site = Site::new(root, "config.toml").unwrap();
        site.enable_incremental_with_memory_limit(allowance).unwrap();
        site.load().unwrap();
        site.build().unwrap();
        site.save_incremental();
        assert_eq!(expected, manifest(root), "allowance={allowance}");
        if allowance == 0 {
            assert_eq!(previous, std::fs::read(&cache_path).ok());
        }
    }
    std::fs::write(&cache_path, "{corrupt cache").unwrap();
    let mut site = Site::new(root, "config.toml").unwrap();
    site.enable_incremental_with_memory_limit(4096).unwrap();
    site.load().unwrap();
    site.build().unwrap();
    site.save_incremental();
    assert_eq!(expected, manifest(root));
}

#[cfg(unix)]
#[test]
fn unreadable_unused_cache_input_falls_back_to_full_build() {
    use std::os::unix::fs::PermissionsExt;
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    write(root, "config.toml", "base_url = \"https://example.com\"\ntheme = \"scratch\"\n");
    write(root, "content/_index.md", "+++\ntitle = \"Home\"\n+++\nHello\n");
    write(root, "templates/index.html", "<main>{{ section.content | safe }}</main>");
    write(root, "themes/scratch/theme.toml", "[extra]\n");
    std::fs::create_dir_all(root.join("themes/scratch/templates")).unwrap();
    write(root, "themes/scratch/unused.txt", "unused fingerprint input");
    build(root, false).unwrap();
    let expected = manifest(root);
    let unused = root.join("themes/scratch/unused.txt");
    std::fs::set_permissions(&unused, std::fs::Permissions::from_mode(0o000)).unwrap();
    // Privileged test users can read mode-000 files and cannot exercise this failure.
    if std::fs::read(&unused).is_ok() {
        std::fs::set_permissions(&unused, std::fs::Permissions::from_mode(0o600)).unwrap();
        return;
    }
    let full_result = build(root, false);
    let result = build(root, true);
    std::fs::set_permissions(&unused, std::fs::Permissions::from_mode(0o600)).unwrap();
    full_result.unwrap();
    result.unwrap();
    assert_eq!(expected, manifest(root));
    assert!(!root.join(".zola-cache/render-v2.json").exists());
}
