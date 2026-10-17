"""Android camera (Camera1 API) + screen capture (MediaProjection) via pyjnius.

Camera1 is used instead of Camera2 because pyjnius PythonJavaClass can only
proxy Java interfaces, and Camera2's StateCallback is an abstract class.
Camera1's PreviewCallback is an interface, so it works.

Preview surface is created via ImageReader.getSurface() and passed to Camera
via a SurfaceHolder proxy (also an interface), avoiding SurfaceTexture and
reflection entirely.

Screen capture uses MediaProjection API with user consent dialog and a
foreground service (required on Android 14+).
"""

from __future__ import annotations

import io
import threading
import time
import traceback
from typing import Callable, Optional

import numpy as np

try:
    from jnius import autoclass, cast, PythonJavaClass, java_method
    _ANDROID = True
except ImportError:
    _ANDROID = False

try:
    from PIL import Image
    _PIL = True
except ImportError:
    _PIL = False


def _write_crash(msg: str) -> None:
    import os as _os
    for p in ("/sdcard/Download/labhairliom_crash.txt",
              _os.path.join(_os.path.expanduser("~"), "labhairliom_crash.txt")):
        try:
            with open(p, "a") as _f:
                _f.write(msg + "\n")
            break
        except Exception:
            continue


if _ANDROID:
    PythonActivity = autoclass("org.kivy.android.PythonActivity")


