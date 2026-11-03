use std::path::Path;
fn main() {
    let args: Vec<String> = std::env::args().collect();
    let content = std::fs::read(&args[1]).unwrap();
    let transformed = utils::minify::minify_asset_bytes(Path::new(&args[1]), &content).unwrap_or(content);
    std::fs::write(&args[2], transformed).unwrap();
}
