"""Desktop capture for Labhair-liom screen share — Windows / macOS / Linux.

Backend priority is **platform-aware**:

  Windows  → mss (DXGI/GDI, fast, 30+ fps capable) → dxcam → ImageMagick
  macOS    → mss → screencapture (built-in) → ImageMagick
  Linux    → gpu-screen-recorder → grim → spectacle → mss → ImageMagick
           (gpu-screen-recorder is GPU-accelerated, works on Wayland)
           (mss is often black on Wayland; tried last there)

All paths produce grayscale uint8 frames for the Labhair-liom encoder.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np


@dataclass
class Region:
    left: int
    top: int
    width: int
    height: int


_capture_color: bool = False  # set True to get BGR frames from backends that support it


def _is_wayland() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY")) or (
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    )


def _platform() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _bgra_or_rgb_to_gray(arr: np.ndarray, bgr: bool = False) -> np.ndarray:
    if arr.ndim == 2:
        return arr.astype(np.uint8)
    if arr.ndim != 3:
        raise ValueError(f"unexpected image shape {arr.shape}")
    if arr.shape[2] >= 3:
        c0 = arr[:, :, 0].astype(np.float32)
        c1 = arr[:, :, 1].astype(np.float32)
        c2 = arr[:, :, 2].astype(np.float32)
        if bgr:
            gray = 0.114 * c0 + 0.587 * c1 + 0.299 * c2
        else:
            gray = 0.299 * c0 + 0.587 * c1 + 0.114 * c2
        return np.clip(gray, 0, 255).astype(np.uint8)
    return arr[:, :, 0].astype(np.uint8)


def _frame_ok(gray: np.ndarray, min_mean: float = 1.0, min_std: float = 0.5) -> bool:
    if gray.size == 0:
        return False
    return float(gray.mean()) >= min_mean and float(gray.std()) >= min_std


def _load_png(path: str) -> np.ndarray:
    from PIL import Image

    with Image.open(path) as im:
        arr = np.array(im.convert("RGB"))
    return _bgra_or_rgb_to_gray(arr, bgr=False)


def _load_png_bgr(path: str) -> np.ndarray:
    """Load a PNG as BGR uint8 (OpenCV convention)."""
    from PIL import Image

    with Image.open(path) as im:
        arr = np.array(im.convert("RGB"))
    return arr[:, :, ::-1].copy()  # RGB → BGR


# ----- backends --------------------------------------------------------------


def _grab_mss(monitor: int, region: Region | None) -> np.ndarray:
    from mss import MSS

    with MSS() as sct:
        if region is not None:
            shot = sct.grab(
                {
                    "left": region.left,
                    "top": region.top,
                    "width": region.width,
                    "height": region.height,
                }
            )
        else:
            mons = sct.monitors
            idx = monitor if 0 <= monitor < len(mons) else (1 if len(mons) > 1 else 0)
            shot = sct.grab(mons[idx])
        bgra = np.array(shot, dtype=np.uint8)
        gray = _bgra_or_rgb_to_gray(bgra, bgr=True)
        if not _frame_ok(gray):
            raise RuntimeError("mss returned black/empty frame (common on Wayland)")
        return gray


def _grab_dxcam(monitor: int, region: Region | None) -> np.ndarray:
    """Windows DXGI desktop duplication — optional high-FPS path."""
    if sys.platform != "win32":
        raise RuntimeError("dxcam is Windows-only")
    try:
        import dxcam  # type: ignore
    except ImportError as exc:
        raise RuntimeError("dxcam not installed (pip install dxcam)") from exc

    # dxcam output index is 0-based physical outputs; map our monitor index
    out_idx = max(0, monitor - 1) if monitor > 0 else 0
    cam = getattr(_grab_dxcam, "_cam", None)
    if cam is None or getattr(_grab_dxcam, "_out_idx", None) != out_idx:
        cam = dxcam.create(output_idx=out_idx, output_color="BGR")
        _grab_dxcam._cam = cam  # type: ignore[attr-defined]
        _grab_dxcam._out_idx = out_idx  # type: ignore[attr-defined]

    if region is not None:
        frame = cam.grab(
            region=(
                region.left,
                region.top,
                region.left + region.width,
                region.top + region.height,
            )
        )
    else:
        frame = cam.grab()
    if frame is None:
        raise RuntimeError("dxcam grab returned None")
    gray = _bgra_or_rgb_to_gray(np.asarray(frame), bgr=True)
    if not _frame_ok(gray):
        raise RuntimeError("dxcam empty frame")
    return gray


def _grab_screencapture(monitor: int, region: Region | None) -> np.ndarray:
    """macOS built-in `/usr/sbin/screencapture` (requires Screen Recording permission)."""
    if sys.platform != "darwin":
        raise RuntimeError("screencapture is macOS-only")
    bin_path = "/usr/sbin/screencapture"
    if not os.path.isfile(bin_path):
        bin_path = shutil.which("screencapture") or ""
    if not bin_path:
        raise RuntimeError("screencapture not found")

    fd, path = tempfile.mkstemp(suffix=".png", prefix="labhairliom-mac-")
    os.close(fd)
    try:
        cmd = [bin_path, "-x"]  # no shutter sound
        if region is not None:
            # -R x,y,w,h
            cmd += ["-R", f"{region.left},{region.top},{region.width},{region.height}"]
        # display id: screencapture -D <display> (1-based)
        elif monitor > 0:
            cmd += ["-D", str(monitor)]
        cmd.append(path)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if r.returncode != 0 or not os.path.isfile(path) or os.path.getsize(path) < 32:
            err = (r.stderr or r.stdout or "screencapture failed").strip()
            raise RuntimeError(err or "screencapture failed (check Screen Recording permission)")
        gray = _load_png(path)
        if not _frame_ok(gray):
            raise RuntimeError("screencapture empty frame")
        return gray
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _gsr_monitor_name(index: int) -> str:
    """Resolve a 1-based monitor index to a gpu-screen-recorder monitor name."""
    r = subprocess.run(
        ["gpu-screen-recorder", "--list-monitors"],
        capture_output=True, text=True, timeout=5,
    )
    names = []
    for line in r.stdout.strip().splitlines():
        name = line.split("|", 1)[0].strip()
        if name:
            names.append(name)
    if not names:
        raise RuntimeError("gpu-screen-recorder: no monitors found")
    idx = index - 1  # convert 1-based user index to 0-based list index
    if idx < 0 or idx >= len(names):
        raise RuntimeError(
            f"gpu-screen-recorder: monitor {index} out of range (found {len(names)})"
        )
    return names[idx]


def _grab_gpu_screen_recorder(monitor: int, region: Region | None) -> np.ndarray:
    """Capture via gpu-screen-recorder — GPU-accelerated, works on Wayland.

    Spawns a short-lived recording to a temp PNG, then reads it back.
    Falls back if gpu-screen-recorder is not available.
    """
    if not shutil.which("gpu-screen-recorder"):
        raise RuntimeError("gpu-screen-recorder not installed")

    if monitor > 0:
        target = _gsr_monitor_name(monitor)
    else:
        target = "screen"
    crop_args = []
    if region is not None:
        crop_args = ["-region", f"{region.width}x{region.height}+{region.left}+{region.top}"]

    fd, path = tempfile.mkstemp(suffix=".png", prefix="labhairliom-gsr-")
    os.close(fd)
    try:
        cmd = (
            ["gpu-screen-recorder", "-w", target]
            + crop_args
            + ["-c", "png", "-f", "1", "-q", "high", "-o", path]
        )
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=3)
        if not os.path.isfile(path) or os.path.getsize(path) < 32:
            stderr = proc.stderr.read().decode() if proc.stderr else ""
            raise RuntimeError(stderr.strip() or "gpu-screen-recorder failed")
        if _capture_color:
            bgr = _load_png_bgr(path)
            if not _frame_ok(bgr[:,:,0]):
                raise RuntimeError("gpu-screen-recorder returned empty frame")
            return bgr
        gray = _load_png(path)
        if not _frame_ok(gray):
            raise RuntimeError("gpu-screen-recorder returned empty frame")
        return gray
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _grab_grim(monitor: int, region: Region | None) -> np.ndarray:
    if not shutil.which("grim"):
        raise RuntimeError("grim not installed")
    fd, path = tempfile.mkstemp(suffix=".png", prefix="labhairliom-grim-")
    os.close(fd)
    try:
        cmd = ["grim"]
        if region is not None:
            cmd += ["-g", f"{region.left},{region.top} {region.width}x{region.height}"]
        cmd.append(path)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "grim failed")
        gray = _load_png(path)
        return _crop_if_needed(gray, monitor, None if region else None) if monitor > 0 and region is None else gray
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _grab_spectacle(monitor: int, region: Region | None) -> np.ndarray:
    if not shutil.which("spectacle"):
        raise RuntimeError("spectacle not installed")
    fd, path = tempfile.mkstemp(suffix=".png", prefix="labhairliom-spec-")
    os.close(fd)
    try:
        cmd = ["spectacle", "-b", "-n", "-o", path, "-f"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode != 0 or not os.path.isfile(path) or os.path.getsize(path) < 32:
            err = (r.stderr or r.stdout or "spectacle failed").strip()
            raise RuntimeError(err)
        gray = _load_png(path)
        return _crop_if_needed(gray, monitor, region)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _grab_imagemagick(monitor: int, region: Region | None) -> np.ndarray:
    magick = shutil.which("magick")
    import_bin = shutil.which("import")
    fd, path = tempfile.mkstemp(suffix=".png", prefix="labhairliom-im-")
    os.close(fd)
    try:
        if magick:
            cmd = [magick, "import", "-window", "root"]
            if region is not None:
                cmd += ["-crop", f"{region.width}x{region.height}+{region.left}+{region.top}"]
            cmd.append(path)
        elif import_bin:
            cmd = [import_bin, "-window", "root"]
            if region is not None:
                cmd += ["-crop", f"{region.width}x{region.height}+{region.left}+{region.top}"]
            cmd.append(path)
        else:
            raise RuntimeError("ImageMagick not installed")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode != 0 or not os.path.isfile(path):
            raise RuntimeError((r.stderr or "import failed").strip())
        gray = _load_png(path)
        if region is None:
            gray = _crop_if_needed(gray, monitor, None)
        if not _frame_ok(gray):
            raise RuntimeError("ImageMagick capture empty")
        return gray
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _monitor_geometry(index: int) -> dict | None:
    try:
        from mss import MSS

        with MSS() as sct:
            mons = sct.monitors
            if 0 <= index < len(mons):
                m = mons[index]
                return {
                    "left": int(m["left"]),
                    "top": int(m["top"]),
                    "width": int(m["width"]),
                    "height": int(m["height"]),
                }
    except Exception:
        pass
    return None


def _crop_if_needed(
    gray: np.ndarray, monitor: int, region: Region | None
) -> np.ndarray:
    if region is not None:
        h, w = gray.shape[:2]
        geo0 = _monitor_geometry(0)
        if geo0 and region.left >= geo0["left"] and region.top >= geo0["top"]:
            x = region.left - geo0["left"]
            y = region.top - geo0["top"]
        else:
            x, y = region.left, region.top
        x2 = min(w, x + region.width)
        y2 = min(h, y + region.height)
        x = max(0, min(x, w - 1))
        y = max(0, min(y, h - 1))
        if x2 > x and y2 > y:
            return gray[y:y2, x:x2]
        return gray

    if monitor <= 0:
        return gray
    geo = _monitor_geometry(monitor)
    geo0 = _monitor_geometry(0)
    if not geo or not geo0:
        return gray
    x = geo["left"] - geo0["left"]
    y = geo["top"] - geo0["top"]
    h, w = gray.shape[:2]
    if abs(w - geo["width"]) < 8 and abs(h - geo["height"]) < 8:
        return gray
    x2 = min(w, x + geo["width"])
    y2 = min(h, y + geo["height"])
    x = max(0, x)
    y = max(0, y)
    if x2 > x and y2 > y:
        return gray[y:y2, x:x2]
    return gray


BackendFn = Callable[[int, Region | None], np.ndarray]


class _PersistentGSR:
    """Keeps gpu-screen-recorder running as a persistent process, decodes via ffmpeg pipe.

    Instead of spawning a new gsr process per frame (~440ms each), this keeps one gsr
    process alive streaming mpegts to stdout, piped to ffmpeg for real-time decode.
    Achieves ~27fps vs ~2fps with per-frame spawning.
    """

    def __init__(self) -> None:
        self._gsr_proc: subprocess.Popen | None = None
        self._ffmpeg_proc: subprocess.Popen | None = None
        self._reader_thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()
        self._latest: np.ndarray | None = None
        self._width: int = 0
        self._height: int = 0

    def start(self, monitor: int = 1, width: int = 640, height: int = 360) -> None:
        if self._running:
            return
        if not shutil.which("gpu-screen-recorder"):
            raise RuntimeError("gpu-screen-recorder not installed")

        target = _gsr_monitor_name(monitor) if monitor > 0 else "screen"
        self._width = width
        self._height = height
        self._running = True

        self._gsr_proc = subprocess.Popen(
            [
                "gpu-screen-recorder", "-w", target,
                "-c", "mpegts", "-f", "30", "-q", "high",
                "-o", "/dev/stdout",
            ],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )

        self._ffmpeg_proc = subprocess.Popen(
            [
                "ffmpeg",
                "-fflags", "nobuffer+discardcorrupt",
                "-flags", "low_delay",
                "-probesize", "32",
                "-analyzeduration", "0",
                "-i", "pipe:0",
                "-f", "rawvideo",
                "-pix_fmt", "bgr24",
                "-vf", f"scale={width}:{height}",
                "-an",
                "pipe:1",
            ],
            stdin=self._gsr_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._gsr_proc.stdout.close()

        self._reader_thread = threading.Thread(
            target=self._read_loop, daemon=True, name="labhairliom-gsr-decode"
        )
        self._reader_thread.start()

    def _read_loop(self) -> None:
        """Read raw BGR frames from ffmpeg stdout."""
        frame_size = self._width * self._height * 3
        buf = b""
        while self._running:
            try:
                needed = frame_size - len(buf)
                data = self._ffmpeg_proc.stdout.read(needed) if needed > 0 else b""
                if not data:
                    break
                buf += data
                if len(buf) >= frame_size:
                    arr = np.frombuffer(buf[:frame_size], dtype=np.uint8).reshape(
                        self._height, self._width, 3
                    ).copy()
                    with self._lock:
                        self._latest = arr
                    buf = buf[frame_size:]
            except Exception:
                break

    def get_latest(self) -> np.ndarray | None:
        with self._lock:
            return self._latest

    def stop(self) -> None:
        self._running = False
        for proc in (self._ffmpeg_proc, self._gsr_proc):
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=3)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        self._gsr_proc = None
        self._ffmpeg_proc = None
        self._latest = None


# --- xdg-desktop-portal ScreenCast (Discord/OBS method, works on Wayland) ---

_PORTAL_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "portal_capture.py")


def _find_portal_python() -> str:
    """Find a python interpreter that has dbus + gi (needed by portal_capture.py)."""
    cands = [shutil.which("python3"), "/usr/bin/python3", shutil.which("python")]
    for cand in cands:
        if not cand:
            continue
        try:
            r = subprocess.run(
                [cand, "-c", "import dbus, gi"],
                capture_output=True, timeout=10,
            )
        except Exception:
            continue
        if r.returncode == 0:
            return cand
    raise RuntimeError("portal screen capture needs dbus + gi (not found in any python)")


def _portal_available() -> bool:
    if not _is_wayland():
        return False
    if not shutil.which("gst-launch-1.0"):
        return False
    try:
        _find_portal_python()
        return True
    except RuntimeError:
        return False


def _portal_placeholder(monitor: int, region: Region | None) -> np.ndarray:
    """``portal`` is interactive-only (pops the portal picker); no single grab."""
    raise RuntimeError(
        "portal screen capture is interactive — start_streaming() shows the "
        "system picker, use that instead of grab()"
    )


class _PersistentPortal:
    """Screen capture via xdg-desktop-portal ScreenCast D-Bus API.

    Runs ``portal_capture.py`` (which lives in the same process tree as
    ``gst-launch-1.0`` so the PipeWire fd stays valid), then reads raw BGR
    frames from its stdout. Same capture path as Discord and OBS.
    """

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._reader_thread: threading.Thread | None = None
        self._stderr_drain: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()
        self._latest: np.ndarray | None = None
        self._width: int = 0
        self._height: int = 0
        self.last_error: str = ""
        self._stderr_lines: list[bytes] = []

    def _drain_stderr(self) -> None:
        """Continuously drain the portal subprocess's stderr into a buffer."""
        try:
            for line in iter(self._proc.stderr.readline, b""):
                self._stderr_lines.append(line)
        except Exception:
            pass

    def _stderr_text(self) -> str:
        return "".join(l.decode(errors="replace") for l in self._stderr_lines).strip()

    def start(self, monitor: int = 1, width: int = 640, height: int = 360) -> None:
        if self._running:
            return
        try:
            py = _find_portal_python()
        except RuntimeError as exc:
            raise RuntimeError(f"portal backend unavailable: {exc}") from exc

        env = dict(os.environ)
        env["LABHAIR_LIOM_PORTAL_WIDTH"] = str(width)
        env["LABHAIR_LIOM_PORTAL_HEIGHT"] = str(height)

        self._stderr_lines.clear()
        self._proc = subprocess.Popen(
            [py, _PORTAL_SCRIPT],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        self._stderr_drain = threading.Thread(
            target=self._drain_stderr, daemon=True, name="labhairliom-portal-stderr"
        )
        self._stderr_drain.start()
        try:
            # portal_capture.py prints "READY <w> <h>" after the user picks a screen
            line = self._proc.stdout.readline()
        except Exception as exc:
            self._proc.kill()
            self._proc = None
            raise RuntimeError(f"portal capture failed to start: {exc}") from exc
        if not line.startswith(b"READY"):
            err_line = line.decode(errors="replace").strip()
            if err_line.startswith("ERROR:"):
                err_line = err_line[len("ERROR:"):].strip()
            stderr_text = self._stderr_text()
            exitcode = self._proc.poll()
            # terminate the subprocess (still draining stderr in the background)
            try:
                self._proc.terminate()
            except Exception:
                pass
            self._proc = None
            if err_line:
                err = err_line
            elif stderr_text:
                err = stderr_text[-500:]
            elif exitcode is not None and exitcode != 0:
                err = f"portal process exited with code {exitcode}"
            else:
                err = "screen picker was closed or cancelled"
            self.last_error = err
            raise RuntimeError(f"portal capture failed: {err}")
        try:
            _, w, h = line.split()
            self._width, self._height = int(w), int(h)
        except Exception:
            self._proc.terminate()
            self._proc = None
            raise RuntimeError("portal capture sent malformed READY line")

        self._running = True
        self._reader_thread = threading.Thread(
            target=self._read_loop, daemon=True, name="labhairliom-portal-decode"
        )
        self._reader_thread.start()

    def _read_loop(self) -> None:
        """Read raw BGR frames from the portal capture subprocess."""
        frame_size = self._width * self._height * 3
        buf = b""
        while self._running:
            try:
                needed = frame_size - len(buf)
                data = self._proc.stdout.read(needed) if needed > 0 else b""
                if not data:
                    break
                buf += data
                if len(buf) >= frame_size:
                    arr = np.frombuffer(buf[:frame_size], dtype=np.uint8).reshape(
                        self._height, self._width, 3
                    ).copy()
                    with self._lock:
                        self._latest = arr
                    buf = buf[frame_size:]
            except Exception:
                break
        # Capture why the capture ended, if the subprocess failed after READY
        try:
            code = self._proc.poll()
        except Exception:
            code = None
        if code is not None and code != 0:
            stderr_text = self._stderr_text()
            if not stderr_text:
                stderr_text = f"portal process exited with code {code}"
            self.last_error = stderr_text[-500:]

    def get_latest(self) -> np.ndarray | None:
        with self._lock:
            return self._latest

    def stderr_text(self) -> str:
        """Contents of the drained subprocess stderr (portal + gst-launch)."""
        return self._stderr_text()

    def stop(self) -> None:
        self._running = False
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = None
        self._latest = None
        if self._stderr_drain and self._stderr_drain.is_alive():
            self._stderr_drain.join(timeout=1)
            self._stderr_drain = None


# name → (fn, typical max fps for auto-cap)
ALL_BACKENDS: dict[str, tuple[BackendFn, int]] = {
    "portal": (_portal_placeholder, 30),
    "gpu-screen-recorder": (_grab_gpu_screen_recorder, 30),
    "mss": (_grab_mss, 30),
    "dxcam": (_grab_dxcam, 60),
    "screencapture": (_grab_screencapture, 8),
    "grim": (_grab_grim, 15),
    "spectacle": (_grab_spectacle, 2),
    "imagemagick": (_grab_imagemagick, 3),
}


def _default_order() -> list[str]:
    plat = _platform()
    if plat == "windows":
        return ["mss", "dxcam", "imagemagick"]
    if plat == "macos":
        return ["mss", "screencapture", "imagemagick"]
    # linux
    if _is_wayland():
        return ["portal", "gpu-screen-recorder"]
    return ["mss", "grim", "spectacle", "imagemagick"]


class ScreenGrabber:
    """Probe once, then grab frames with the chosen backend."""

    def __init__(self, preferred: str | None = None) -> None:
        self.backend_name: str | None = None
        self._grab: BackendFn | None = None
        self._preferred = preferred
        self.last_error: str = ""
        self.max_fps: int = 15
        self._stream_thread: threading.Thread | None = None
        self._stream_running = False
        self._stream_lock = threading.Lock()
        self._stream_latest: np.ndarray | None = None
        self._stream_monitor: int = 1
        self._stream_region: Region | None = None
        self._stream_color: bool = False
        self._persistent_gsr: _PersistentGSR | None = None
        self._persistent_portal: _PersistentPortal | None = None

    def probe(self, monitor: int = 1) -> str:
        order = _default_order()
        if self._preferred and self._preferred in ALL_BACKENDS:
            order = [self._preferred] + [n for n in order if n != self._preferred]

        errors: list[str] = []
        for name in order:
            if name == "portal":
                # interactive backend: verify the toolchain without popping the picker
                if _portal_available():
                    self.backend_name = name
                    self._grab = None
                    self.max_fps = 30
                    self.last_error = ""
                    return name
                errors.append("portal: dbus/gi/gst not available")
                continue
            fn, max_fps = ALL_BACKENDS[name]
            try:
                frame = fn(monitor, None)
                if not _frame_ok(frame):
                    raise RuntimeError("empty/black frame")
                self.backend_name = name
                self._grab = fn
                self.max_fps = max_fps
                self.last_error = ""
                return name
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        self.last_error = "; ".join(errors)
        plat = _platform()
        hint = {
            "windows": "Install mss (pip) — works out of the box. Optional: pip install dxcam for higher FPS.",
            "macos": "Grant Screen Recording permission to your terminal (System Settings → Privacy). mss or screencapture.",
            "linux": "X11: mss. Wayland: gpu-screen-recorder (GPU-accelerated) or grim/spectacle.",
        }.get(plat, "")
        raise RuntimeError(
            f"no working screen capture backend on {plat}. {hint} Tried: {self.last_error}"
        )

    def start_streaming(
        self,
        monitor: int = 1,
        region: Region | None = None,
        color: bool = False,
        width: int = 640,
        height: int = 360,
    ) -> None:
        """Start a background thread that continuously captures frames."""
        if self._stream_running:
            return
        if self._grab is None:
            self.probe(monitor=monitor)
        self._stream_monitor = monitor
        self._stream_region = region
        self._stream_color = color
        self._stream_running = True

        # For gpu-screen-recorder, use the persistent pipe-based capture (~27fps vs ~2fps)
        if self.backend_name == "gpu-screen-recorder":
            try:
                self._persistent_gsr = _PersistentGSR()
                self._persistent_gsr.start(monitor=monitor)
                return  # no need for stream thread — GSR decode thread feeds get_latest()
            except Exception:
                self._persistent_gsr = None

        # For portal, show the system screen picker and stream frames via PipeWire.
        if self.backend_name == "portal":
            try:
                self._persistent_portal = _PersistentPortal()
                self._persistent_portal.start(
                    monitor=monitor, width=width, height=height
                )
                return  # portal decode thread feeds get_latest()
            except Exception as exc:
                self._persistent_portal = None
                self._stream_running = False
                raise RuntimeError(f"portal screen share failed: {exc}") from exc

        self._stream_thread = threading.Thread(
            target=self._stream_loop, daemon=True, name="labhairliom-capture"
        )
        self._stream_thread.start()

    def _stream_loop(self) -> None:
        while self._stream_running:
            try:
                if self._stream_color:
                    global _capture_color
                    _capture_color = True
                    try:
                        frame = self._grab(self._stream_monitor, self._stream_region)
                    finally:
                        _capture_color = False
                    if frame.ndim == 2:
                        import cv2
                        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                    elif frame.ndim == 3 and frame.shape[2] == 4:
                        import cv2
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                else:
                    frame = self._grab(self._stream_monitor, self._stream_region)
                with self._stream_lock:
                    self._stream_latest = frame
            except Exception:
                time.sleep(0.05)

    def get_latest(self) -> np.ndarray | None:
        """Return the latest frame from the streaming capture thread (or None)."""
        if self._persistent_portal is not None:
            return self._persistent_portal.get_latest()
        if self._persistent_gsr is not None:
            return self._persistent_gsr.get_latest()
        with self._stream_lock:
            return self._stream_latest

    def diagnostics(self) -> str:
        """Best-effort diagnostic text about the active capture backend."""
        parts: list[str] = []
        if self._persistent_portal is not None:
            try:
                pool = self._persistent_portal
                if pool.last_error:
                    parts.append(f"portal: {pool.last_error}")
                txt = pool.stderr_text()
                if txt:
                    parts.append(f"portal/gst stderr: {txt[-4000:]}")
            except Exception:
                pass
        if self._persistent_gsr is not None:
            try:
                if self._persistent_gsr.last_error:
                    parts.append(f"gpu-screen-recorder: {self._persistent_gsr.last_error}")
            except Exception:
                pass
        return "; ".join(parts)

    def stop_streaming(self) -> None:
        """Stop the background capture thread."""
        self._stream_running = False
        if self._persistent_portal is not None:
            self._persistent_portal.stop()
            self._persistent_portal = None
        if self._persistent_gsr is not None:
            self._persistent_gsr.stop()
            self._persistent_gsr = None
        if self._stream_thread and self._stream_thread.is_alive():
            self._stream_thread.join(timeout=3.0)
        self._stream_thread = None
        self._stream_latest = None

    def grab(self, monitor: int = 1, region: Region | None = None) -> np.ndarray:
        if self._grab is None:
            self.probe(monitor=monitor)
        assert self._grab is not None
        return self._grab(monitor, region)

    def grab_color(self, monitor: int = 1, region: Region | None = None) -> np.ndarray:
        """Grab a frame in color (BGR). Falls back to grayscale→BGR if unsupported."""
        global _capture_color
        _capture_color = True
        try:
            frame = self.grab(monitor=monitor, region=region)
        finally:
            _capture_color = False
        if frame.ndim == 2:
            import cv2
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        return frame


def list_monitors() -> list[dict]:
    out: list[dict] = []
    try:
        from mss import MSS

        with MSS() as sct:
            for i, m in enumerate(sct.monitors):
                item = {
                    "index": i,
                    "left": int(m["left"]),
                    "top": int(m["top"]),
                    "width": int(m["width"]),
                    "height": int(m["height"]),
                }
                if i == 0:
                    item["label"] = "all"
                else:
                    item["label"] = m.get("output") or f"monitor-{i}"
                    item["primary"] = bool(m.get("is_primary"))
                out.append(item)
            return out
    except Exception:
        pass
    return [{"index": 0, "left": 0, "top": 0, "width": 1920, "height": 1080, "label": "all"}]


def backend_status() -> str:
    g = ScreenGrabber()
    try:
        name = g.probe()
        t0 = time.time()
        frame = g.grab()
        dt = time.time() - t0
        return (
            f"platform={_platform()}  backend={name}  max_fps≈{g.max_fps}  "
            f"frame={frame.shape[1]}x{frame.shape[0]}  mean={frame.mean():.1f}  "
            f"grab={dt*1000:.0f}ms  wayland={_is_wayland()}"
        )
    except Exception as exc:
        return f"platform={_platform()}  backend=NONE  error={exc}  wayland={_is_wayland()}"
