//! Extract the first native Markdown image with the fork's locked parser.
use pulldown_cmark::{Event, Options, Parser, Tag};
fn main() {
    let source = std::fs::read_to_string(std::env::args().nth(1).unwrap()).unwrap();
    let body = source.strip_prefix("+++\n")
        .and_then(|rest| rest.split_once("\n+++\n").map(|(_, body)| body))
        .unwrap_or(&source);
    for event in Parser::new_ext(body, Options::all()) {
        if let Event::Start(Tag::Image { dest_url, .. }) = event {
            println!("{dest_url}");
            return;
        }
    }
}
