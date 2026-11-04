//! Extract the first native Markdown image with the fork's locked parser.
use pulldown_cmark::{Event, Options, Parser, Tag, TagEnd};
fn main() {
    let source = std::fs::read_to_string(std::env::args().nth(1).unwrap()).unwrap();
    let body = source.strip_prefix("+++\n")
        .and_then(|rest| rest.split_once("\n+++\n").map(|(_, body)| body))
        .unwrap_or(&source);
    let mut image = None;
    let mut alt = String::new();
    for event in Parser::new_ext(body, Options::all()) {
        match event {
            Event::Start(Tag::Image { dest_url, .. }) if image.is_none() => image = Some(dest_url.to_string()),
            Event::Text(text) | Event::Code(text) if image.is_some() => alt.push_str(&text),
            Event::SoftBreak | Event::HardBreak if image.is_some() => alt.push('\n'),
            Event::End(TagEnd::Image) if image.is_some() => {
                println!("{}", serde_json::to_string(&(image.unwrap(), alt)).unwrap());
                return;
            }
            _ => {}
        }
    }
}
