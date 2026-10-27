mod common;
use config::Config;

#[test]
fn can_transform_image() {
    let cases = vec![
        "![haha](https://example.com/abc.jpg)",
        "![](https://example.com/abc.jpg)",
        "![ha\"h>a](https://example.com/abc.jpg)",
        "![__ha__*ha*](https://example.com/abc.jpg)",
        "![ha[ha](https://example.com)](https://example.com/abc.jpg)",
    ];

    let body = common::render(&cases.join("\n")).unwrap().body;
    insta::assert_snapshot!(body);
}

#[test]
fn can_add_lazy_loading_and_async_decoding() {
    let cases = vec![
        "![haha](https://example.com/abc.jpg)",
        "![](https://example.com/abc.jpg)",
        "![ha\"h>a](https://example.com/abc.jpg)",
        "![__ha__*ha*](https://example.com/abc.jpg)",
        "![ha[ha](https://example.com)](https://example.com/abc.jpg)",
    ];

    let mut config = Config::default_for_test();
    config.markdown.lazy_async_image = true;

    let body = common::render_with_config(&cases.join("\n"), config).unwrap().body;
    insta::assert_snapshot!(body);
}

#[test]
fn first_image_is_eager_when_lazy_async_enabled() {
    let mut config = Config::default_for_test();
    config.markdown.lazy_async_image = true;

    // Single image case: only decoding="async", no loading="lazy" (eager by default)
    let single = common::render_with_config("![hero](https://example.com/hero.jpg)", config.clone()).unwrap().body;
    assert_eq!(single, "<p><img src=\"https://example.com/hero.jpg\" alt=\"hero\" decoding=\"async\" /></p>\n");

    // Multiple images: first image omits loading="lazy", subsequent images have loading="lazy"
    let multiple = common::render_with_config(
        "![hero](https://example.com/hero.jpg)\n\n![second](https://example.com/second.jpg)",
        config,
    )
    .unwrap()
    .body;
    assert_eq!(
        multiple,
        "<p><img src=\"https://example.com/hero.jpg\" alt=\"hero\" decoding=\"async\" /></p>\n<p><img src=\"https://example.com/second.jpg\" alt=\"second\" loading=\"lazy\" decoding=\"async\" /></p>\n"
    );
}
