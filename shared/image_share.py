"""Image sharing — WebP encoding/decoding with ASCII preview.

Images are converted to WebP on send to minimize bandwidth.
Received images are saved to ``~/.local/share/labhairliom/images/`` (or
``$XDG_DATA_HOME/labhairliom/images/``) and a small ASCII preview is
shown in the terminal.

Wire format (inside the encrypted IMAGE payload)::

    {
      "id": "<sha256-hex-12>",
      "name": "photo.png",
      "w": 1920,
      "h": 1080,
      "webp_size": 48200,
      "quality": 80,
      "preview_cols": 60,
      "preview_rows": 30
    }
    <raw WebP bytes follow after the JSON>

The preview is an ASCII representation embedded in the same payload
after the WebP data, so receivers can display it without decoding the
full image.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Quality for WebP conversion (0-100). 80 is a good balance.
DEFAULT_QUALITY = 80

# Preview dimensions (characters in the terminal)
DEFAULT_PREVIEW_COLS = 60
DEFAULT_PREVIEW_ROWS = 30

# Luminance ramp for ASCII preview
_PREVIEW_RAMP = list(" .:-=+*#%@")


def _get_save_dir() -> Path:
    """Return the directory for saving received images."""
    if sys.platform == "win32":
        base = os.path.join(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"), "labhairliom")
    else:
        base = os.environ.get("XDG_DATA_HOME", "")
        if not base:
            base = os.path.join(Path.home(), ".local", "share")
        base = os.path.join(base, "labhairliom")
    d = Path(base) / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class ImageMessage:
    """Metadata for a shared image."""
    id: str
    name: str
    width: int
    height: int
    webp_size: int
    quality: int
    preview_cols: int
    preview_rows: int

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "w": self.width,
            "h": self.height,
            "webp_size": self.webp_size,
            "quality": self.quality,
            "preview_cols": self.preview_cols,
            "preview_rows": self.preview_rows,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ImageMessage:
        return cls(
            id=d["id"],
            name=d.get("name", "image"),
            width=d.get("w", 0),
            height=d.get("h", 0),
            webp_size=d.get("webp_size", 0),
            quality=d.get("quality", DEFAULT_QUALITY),
            preview_cols=d.get("preview_cols", DEFAULT_PREVIEW_COLS),
            preview_rows=d.get("preview_rows", DEFAULT_PREVIEW_ROWS),
        )


def load_and_convert(
    path: str,
    quality: int = DEFAULT_QUALITY,
    preview_cols: int = DEFAULT_PREVIEW_COLS,
    preview_rows: int = DEFAULT_PREVIEW_ROWS,
) -> tuple[ImageMessage, bytes, str]:
    """Load an image, convert to WebP, generate ASCII preview.

    Returns (metadata, webp_bytes, ascii_preview_string).
    """
    from PIL import Image

    img = Image.open(path)
    orig_w, orig_h = img.size

    # Convert to RGB if needed (WebP supports alpha but let's keep it simple)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")

    # Convert to WebP
    buf = img.tobytes()  # not used directly
    import io

    webp_buf = io.BytesIO()
    img.save(webp_buf, format="WEBP", quality=quality)
    webp_bytes = webp_buf.getvalue()

    # Generate unique ID from content hash
    content_hash = hashlib.sha256(webp_bytes).hexdigest()[:12]

    # Generate ASCII preview from the original image
    preview = _make_ascii_preview(img, preview_cols, preview_rows)

    meta = ImageMessage(
        id=content_hash,
        # Do not transmit the source filename; it can contain a person's
        # name, device export path, or other identifying information.
        name="image.webp",
        width=orig_w,
        height=orig_h,
        webp_size=len(webp_bytes),
        quality=quality,
        preview_cols=preview_cols,
        preview_rows=preview_rows,
    )

    return meta, webp_bytes, preview


def _make_ascii_preview(img, cols: int, rows: int) -> str:
    """Convert a PIL image to an ASCII art string.

    Uses only Pillow + numpy — no cv2 dependency required.
    """
    from PIL import Image as PILImage

    # Convert to grayscale and resize
    gray = img.convert("L").resize((cols, rows), PILImage.LANCZOS)
    arr = np.array(gray)

    # Contrast stretch
    lo, hi = np.percentile(arr, [5, 95])
    if hi <= lo:
        hi = lo + 1
    norm = np.clip((arr.astype(np.float32) - lo) / (hi - lo), 0, 1)

    # Map to characters
    idx = (norm * (len(_PREVIEW_RAMP) - 1)).astype(int)
    lines = []
    for row in idx:
        lines.append("".join(_PREVIEW_RAMP[i] for i in row))
    return "\n".join(lines)


def pack_image_payload(meta: ImageMessage, webp_bytes: bytes, preview: str) -> bytes:
    """Pack image metadata + WebP + preview into a single wire payload."""
    meta_dict = meta.to_dict()
    meta_dict["preview"] = preview
    meta_json = json.dumps(meta_dict, separators=(",", ":")).encode("utf-8")
    # Format: [meta_len(4)][meta_json][webp_bytes]
    return struct.pack("!I", len(meta_json)) + meta_json + webp_bytes


def unpack_image_payload(payload: bytes) -> tuple[ImageMessage, bytes, str]:
    """Unpack a wire payload into (metadata, webp_bytes, preview_string)."""
    if len(payload) < 4:
        raise ValueError("image payload too short")
    meta_len = struct.unpack("!I", payload[:4])[0]
    if meta_len > len(payload) - 4:
        raise ValueError("image metadata length exceeds payload")
    meta_json = payload[4 : 4 + meta_len]
    webp_bytes = payload[4 + meta_len :]
    meta_dict = json.loads(meta_json.decode("utf-8"))
    preview = meta_dict.pop("preview", "")
    meta = ImageMessage.from_dict(meta_dict)
    return meta, webp_bytes, preview


def save_received_image(meta: ImageMessage, webp_bytes: bytes) -> Path:
    """Save a received WebP image to the downloads directory."""
    save_dir = _get_save_dir()
    # Use the content hash as filename to avoid collisions
    out_path = save_dir / f"{meta.id}.webp"
    out_path.write_bytes(webp_bytes)
    return out_path


def decode_webp_preview(webp_bytes: bytes, cols: int, rows: int) -> str:
    """Generate an ASCII preview from WebP bytes (for re-display)."""
    from PIL import Image
    import io

    img = Image.open(io.BytesIO(webp_bytes))
    return _make_ascii_preview(img, cols, rows)


def format_image_info(meta: ImageMessage, sender: str, saved_path: Path | None = None) -> str:
    """Format a human-readable image info line."""
    size_kb = meta.webp_size / 1024
    parts = [
        f"\033[1m<{sender}>\033[0m sent image \033[33m{meta.name}\033[0m",
        f"  {meta.width}x{meta.height}  WebP {size_kb:.1f} KB  id={meta.id}",
    ]
    if saved_path:
        parts.append(f"  saved to {saved_path}")
    return "\n".join(parts)


def format_image_preview(meta: ImageMessage, preview: str, sender: str) -> str:
    """Format an ASCII preview with box drawing for terminal display."""
    lines = preview.splitlines()
    if not lines:
        return ""
    w = max(len(l) for l in lines)
    border = "+" + "-" * (w + 2) + "+"
    body = "\n".join("| " + l.ljust(w) + " |" for l in lines)
    header = f"--- Image from {sender}: {meta.name} ({meta.width}x{meta.height}) ---"
    return f"{header}\n{border}\n{body}\n{border}"
