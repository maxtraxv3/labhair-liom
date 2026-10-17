"""File sharing — generic file transfer with E2E encryption.

Files are sent as raw bytes with a metadata header. Received files are
saved to a configurable directory. The 1 MiB protocol limit applies.

Wire format (inside the encrypted FILE payload)::

    [4 bytes: meta_json length (big-endian uint32)]
    [meta_json bytes: UTF-8 JSON with file metadata]
    [remaining bytes: raw file data]
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

MAX_FILE_SIZE = (1 << 20) - 4096  # ~1 MiB minus overhead for base64 + JSON envelope


def _get_save_dir() -> Path:
    """Return the directory for saving received files."""
    if sys.platform == "win32":
        base = os.path.join(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"), "labhairliom")
    else:
        base = os.environ.get("XDG_DATA_HOME", "")
        if not base:
            base = os.path.join(Path.home(), ".local", "share")
        base = os.path.join(base, "labhairliom")
    d = Path(base) / "files"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class FileMessage:
    """Metadata for a shared file."""
    id: str
    name: str
    mime_type: str
    size: int
    sha256: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "mime": self.mime_type,
            "size": self.size,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, d: dict) -> FileMessage:
        return cls(
            id=str(d.get("id", "")),
            name=str(d.get("name", "file")),
            mime_type=str(d.get("mime", "application/octet-stream")),
            size=int(d.get("size", 0)),
            sha256=str(d.get("sha256", "")),
        )


def make_file_id(data: bytes) -> str:
    """Generate a short hex ID from file content."""
    return hashlib.sha256(data).hexdigest()[:12]


def pack_file_payload(meta: FileMessage, file_bytes: bytes) -> bytes:
    """Pack file metadata + raw bytes into a single wire payload."""
    meta_json = json.dumps(meta.to_dict(), separators=(",", ":")).encode("utf-8")
    return struct.pack("!I", len(meta_json)) + meta_json + file_bytes


def unpack_file_payload(payload: bytes) -> tuple[FileMessage, bytes]:
    """Unpack a wire payload into (metadata, file_bytes)."""
    if len(payload) < 4:
        raise ValueError("file payload too short")
    meta_len = struct.unpack("!I", payload[:4])[0]
    if meta_len > len(payload) - 4:
        raise ValueError("file payload meta length exceeds data")
    meta_json = payload[4:4 + meta_len]
    file_bytes = payload[4 + meta_len:]
    meta = FileMessage.from_dict(json.loads(meta_json.decode("utf-8")))
    return meta, file_bytes


def save_received_file(meta: FileMessage, file_bytes: bytes) -> Path:
    """Save a received file to the downloads directory."""
    save_dir = _get_save_dir()
    # Sanitize filename — strip path components, null bytes, leading dots, limit length
    safe_name = meta.name.replace("/", "_").replace("\\", "_").replace("\0", "")
    safe_name = safe_name.lstrip(".")
    if not safe_name:
        safe_name = f"{meta.id}_file"
    # Enforce max filename length (255 is typical filesystem limit)
    if len(safe_name) > 200:
        stem = safe_name[:200]
        suffix = Path(safe_name).suffix[:55]  # keep extension short
        safe_name = stem + suffix
    out_path = save_dir / safe_name
    # Avoid overwriting — append counter if needed
    if out_path.exists():
        stem = out_path.stem
        suffix = out_path.suffix
        counter = 1
        while out_path.exists():
            out_path = save_dir / f"{stem}_{counter}{suffix}"
            counter += 1
    out_path.write_bytes(file_bytes)
    return out_path


def format_file_info(meta: FileMessage, sender: str, saved_path: Path | None = None) -> str:
    """Format a human-readable file info line."""
    size_kb = meta.size / 1024
    if size_kb > 1024:
        size_str = f"{size_kb / 1024:.1f} MB"
    else:
        size_str = f"{size_kb:.1f} KB"
    parts = [
        f"\033[1m<{sender}>\033[0m sent file \033[33m{meta.name}\033[0m",
        f"  {meta.mime_type}  {size_str}  id={meta.id}",
    ]
    if saved_path:
        parts.append(f"  saved to {saved_path}")
    return "\n".join(parts)
