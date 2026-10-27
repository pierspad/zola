use std::io::{Read, Write};
use std::net::TcpListener;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::thread;
use std::time::Duration;

mod common;
use common::build_site;

#[test]
fn test_internal_links_with_anchors_dedup_and_errors() {
    let (mut site, _tmp, _pub) = build_site("test_site");

    let library = Arc::make_mut(&mut site.library);
    let page_paths: Vec<_> = library.pages.keys().cloned().collect();
    assert!(page_paths.len() >= 3);

    // Page 0 and Page 1 both link to a valid anchor in posts/fixed-slug.md#title
    library
        .pages
        .get_mut(&page_paths[0])
        .unwrap()
        .internal_links
        .push(("posts/fixed-slug.md".to_string(), Some("title".to_string())));
    library
        .pages
        .get_mut(&page_paths[1])
        .unwrap()
        .internal_links
        .push(("posts/fixed-slug.md".to_string(), Some("title".to_string())));

    // Page 1 and Page 2 both link to a MISSING anchor in posts/fixed-slug.md#does-not-exist
    library
        .pages
        .get_mut(&page_paths[1])
        .unwrap()
        .internal_links
        .push(("posts/fixed-slug.md".to_string(), Some("does-not-exist".to_string())));
    library
        .pages
        .get_mut(&page_paths[2])
        .unwrap()
        .internal_links
        .push(("posts/fixed-slug.md".to_string(), Some("does-not-exist".to_string())));

    // Page 0 links to a valid section anchor in _index.md#heading-1
    library
        .pages
        .get_mut(&page_paths[0])
        .unwrap()
        .internal_links
        .push(("_index.md".to_string(), Some("heading-1".to_string())));

    // Page 2 links to a MISSING section anchor in _index.md#missing-sec-anchor
    library
        .pages
        .get_mut(&page_paths[2])
        .unwrap()
        .internal_links
        .push(("_index.md".to_string(), Some("missing-sec-anchor".to_string())));

    let messages = site::link_checking::check_internal_links_with_anchors(&site);

    // Expect 3 errors:
    // - page_paths[1] with posts/fixed-slug.md#does-not-exist
    // - page_paths[2] with posts/fixed-slug.md#does-not-exist
    // - page_paths[2] with _index.md#missing-sec-anchor
    assert_eq!(messages.len(), 3);

    assert!(messages.iter().any(|m| m.contains("@/posts/fixed-slug.md#does-not-exist")
        && m.contains(&page_paths[1].to_string_lossy().to_string())));
    assert!(messages.iter().any(|m| m.contains("@/posts/fixed-slug.md#does-not-exist")
        && m.contains(&page_paths[2].to_string_lossy().to_string())));
    assert!(messages.iter().any(|m| m.contains("@/_index.md#missing-sec-anchor")
        && m.contains(&page_paths[2].to_string_lossy().to_string())));
}

#[test]
fn test_external_links_dedup_and_errors() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    listener.set_nonblocking(true).unwrap();
    let request_count = Arc::new(AtomicUsize::new(0));
    let count_clone = Arc::clone(&request_count);
    let running = Arc::new(AtomicBool::new(true));
    let running_clone = Arc::clone(&running);

    let server_handle = thread::spawn(move || {
        while running_clone.load(Ordering::SeqCst) {
            match listener.accept() {
                Ok((mut stream, _)) => {
                    count_clone.fetch_add(1, Ordering::SeqCst);
                    let mut buf = [0u8; 1024];
                    let _ = stream.read(&mut buf);
                    let response =
                        "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n";
                    let _ = stream.write_all(response.as_bytes());
                    let _ = stream.flush();
                }
                Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                    thread::sleep(Duration::from_millis(10));
                }
                Err(_) => break,
            }
        }
    });

    let (mut site, _tmp, _pub) = build_site("test_site");

    let library = Arc::make_mut(&mut site.library);
    let page_paths: Vec<_> = library.pages.keys().cloned().collect();

    // Clear existing external links so we test in isolation
    for page in library.pages.values_mut() {
        page.external_links.clear();
    }
    for sec in library.sections.values_mut() {
        sec.external_links.clear();
    }

    // Use local mock server URL across 3 different pages
    let broken_url = format!("http://127.0.0.1:{}/broken-link", port);
    library.pages.get_mut(&page_paths[0]).unwrap().external_links.push(broken_url.clone());
    library.pages.get_mut(&page_paths[1]).unwrap().external_links.push(broken_url.clone());
    library.pages.get_mut(&page_paths[2]).unwrap().external_links.push(broken_url.clone());

    let messages = site::link_checking::check_external_links(&site);

    running.store(false, Ordering::SeqCst);
    let _ = server_handle.join();

    // Verify deduplication: despite 3 pages referencing the URL, exactly 1 HTTP request was made
    assert_eq!(request_count.load(Ordering::SeqCst), 1);

    // Should report the broken link for all 3 pages
    assert_eq!(messages.len(), 3);
    for path in &page_paths[..3] {
        assert!(
            messages.iter().any(|m| m.contains(&path.to_string_lossy().to_string())
                && m.contains(&broken_url)),
            "Expected error for page {:?} not found in {:?}",
            path,
            messages
        );
    }
}
