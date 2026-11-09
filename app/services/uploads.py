"""Secure image upload handling.

* Extension allow-list AND content sniffing via Pillow (the file must decode as an image).
* Size limits per file and per request (MAX_CONTENT_LENGTH).
* The image is re-encoded server-side to JPEG/WebP: this strips EXIF/GPS metadata and
  neutralises polyglot payloads. User-supplied filenames are never used on disk.
* Files are stored OUTSIDE the static folder and served only through an authorised view.
"""
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from flask import current_app
from flask_babel import gettext as _
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.utils import secure_filename

Image.MAX_IMAGE_PIXELS = 40_000_000  # decompression-bomb guard

try:  # optional HEIC support (iPhone photos)
    from pillow_heif import register_heif_opener  # type: ignore

    register_heif_opener()
except Exception:  # pragma: no cover
    pass


class UploadError(ValueError):
    pass


@dataclass
class StoredImage:
    stored_name: str
    original_name: str
    mime_type: str
    size_bytes: int
    width: int
    height: int


def upload_dir() -> Path:
    p = Path(current_app.config["UPLOAD_FOLDER"])
    p.mkdir(parents=True, exist_ok=True)
    return p


def _ext_ok(filename: str) -> bool:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in current_app.config["ALLOWED_IMAGE_EXTENSIONS"]


def save_image(file_storage) -> StoredImage:
    original = secure_filename(file_storage.filename or "")[:255] or "image"
    if not _ext_ok(file_storage.filename or ""):
        raise UploadError(_("Unsupported file type. Allowed: JPG, PNG, WEBP, HEIC."))

    stream = file_storage.stream
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    if size == 0:
        raise UploadError(_("The file is empty."))
    if size > current_app.config["MAX_IMAGE_BYTES"]:
        mb = current_app.config["MAX_IMAGE_BYTES"] // (1024 * 1024)
        raise UploadError(_("Image is too large (maximum %(mb)s MB).", mb=mb))

    try:
        with Image.open(stream) as probe:
            probe.verify()
        stream.seek(0)
        img = Image.open(stream)
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise UploadError(_("The file is not a valid image."))

    img = ImageOps.exif_transpose(img)
    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    img = img.convert("RGBA" if has_alpha else "RGB")
    max_dim = current_app.config["IMAGE_MAX_DIMENSION"]
    img.thumbnail((max_dim, max_dim))

    if has_alpha:
        ext, fmt, mime, opts = "webp", "WEBP", "image/webp", {"quality": 82}
    else:
        ext, fmt, mime, opts = "jpg", "JPEG", "image/jpeg", {"quality": 82, "optimize": True, "progressive": True}

    name = f"{secrets.token_hex(16)}.{ext}"
    path = upload_dir() / name
    img.save(path, fmt, **opts)  # no exif passed → metadata stripped
    os.chmod(path, 0o640)
    return StoredImage(name, original, mime, path.stat().st_size, img.width, img.height)


def delete_stored(stored_name: str) -> None:
    safe = secure_filename(stored_name)
    if not safe or safe != stored_name:
        return
    p = upload_dir() / safe
    if p.is_file():
        p.unlink()
