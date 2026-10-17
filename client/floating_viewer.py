"""Floating desktop video viewer (Tkinter window) for Labhair-liom.

A real OS window that floats on the desktop — movable anywhere on screen,
resizable, closable via its X — unlike the Flet overlay panel. Flet 0.25 has no
second native window and its page.update() path limits in-app rendering rates,
so this viewer renders in its own dedicated Tkinter thread, fed with the same
JPEG frames the screen-share loop produces over a threadsafe queue (newest
frame wins; stale frames are dropped).

The window title shows live FPS: "<display fps> fps (feed <capture fps>)".
"""

from __future__ import annotations

import io
import queue
import threading
import time
from typing import Optional

import PIL.Image as _PILImage
import PIL.ImageTk as _PILImageTk

_CMD: "queue.Queue[str]" = queue.Queue()
_FRAMES: "queue.Queue[bytes]" = queue.Queue(maxsize=2)
_PUSH_TIMES: "queue.Queue[float]" = queue.Queue(maxsize=130)  # ~4s rolling @30fps
_LOCK = threading.Lock()
_OPEN = False
_THREAD: Optional[threading.Thread] = None


def is_open() -> bool:
    with _LOCK:
        return _OPEN


def push_frame_jpeg(jpeg_bytes: bytes) -> None:
    """Feed a JPEG frame (called from the capture thread; cheap when closed)."""
    if not is_open():
        return
    now = time.monotonic()
    if _PUSH_TIMES.full():
        try:
            _PUSH_TIMES.get_nowait()
        except queue.Empty:
            pass
    _PUSH_TIMES.put_nowait(now)
    if _FRAMES.full():
        try:
            _FRAMES.get_nowait()  # drop oldest — newest frame wins
        except queue.Empty:
            pass
    _FRAMES.put_nowait(jpeg_bytes)


def _feed_fps() -> int:
    """Frames pushed in the last second (capture-side health)."""
    now = time.monotonic()
    n = 0
    try:
        for t in list(_PUSH_TIMES.queue):
            if now - t <= 1.0:
                n += 1
    except Exception:
        pass
    return n


def toggle() -> bool:
    """Show/hide the floating window. Returns True when now visible."""
    global _OPEN, _THREAD
    with _LOCK:
        if _OPEN:
            _OPEN = False
            _CMD.put("hide")
            return False
        _OPEN = True
        _CMD.put("show")
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = threading.Thread(
                target=_run_tk, daemon=True, name="floating-viewer"
            )
            _THREAD.start()
        return True


def stop() -> None:
    """Hide and request the window thread to quit (app teardown)."""
    global _OPEN
    with _LOCK:
        _OPEN = False
    try:
        _CMD.put("quit")
    except Exception:
        pass


def _run_tk() -> None:
    import tkinter as tk

    root = tk.Tk()
    root.title("Video Viewer")
    root.geometry("854x480")
    root.configure(bg="#101112")
    root.minsize(240, 160)
    label = tk.Label(root, bg="#101112", bd=0, highlightthickness=0)
    label.pack(fill=tk.BOTH, expand=True)

    state = {
        "img": _PILImage.new("RGB", (1, 1), (30, 31, 34)),
        "photo": None,
        "last_bytes": None,
        "seq": -1,
        "drawn": 0,
        "title_at": time.monotonic(),
        "disp_fps": 0,
        "render_t": 0.0,
    }

    def render() -> None:
        """Re-render the cached frame scaled to fit the window (CONTAIN)."""
        try:
            img = state["img"]
            ow, oh = img.size
            if not ow or not oh:
                return
            W, H = root.winfo_width(), root.winfo_height()
            if W < 4 or H < 4:
                return
            scale = min(W / ow, H / oh, 2.0)  # never upscale more than 2x
            nw, nh = max(1, int(ow * scale)), max(1, int(oh * scale))
            resized = img.resize((nw, nh), _PILImage.Resampling.BILINEAR)
            state["photo"] = _PILImageTk.PhotoImage(resized)
            label.configure(image=state["photo"])
            state["drawn"] += 1
        except Exception:
            pass

    def on_configure(_e) -> None:
        now = time.monotonic()
        if now - state["render_t"] >= 0.06:  # throttle resize re-renders
            state["render_t"] = now
            render()

    def on_close() -> None:
        with _LOCK:
            global _OPEN
            _OPEN = False
        root.withdraw()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.bind("<Configure>", on_configure)

    def poll() -> None:
        # 1) process show/hide/quit commands
        try:
            while True:
                cmd = _CMD.get_nowait()
                if cmd == "quit":
                    root.destroy()
                    return
                if cmd == "show":
                    root.deiconify()
                elif cmd == "hide":
                    root.withdraw()
        except queue.Empty:
            pass

        # 2) drain new frames (newest wins)
        if is_open():
            seq = state["seq"]
            while True:
                try:
                    data = _FRAMES.get_nowait()
                    seq += 1
                    state["last_bytes"] = data
                except queue.Empty:
                    break
            if state["last_bytes"] is not None and seq > state["seq"]:
                try:
                    img = _PILImage.open(io.BytesIO(state["last_bytes"])).convert("RGB")
                    state["img"] = img
                    state["seq"] = seq
                    render()
                except Exception:
                    pass

        # 3) title HUD once per second
        now = time.monotonic()
        if now - state["title_at"] >= 1.0:
            state["disp_fps"] = state["drawn"]
            state["drawn"] = 0
            state["title_at"] = now
            try:
                root.title(
                    f"Video Viewer — {state['disp_fps']} fps (feed {_feed_fps()})"
                )
            except Exception:
                pass
        root.after(20, poll)

    root.after(20, poll)
    root.mainloop()