class _PreviewCallbackImpl(PythonJavaClass):
    """Camera1 preview callback — stashes raw NV21 data for a worker thread.

    The callback runs on Camera1's internal thread and must return quickly
    to avoid buffer starvation.  Heavy work (NV21→RGB, encoding, network
    send) happens in _worker_thread.
    """
    __javainterfaces__ = ["android/hardware/Camera$PreviewCallback"]
    __javainterargs__ = ()

    def __init__(self, width: int, height: int):
        super().__init__()
        self.width = width
        self.height = height
        self._frame_count = 0
        self._latest_data: Optional[bytes] = None
        self._data_lock = threading.Lock()

    @java_method("([BLandroid/hardware/Camera;)V")
    def onPreviewFrame(self, data, camera):
        if data is None or camera is None:
            return
        try:
            raw = bytes(data)
            self._frame_count += 1
            if self._frame_count == 1:
                _write_crash(f"camera: first preview frame OK ({self.width}x{self.height}, {len(raw)} bytes)")
            with self._data_lock:
                self._latest_data = raw
        except Exception as exc:
            _write_crash(f"camera: onPreviewFrame error: {exc}")

    @staticmethod
    def _nv21_to_rgb(data, width: int, height: int) -> np.ndarray:
        yuv = np.frombuffer(bytes(data), dtype=np.uint8)
        frame_size = width * height
        if len(yuv) < frame_size * 3 // 2:
            padded = np.zeros(frame_size * 3 // 2, dtype=np.uint8)
            padded[:len(yuv)] = yuv[:len(padded)]
            yuv = padded

        y = yuv[:frame_size].reshape((height, width)).astype(np.float32)
        uv = yuv[frame_size:].reshape((height // 2, width // 2, 2))
        u = uv[:, :, 0].astype(np.float32)
        v = uv[:, :, 1].astype(np.float32)
        u_full = np.repeat(np.repeat(u, 2, axis=0), 2, axis=1)[:height, :width]
        v_full = np.repeat(np.repeat(v, 2, axis=0), 2, axis=1)[:height, :width]
        r = np.clip(y + 1.402 * (v_full - 128), 0, 255).astype(np.uint8)
        g = np.clip(y - 0.344136 * (u_full - 128) - 0.714136 * (v_full - 128), 0, 255).astype(np.uint8)
        b = np.clip(y + 1.772 * (u_full - 128), 0, 255).astype(np.uint8)
        return np.stack([r, g, b], axis=2)


class _SurfaceHolderProxy(PythonJavaClass):
    """Minimal SurfaceHolder proxy — Camera1 only needs getSurface().

    SurfaceHolder is an interface, so PythonJavaClass can proxy it.
    This avoids calling the hidden Camera.setPreviewSurface() via reflection.
    """
    __javainterfaces__ = ["android/view/SurfaceHolder"]
    __javainterargs__ = ()

    def __init__(self, surface):
        super().__init__()
        self._surface = surface

    @java_method("()Landroid/view/Surface;")
    def getSurface(self):
        return self._surface


def _get_preview_surface(width: int, height: int):
    """Create a Surface for Camera1 preview using ImageReader.

    Returns (surface, image_reader) or (None, None) on failure.
    """
    try:
        ImageReader = autoclass("android.media.ImageReader")
        # YUV_420_888 = 0x23 = 35
        image_reader = ImageReader.newInstance(width, height, 0x23, 1)
        surface = image_reader.getSurface()
        _write_crash(f"camera: ImageReader Surface created ({width}x{height})")
        return surface, image_reader
    except Exception as exc:
        _write_crash(f"camera: ImageReader Surface failed: {exc}")
        return None, None


class AndroidCamera:
    """Camera capture using Android Camera1 API via pyjnius.

    Opens the front/back camera, sets up preview, and delivers
    RGB numpy arrays to the frame callback.
    """

    def __init__(self) -> None:
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._frame_cb: Optional[Callable] = None
        self._camera = None
        self._image_reader = None
        self.last_error: Optional[str] = None
        self._lock = threading.Lock()

    def start(self, frame_cb: Callable = None, width: int = 640, height: int = 480) -> None:
        self._running = True
        self._frame_cb = frame_cb
        self._thread = threading.Thread(target=self._loop, args=(width, height), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        time.sleep(0.1)
        self._close()

    def _close(self) -> None:
        cam = self._camera
        self._camera = None
        if cam is not None:
            try:
                cam.setPreviewCallback(None)
                cam.stopPreview()
                cam.release()
            except Exception:
                pass
        ir = self._image_reader
        self._image_reader = None
        if ir is not None:
            try:
                ir.close()
            except Exception:
                pass

    def _loop(self, width: int, height: int) -> None:
        if not _ANDROID or not _PIL:
            msg = "[android-camera] pyjnius/PIL not available"
            print(msg)
            _write_crash(msg)
            return
        try:
            _write_crash("camera thread starting (Camera1 API)")
            self._run_camera1(width, height)
        except Exception as exc:
            self.last_error = str(exc)
            _write_crash(f"camera thread CRASHED: {exc}")
            print(f"[android-camera] Camera1 error: {exc}", flush=True)

    def _run_camera1(self, width: int, height: int) -> None:
        Camera = autoclass("android.hardware.Camera")
        CameraInfo = autoclass("android.hardware.Camera$CameraInfo")
        _write_crash("camera: got Camera class")

        # Find front-facing camera or use camera 0
        camera_id = 0
        for i in range(Camera.getNumberOfCameras()):
            info = CameraInfo()
            Camera.getCameraInfo(i, info)
            if info.facing == 1:  # CAMERA_FACING_FRONT
                camera_id = i
                break
        _write_crash(f"camera: using camera_id={camera_id}")

        self._camera = Camera.open(camera_id)
        _write_crash(f"camera: Camera.open({camera_id}) succeeded")

        # Set preview size
        params = self._camera.getParameters()
        best = None
        for sz in params.getSupportedPreviewSizes():
            if sz.width == width and sz.height == height:
                best = sz
                break
        if best is None:
            best = min(params.getSupportedPreviewSizes(),
                       key=lambda s: abs(s.width - width) + abs(s.height - height))
        params.setPreviewSize(best.width, best.height)
        self._camera.setParameters(params)
        _write_crash(f"camera: preview size set to {best.width}x{best.height}")

        # Create callback — stashes raw NV21 for worker thread
        cb = _PreviewCallbackImpl(best.width, best.height)

        # setPreviewCallback (deprecated) — Camera1 allocates its own buffers
        # and delivers every frame.  Avoids addCallbackBuffer issues through pyjnius
        # where recycling Java byte[] objects may silently fail.
        self._camera.setPreviewCallback(cb)

        # Create a Surface for preview via ImageReader + SurfaceHolder proxy
        surface, image_reader = _get_preview_surface(best.width, best.height)
        self._image_reader = image_reader  # keep reference for cleanup
        if surface is not None:
            holder = _SurfaceHolderProxy(surface)
            try:
                self._camera.setPreviewDisplay(holder)
                _write_crash("camera: setPreviewDisplay(holder) OK, starting preview")
            except Exception as exc:
                _write_crash(f"camera: setPreviewDisplay failed: {exc}")
        else:
            _write_crash("camera: no Surface available — cannot start preview")

        self._camera.startPreview()
        _write_crash("camera: preview started, worker thread processing frames")

        # Worker thread — picks up latest NV21 frame at its own pace,
        # does heavy NV21→RGB + encoding + callback on its own thread,
        # so Camera1 callback thread returns immediately.
        worker_count = 0
        while self._running:
            raw = None
            with cb._data_lock:
                raw = cb._latest_data
                cb._latest_data = None
            if raw is None:
                time.sleep(0.033)
                continue
            worker_count += 1
            if worker_count <= 3 or worker_count % 30 == 0:
                _write_crash(f"camera: worker picked up frame #{worker_count} "
                             f"(callback delivered {cb._frame_count} total)")
            try:
                rgb = _PreviewCallbackImpl._nv21_to_rgb(raw, best.width, best.height)
                with self._lock:
                    frame_cb = self._frame_cb
                if frame_cb:
                    frame_cb(rgb)
            except Exception as exc:
                _write_crash(f"camera: worker error: {exc}")

        self._close()
        _write_crash("camera: stopped")


class AndroidScreenCapture:
    """Screen capture via MediaProjection API (Android 5.0+).

    Requires user consent via a system dialog. On Android 14+ (API 34+),
    a foreground service with type mediaProjection must be running before
    creating the VirtualDisplay.
    """

    REQUEST_CODE = 0x5343  # "SC" — unique request code for the consent dialog

    def __init__(self) -> None:
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._frame_cb: Optional[Callable] = None
        self._projection = None
        self._image_reader = None
        self._virtual_display = None
        self.last_error: Optional[str] = None
        self._width = 640
        self._height = 360
        self._dpi = 160
        self._consent_event = threading.Event()
        self._consent_code = 0
        self._consent_intent = None

    def start(self, frame_cb: Callable = None, width: int = 640, height: int = 360,
              dpi: int = 160) -> None:
        if self._running:
            return
        self._running = True
        self._frame_cb = frame_cb
        self._width = width
        self._height = height
        self._dpi = dpi
        self._consent_event.clear()
        self._consent_code = 0
        self._consent_intent = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        self._cleanup()

    def _cleanup(self) -> None:
        for attr in ("_virtual_display", "_projection", "_image_reader"):
            obj = getattr(self, attr, None)
            if obj is not None:
                try:
                    obj.release()
                except Exception:
                    try:
                        obj.stop()
                    except Exception:
                        pass
                setattr(self, attr, None)
        _write_crash("screen: cleanup done")

    # ── main thread ──────────────────────────────────────────────────

    def _run(self) -> None:
        if not _ANDROID or not _PIL:
            msg = "[android-screen] pyjnius/PIL not available"
            print(msg)
            _write_crash(msg)
            return
        try:
            _write_crash("screen: requesting MediaProjection consent")
            self._start_fg_service()
            self._request_consent_ui()

            if not self._consent_event.wait(timeout=60):
                self.last_error = "Screen capture consent timeout"
                self._running = False
                _write_crash("screen: consent timeout")
                return

            if self._consent_code != -1 or self._consent_intent is None:
                self.last_error = "Screen capture permission denied"
                self._running = False
                _write_crash(f"screen: consent denied (code={self._consent_code})")
                return

            _write_crash("screen: consent granted, setting up capture")

            self._create_projection()
            self._capture_loop()

        except Exception as exc:
            self.last_error = str(exc)
            _write_crash(f"screen: thread error: {exc}\n{traceback.format_exc()}")
            print(f"[android-screen] error: {exc}", flush=True)
            self._running = False

    # ── consent ──────────────────────────────────────────────────────

    def _request_consent_ui(self) -> None:
        """Schedule the consent dialog on the Kivy/UI thread."""
        from kivy.clock import Clock

        def _do_request(_dt=None):
            try:
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                activity = PythonActivity.mActivity
                mgr = activity.getSystemService("media_projection")
                intent = mgr.createScreenCaptureIntent()

                try:
                    from android import activity as android_activity

                    def _on_result(requestCode, resultCode, intent_data):
                        self._consent_code = resultCode
                        self._consent_intent = intent_data
                        _write_crash(f"screen: _on_result(code={resultCode}, "
                                      f"intent_type={type(intent_data).__name__})")
                        self._consent_event.set()

                    android_activity.bind(on_activity_result=_on_result)
                    _write_crash("screen: bound to activity_result via android.activity")
                except Exception as bind_exc:
                    _write_crash(f"screen: android.activity.bind failed: {bind_exc}")

                activity.startActivityForResult(intent, self.REQUEST_CODE)
                _write_crash("screen: startActivityForResult called")

            except Exception as exc:
                _write_crash(f"screen: consent UI failed: {exc}")
                self.last_error = str(exc)
                self._consent_event.set()

        Clock.schedule_once(_do_request, 0)

    # ── foreground service ───────────────────────────────────────────

    def _start_fg_service(self) -> None:
        """Start a foreground service (required for MediaProjection on Android 14+).

        The Java MediaProjectionService must be compiled into the APK (via
        android.add_src in buildozer.spec) and declared in the manifest.
        It runs in the main process and calls startForeground() with
        FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION.
        """
        import os
        _write_crash(f"screen: _start_fg_service from PID {os.getpid()}")
        try:
            from client.android_app.foreground_service import start_media_projection_fg
            if start_media_projection_fg():
                _write_crash("screen: foreground service start OK, waiting for startForeground...")
                time.sleep(3.0)
                _write_crash("screen: foreground service wait done")
            else:
                _write_crash("screen: foreground service start returned False — "
                             "check if Java class is in APK")
        except Exception as exc:
            _write_crash(f"screen: foreground service error: {exc}\n{traceback.format_exc()}")

    # ── projection setup ─────────────────────────────────────────────

    def _create_projection(self) -> None:
        """Create MediaProjection on the main thread, then ImageReader + VirtualDisplay.

        getMediaProjection() must be called on the main thread.  We schedule
        it there via Clock.schedule_once and block until done.
        """
        from kivy.clock import Clock

        self._projection_ready = threading.Event()
        self._projection_error = [None]
        self._projection_obj = [None]

        def _do_create(_dt=None):
            try:
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                activity = PythonActivity.mActivity
                mgr = activity.getSystemService("media_projection")
                proj = mgr.getMediaProjection(self._consent_code, self._consent_intent)
                if proj is None:
                    self._projection_error[0] = "getMediaProjection returned null"
                    _write_crash("screen: getMediaProjection returned NULL")
                else:
                    self._projection_obj[0] = proj
                    _write_crash("screen: getMediaProjection OK")
            except Exception as exc:
                self._projection_error[0] = str(exc)
                _write_crash(f"screen: getMediaProjection exception: {exc}")
            finally:
                self._projection_ready.set()

        Clock.schedule_once(_do_create, 0)
        if not self._projection_ready.wait(timeout=10):
            raise RuntimeError("getMediaProjection timed out on main thread")

        if self._projection_error[0]:
            raise RuntimeError(self._projection_error[0])

        self._projection = self._projection_obj[0]

        _write_crash("screen: MediaProjection ready")

        # ImageReader — FORMAT_RGBA_8888 = 1
        ImageReader = autoclass("android.media.ImageReader")
        self._image_reader = ImageReader.newInstance(
            int(self._width), int(self._height), int(1), int(2))
        surface = self._image_reader.getSurface()
        _write_crash(f"screen: ImageReader created ({self._width}x{self._height})")

        # VirtualDisplay — call createVirtualDisplay directly on the projection.
        # API 35 8-param signature: (String, int, int, int, int, Surface, Callback, Handler)
        # flags (int=0) comes BEFORE surface — that's how the API 35 overloads are ordered.
        try:
            self._virtual_display = self._projection.createVirtualDisplay(
                "Labhair-liomScreen",
                int(self._width),
                int(self._height),
                int(self._dpi),
                int(0),     # flags
                surface,
                None,       # VirtualDisplay.Callback
                None,       # Handler
            )
        except Exception as exc:
            _write_crash(f"screen: direct createVirtualDisplay failed: {exc}")
            # Fallback: use Java reflection via app classloader
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            cl = activity.getClassLoader()
            HelperClass = cl.loadClass("org.labhairliom.ScreenCaptureHelper")
            createDisplay = None
            for m in HelperClass.getMethods():
                if m.getName() == "createDisplay":
                    createDisplay = m
                    break
            if createDisplay is None:
                raise RuntimeError("ScreenCaptureHelper.createDisplay not found")
            from jnius import cast
            createDisplay = cast("java.lang.reflect.Method", createDisplay)
            # Use Array.newInstance to create a Java Object[]
            Array = autoclass("java.lang.reflect.Array")
            ObjectClass = autoclass("java.lang.Object")
            java_args = Array.newInstance(ObjectClass, 7)
            java_args[0] = self._projection
            java_args[1] = "Labhair-liomScreen"
            java_args[2] = int(self._width)
            java_args[3] = int(self._height)
            java_args[4] = int(self._dpi)
            java_args[5] = surface
            java_args[6] = int(0)
            self._virtual_display = createDisplay.invoke(None, java_args)

        if self._virtual_display is None:
            raise RuntimeError("createVirtualDisplay returned null — "
                               "ensure foreground service with mediaProjection type is running")

        _write_crash("screen: VirtualDisplay created, capturing frames")

    # ── frame polling ────────────────────────────────────────────────

    def _capture_loop(self) -> None:
        """Poll ImageReader for RGBA frames and deliver as RGB numpy arrays."""
        frame_count = 0
        while self._running:
            try:
                image = self._image_reader.acquireLatestImage()
                if image is None:
                    time.sleep(0.033)
                    continue
                try:
                    planes = image.getPlanes()
                    plane = planes[0]
                    buffer = plane.getBuffer()
                    buf_len = buffer.remaining()
                    byte_array = bytearray(buf_len)
                    buffer.rewind()
                    buffer.get(byte_array)

                    rgba = np.frombuffer(byte_array, dtype=np.uint8).reshape(
                        (self._height, self._width, 4)
                    )
                    rgb = rgba[:, :, :3].copy()

                    frame_count += 1
                    if frame_count == 1:
                        _write_crash(f"screen: first frame ({buf_len} bytes)")

                    if self._frame_cb:
                        self._frame_cb(rgb)
                finally:
                    image.close()
            except Exception as exc:
                _write_crash(f"screen: frame error: {exc}")
                time.sleep(0.1)
