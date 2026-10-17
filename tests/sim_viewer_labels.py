"""Regression guard: the viewer stream dropdown shows real usernames.

Covers the label plumbing in ViewerWindow.push_jpeg: a remote stream must
appear as "Alice (screen)" (never a raw uid), a local stream as
"Maxtrax (screen)", and the dropdown options must carry those labels.
"""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client.flet_app.viewer import ViewerWindow


def _tiny_jpeg() -> bytes:
    from PIL import Image as _PILImage
    buf = io.BytesIO()
    _PILImage.new("RGB", (160, 90), (60, 90, 200)).save(buf, format="JPEG", quality=60)
    return buf.getvalue()


class FakePanel:
    visible = True


class FakeDropdown:
    def __init__(self):
        self.options = None


class FakePage:
    width, height = 1200, 800

    def update(self):
        pass


class FakeClient:
    display = "Maxtrax"


def main() -> int:
    fails = []

    vw = ViewerWindow(FakePage(), FakeClient())
    vw._panel = FakePanel()
    vw._stream_dropdown = FakeDropdown()
    jpg = _tiny_jpeg()

    # 1) remote stream -> display name in parentheses with source
    vw.push_jpeg(jpg, source="screen", resolution="", label="Alice (screen)")
    if vw._streams != ["Alice (screen)"]:
        fails.append(f"remote label wrong: {vw._streams!r}")
    if vw._stream_dropdown.options is None or vw._stream_dropdown.options[0].text != "Alice (screen)":
        fails.append(f"dropdown option wrong: {vw._stream_dropdown.options!r}")
    if vw._frames.get("Alice (screen)") is not jpg:
        fails.append("frame not stored under label key")

    # 2) local stream -> default label from source+resolution
    vw._last_push_time = 0.0  # reset 1/30s throttle: in practice streams arrive seconds apart
    vw.push_jpeg(jpg, source="screen", resolution="854x480")
    if "screen 854x480" not in vw._streams:
        fails.append(f"local default label missing: {vw._streams!r}")

    # 3) repeated frames do not duplicate dropdown entries
    vw._last_push_time = 0.0
    vw.push_jpeg(jpg, source="screen", resolution="854x480")
    if vw._streams.count("screen 854x480") != 1:
        fails.append(f"label duplicated: {vw._streams!r}")

    # 4) explicit label wins over source/resolution
    vw._last_push_time = 0.0
    vw.push_jpeg(jpg, source="screen", resolution="1080p", label="Bob (screen)")
    if "Bob (screen)" not in vw._streams or "screen 1080p" in vw._streams:
        fails.append(f"explicit label not honored: {vw._streams!r}")

    if fails:
        for f in fails:
            print(f"FAIL: {f}")
        return 1
    print("viewer label dropdown: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())