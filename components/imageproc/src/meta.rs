use ahash::AHashMap;
use avif_parse::read_avif;
use errors::{Context, Result, anyhow};
use fs_err as fs;
use image::{ImageDecoder, ImageReader};
use image::{ImageFormat, ImageResult};
use serde::Serialize;
use std::ffi::OsStr;
use std::io::BufReader;
use std::path::{Path, PathBuf};
use std::sync::{LazyLock, Mutex};
use std::time::SystemTime;
use svg_metadata::Metadata as SvgMetadata;

use crate::get_rotated_size;
use crate::helpers::{get_created_datetime, get_description};

type CacheEntry<T> = (u64, SystemTime, T);

static META_CACHE: LazyLock<Mutex<AHashMap<PathBuf, CacheEntry<ImageMetaResponse>>>> =
    LazyLock::new(|| Mutex::new(AHashMap::new()));

static IMAGE_META_CACHE: LazyLock<Mutex<AHashMap<PathBuf, CacheEntry<ImageMeta>>>> =
    LazyLock::new(|| Mutex::new(AHashMap::new()));

/// Size and format read cheaply with `image`'s `Reader`.
#[derive(Debug, Clone)]
pub struct ImageMeta {
    /// (w, h)
    pub size: (u32, u32),
    pub format: Option<ImageFormat>,
    pub description: Option<String>,
    pub created: Option<String>,
}

impl ImageMeta {
    pub fn read(path: &Path) -> ImageResult<Self> {
        let file_meta =
            fs::metadata(path).ok().and_then(|m| m.modified().ok().map(|mtime| (m.len(), mtime)));

        if let Some((len, mtime)) = file_meta {
            let cache = IMAGE_META_CACHE.lock().unwrap_or_else(|e| e.into_inner());
            if let Some((cached_len, cached_mtime, cached_meta)) = cache.get(path)
                && *cached_len == len
                && *cached_mtime == mtime
            {
                return Ok(cached_meta.clone());
            }
        }

        let meta = Self::read_uncached(path)?;

        if let Some((len, mtime)) = file_meta {
            let mut cache = IMAGE_META_CACHE.lock().unwrap_or_else(|e| e.into_inner());
            cache.insert(path.to_path_buf(), (len, mtime, meta.clone()));
        }

        Ok(meta)
    }

    fn read_uncached(path: &Path) -> ImageResult<Self> {
        let reader = ImageReader::open(path).and_then(ImageReader::with_guessed_format)?;
        let format = reader.format();
        let mut decoder = reader.into_decoder()?;
        let size = decoder.dimensions();
        let Some(metadata) = decoder.exif_metadata()? else {
            // No raw EXIF data present for this file
            return Ok(Self { size, format, description: None, created: None });
        };
        let metadata = match exif::Reader::new().read_raw(metadata) {
            Ok(metadata) => metadata,
            Err(e) => {
                log::warn!("Failed to parse exif for {}: {}", path.display(), e);
                return Ok(Self { size, format, description: None, created: None });
            }
        };

        let size = get_rotated_size(size.0, size.1, &metadata).unwrap_or(size);
        let description = get_description(&metadata).ok();
        let created = get_created_datetime(&metadata).ok();
        Ok(Self { size, format, description, created })
    }

    pub fn is_lossy(&self) -> bool {
        use ImageFormat::*;

        // We assume lossy by default / if unknown format
        let format = self.format.unwrap_or(Jpeg);
        !matches!(format, Png | Pnm | Tiff | Tga | Bmp | Ico | Hdr | Farbfeld)
    }
}

#[derive(Debug, Clone, Serialize, Eq, PartialEq)]
pub struct ImageMetaResponse {
    pub width: u32,
    pub height: u32,
    pub format: Option<&'static str>,
    pub mime: Option<&'static str>,
    pub description: Option<String>,
    pub created: Option<String>,
}

impl ImageMetaResponse {
    fn new_svg(path: &Path) -> Result<Self> {
        let img = SvgMetadata::parse_file(path)?;
        let (w, h) = match (img.width(), img.height(), img.view_box()) {
            (Some(w), Some(h), _) => Ok((w, h)),
            (_, _, Some(view_box)) => Ok((view_box.width, view_box.height)),
            _ => Err(anyhow!("Invalid dimensions: SVG width/height and viewbox not set.")),
        }?;
        Ok(Self {
            width: w as u32,
            height: h as u32,
            format: Some("svg"),
            mime: Some("text/svg+xml"),
            // SVG files have these fields, but we'd need a more comprehensive parser to read them.
            description: None,
            created: None,
        })
    }

    fn new_avif(path: &Path) -> Result<Self> {
        let avif_data = read_avif(&mut BufReader::new(fs::File::open(path)?))?;
        let meta = avif_data.primary_item_metadata()?;
        Ok(Self {
            width: meta.max_frame_width.get(),
            height: meta.max_frame_height.get(),
            format: Some("avif"),
            mime: Some("image/avif"),
            // AVIF files have exif metadata to read these fields from, but we'd  need to enable image's avif-native feature to support decoding it.
            description: None,
            created: None,
        })
    }
}

impl From<ImageMeta> for ImageMetaResponse {
    fn from(im: ImageMeta) -> Self {
        Self {
            width: im.size.0,
            height: im.size.1,
            format: im.format.and_then(|f| f.extensions_str().first()).copied(),
            mime: im.format.map(|f| f.to_mime_type()),
            description: im.description,
            created: im.created,
        }
    }
}

/// Read image dimensions (cheaply), used in `get_image_metadata()`, supports SVG
pub fn read_image_metadata<P: AsRef<Path>>(path: P) -> Result<ImageMetaResponse> {
    let path = path.as_ref();
    let ext = path.extension().and_then(OsStr::to_str).unwrap_or("").to_lowercase();

    let err_context = || {
        format!(
            "Failed to read image (ext: {}) metadata: {}",
            if ext.is_empty() { "?" } else { ext.as_str() },
            path.display()
        )
    };

    let file_meta =
        fs::metadata(path).ok().and_then(|m| m.modified().ok().map(|mtime| (m.len(), mtime)));

    if let Some((len, mtime)) = file_meta {
        let cache = META_CACHE.lock().unwrap_or_else(|e| e.into_inner());
        if let Some((cached_len, cached_mtime, cached_meta)) = cache.get(path)
            && *cached_len == len
            && *cached_mtime == mtime
        {
            return Ok(cached_meta.clone());
        }
    }

    let meta = match ext.as_str() {
        "svg" => ImageMetaResponse::new_svg(path),
        "avif" => ImageMetaResponse::new_avif(path),
        _ => ImageMeta::read(path).map(ImageMetaResponse::from).map_err(Into::into),
    }
    .with_context(err_context)?;

    if let Some((len, mtime)) = file_meta {
        let mut cache = META_CACHE.lock().unwrap_or_else(|e| e.into_inner());
        cache.insert(path.to_path_buf(), (len, mtime, meta.clone()));
    }

    Ok(meta)
}
