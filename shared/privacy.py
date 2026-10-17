"""Best-effort upload privacy checks and sanitization."""

from __future__ import annotations

import io
import mimetypes
from dataclasses import dataclass
from pathlib import Path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


@dataclass(frozen=True)
class FilePrivacyReport:
    can_strip: bool
    warning: str = ""


def inspect_file(path: str | Path) -> FilePrivacyReport:
    """Return whether this format can be sanitized by the bundled code."""
    suffix = Path(path).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return FilePrivacyReport(True)
    return FilePrivacyReport(
        False,
        "Identifying metadata could not be stripped from this file format. "
        "It may contain GPS/location, device, author, timestamp, or software metadata.",
    )


def sanitize_image(path: str | Path) -> tuple[bytes, str, str]:
    """Re-encode an image without carrying source metadata; return bytes/name/MIME."""
    from PIL import Image

    with Image.open(path) as source:
        if source.mode not in ("RGB", "RGBA"):
            source = source.convert("RGB")
        output = io.BytesIO()
        source.save(output, format="WEBP", quality=80, exif=b"", icc_profile=None, xmp=b"")
    return output.getvalue(), "image.webp", "image/webp"


def neutral_filename(path: str | Path, original_name: str = "") -> str:
    """Keep only a generic extension; do not transmit a potentially identifying filename."""
    suffix = Path(original_name or path).suffix.lower()
    return f"file{suffix}" if suffix else "file.bin"

