"""Floating, draggable, resizable in-app video viewer for Labhair-liom.

No browser and no second native window (Flet 0.25 has neither): the viewer is
an overlay panel inside the client window. Drag the header to move it; drag the
right/bottom edges or the corner handle to resize it. The video letterboxes to
fit the panel (ImageFit.CONTAIN) and a live FPS readout is shown in the header.
"""

from __future__ import annotations

import base64
import time
import flet as ft
from typing import TYPE_CHECKING

from client.flet_app.theme import *

if TYPE_CHECKING:
    from client.main import ChatClient

# Screen-share capture resolution presets (key → pixel size).
_RES_MAP: dict[str, tuple[int, int]] = {
    "360p": (640, 360),
    "480p": (854, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
}

# Minimum panel size (px) when resizing.
_MIN_W, _MIN_H = 420, 300


class ViewerWindow:
    """Floating viewer panel: drag the header to move, edge/corner handles to resize."""

    def __init__(self, page: ft.Page, client: ChatClient):
        self.page = page
        self.client = client
        self._panel: ft.Container | None = None
        self._stream_dropdown: ft.Dropdown | None = None
        self._res_dropdown: ft.Dropdown | None = None
        self._video_image: ft.Image | None = None
        self._video_container: ft.Container | None = None
        self._video_stack: ft.Stack | None = None
        self._metadata_label: ft.Text | None = None
        self._handle_r: ft.GestureDetector | None = None
        self._handle_b: ft.GestureDetector | None = None
        self._handle_se: ft.GestureDetector | None = None
        self._streams: list[str] = []
        self._frames: dict[str, bytes] = {}
        self._selected_stream: str = ""
        self._current_source: str = ""
        self._last_push_time: float = 0.0
        self._fps_start: float = 0.0
        self._fps_count: int = 0
        self._display_fps: int = 0
        self._feed_fps: int = 0

    def set_feed_fps(self, fps: int) -> None:
        """Capture-side push rate (how fast the source actually produces frames)."""
        self._feed_fps = fps

    # --- open / close ------------------------------------------------------

    def show(self):
        """Show the viewer (builds it on first use, then just unhides it)."""
        if self._panel is not None:
            self._panel.visible = True
            self.page.update()
            return
        self._build()
        self.page.overlay.append(self._panel)
        self.page.update()

    def _close(self, e=None):
        """Hide the viewer (kept in the overlay, just hidden)."""
        if self._panel is not None:
            self._panel.visible = False
            self.page.update()

    def is_open(self) -> bool:
        return self._panel is not None and self._panel.visible

    # --- construction ------------------------------------------------------

    def _build(self) -> None:
        pw_ = self.page.width or 900
        ph_ = self.page.height or 700
        pw, ph = max(_MIN_W, int(pw_ * 0.55)), max(_MIN_H, int(ph_ * 0.6))
        px = max(8, int((pw_ - pw) / 2))
        py = max(8, int((ph_ - ph) / 3))

        self._stream_dropdown = ft.Dropdown(
            hint_text="Select stream",
            bgcolor=BG_INPUT,
            color=FG,
            border_color=DIVIDER,
            border_radius=8,
            options=[],
            on_change=self._on_stream_change,
            width=170,
        )

        # Current capture resolution from the client engine, if one exists.
        default_res = "720p"
        eng = getattr(self.client, "video", None)
        if eng is not None:
            cw = getattr(eng, "capture_width", None)
            ch = getattr(eng, "capture_height", None)
            if cw and ch:
                for k, (w, h) in _RES_MAP.items():
                    if (w, h) == (cw, ch):
                        default_res = k
                        break

        self._res_dropdown = ft.Dropdown(
            value=default_res,
            bgcolor=BG_INPUT,
            color=FG,
            border_color=DIVIDER,
            border_radius=8,
            width=150,
            options=[
                ft.dropdown.Option(key="360p", text="360p (640x360)"),
                ft.dropdown.Option(key="480p", text="480p (854x480)"),
                ft.dropdown.Option(key="720p", text="720p (1280x720)"),
                ft.dropdown.Option(key="1080p", text="1080p (1920x1080)"),
            ],
            on_change=self._on_res_change,
            tooltip="Screen-share capture resolution",
        )

        # 1x1 dark pixel as placeholder until the first real frame
        import io
        try:
            from PIL import Image as _PILImage
            buf = io.BytesIO()
            _PILImage.new("RGB", (1, 1), (30, 31, 34)).save(buf, format="PNG")
            _placeholder = base64.b64encode(buf.getvalue()).decode()
        except Exception:
            _placeholder = ""

        self._metadata_label = ft.Text(
            "No stream selected",
            color=FG_DIM,
            size=12,
        )

        self._video_image = ft.Image(
            src_base64=_placeholder,
            fit=ft.ImageFit.CONTAIN,
        )
        self._video_container = ft.Container(
            content=self._video_image,
            bgcolor=BG_DARKER,
            border_radius=8,
        )

        # Resize handles live on top of the video area, inside a Stack.
        self._handle_se = self._make_handle(
            ft.MouseCursor.RESIZE_DOWN_RIGHT, self._resize_se
        )
        self._handle_r = self._make_handle(
            ft.MouseCursor.RESIZE_COLUMN, self._resize_r
        )
        self._handle_b = self._make_handle(
            ft.MouseCursor.RESIZE_ROW, self._resize_b
        )
        self._video_stack = ft.Stack([
            self._video_container,
            self._handle_r,
            self._handle_b,
            self._handle_se,
        ])

        # Header: drag affordance + title on the left, live status on the right.
        title_drag = ft.GestureDetector(
            content=ft.Row([
                ft.Icon(ft.Icons.DRAG_INDICATOR, size=16, color=FG_DIM),
                ft.Text("Video Viewer", color=FG, size=14),
            ], spacing=6),
            mouse_cursor=ft.MouseCursor.MOVE,
            drag_interval=20,
            on_pan_start=self._drag_start,
            on_pan_update=self._drag_update,
            on_pan_end=self._drag_end,
        )

        # Controls row (clicks stay interactive — separate from the drag header).
        self._scr_btn = ft.IconButton(
            icon=ft.Icons.SCREEN_SHARE,
            icon_color=FG_DIM,
            icon_size=18,
            tooltip="Toggle screen share",
            on_click=self._toggle_screen,
        )
        controls_row = ft.Row([
            self._stream_dropdown,
            self._res_dropdown,
            ft.Container(expand=True),
            ft.IconButton(
                icon=ft.Icons.CAMERA_ALT,
                icon_color=FG_DIM,
                icon_size=18,
                tooltip="Toggle camera",
                on_click=self._toggle_camera,
            ),
            self._scr_btn,
            ft.IconButton(
                icon=ft.Icons.OPEN_IN_FULL,
                icon_color=FG_DIM,
                icon_size=18,
                tooltip="Open floating window (movable outside the app) — closes this panel",
                on_click=self._toggle_floating,
            ),
            ft.IconButton(
                icon=ft.Icons.CLOSE,
                icon_color=FG_DIM,
                icon_size=18,
                tooltip="Close viewer",
                on_click=self._close,
            ),
        ], spacing=8)

        self._panel = ft.Container(
            left=px,
            top=py,
            width=pw,
            height=ph,
            bgcolor=BG_DARK,
            border_radius=10,
            border=ft.border.all(1, DIVIDER),
            padding=8,
            content=ft.Column([
                ft.Row([
                    title_drag,
                    ft.Container(expand=True),
                    self._metadata_label,
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                controls_row,
                self._video_stack,
            ], spacing=8),
        )

        self._apply_size()

    def _make_handle(
        self,
        cursor: ft.MouseCursor,
        on_update,
    ) -> ft.GestureDetector:
        """A small draggable resize bar (sized/positioned by _apply_size)."""
        return ft.GestureDetector(
            content=ft.Container(bgcolor=DIVIDER, border_radius=4),
            mouse_cursor=cursor,
            drag_interval=20,
            on_pan_start=self._drag_start,
            on_pan_update=on_update,
            on_pan_end=self._drag_end,
        )

    def _apply_size(self) -> None:
        """Fit inner controls to the panel's current width/height."""
        p = self._panel
        if p is None:
            return
        pw = max(_MIN_W, int(p.width or 0))
        ph = max(_MIN_H, int(p.height or 0))
        p.width, p.height = pw, ph
        vw, vh = pw - 16, max(140, ph - 128)  # column padding + header + controls

        self._video_stack.width, self._video_stack.height = vw, vh
        self._video_container.width, self._video_container.height = vw, vh
        self._video_image.width, self._video_image.height = vw, vh

        self._handle_r.left, self._handle_r.top = vw - 7, 12
        self._handle_r.width, self._handle_r.height = 7, vh - 24
        self._handle_b.left, self._handle_b.top = 12, vh - 7
        self._handle_b.width, self._handle_b.height = vw - 24, 7
        self._handle_se.left, self._handle_se.top = vw - 24, vh - 24
        self._handle_se.width, self._handle_se.height = 24, 24

    # --- move / resize gestures --------------------------------------------

    def _drag_start(self, e):
        pass

    def _drag_end(self, e):
        pass

    def _drag_update(self, e):
        p = self._panel
        if p is None:
            return
        dx, dy = e.delta_x or 0, e.delta_y or 0
        pw, ph = p.width or 0, p.height or 0
        max_x = max(0, (self.page.width or pw) - pw - 8)
        max_y = max(0, (self.page.height or ph) - ph - 8)
        p.left = max(0, min(max_x, (p.left or 0) + dx))
        p.top = max(0, min(max_y, (p.top or 0) + dy))
        self.page.update()

    def _resize_se(self, e):
        p = self._panel
        if p is None:
            return
        p.width = max(_MIN_W, (p.width or 0) + (e.delta_x or 0))
        p.height = max(_MIN_H, (p.height or 0) + (e.delta_y or 0))
        self._apply_size()
        self.page.update()

    def _resize_r(self, e):
        p = self._panel
        if p is None:
            return
        p.width = max(_MIN_W, (p.width or 0) + (e.delta_x or 0))
        self._apply_size()
        self.page.update()

    def _resize_b(self, e):
        p = self._panel
        if p is None:
            return
        p.height = max(_MIN_H, (p.height or 0) + (e.delta_y or 0))
        self._apply_size()
        self.page.update()

    # --- video feed --------------------------------------------------------

    def update_streams(self, streams: list[str]):
        """Update the stream selector dropdown."""
        self._streams = streams
        if self._stream_dropdown:
            self._stream_dropdown.options = [
                ft.dropdown.Option(text=s, key=s) for s in streams
            ]
            self.page.update()

    def push_jpeg(
        self,
        jpeg_data: bytes,
        source: str = "",
        resolution: str = "",
        label: str | None = None,
    ):
        """Display a JPEG frame (ignored while the viewer panel is hidden)."""
        if not self.is_open():
            return
        now = time.monotonic()
        if now - self._last_push_time < 1.0 / 30.0:
            return
        self._last_push_time = now
        if label is None:
            label = f"{source} {resolution}".strip() if (source or resolution) else "local"
        self._frames[label] = jpeg_data

        # Update stream list if new source
        if label not in self._streams:
            self._streams.append(label)
            self.update_streams(self._streams)

        # Show frame if it matches selected stream or nothing selected yet
        if not self._selected_stream or label == self._selected_stream:
            self._show_frame(jpeg_data, source, resolution, label)

    def _show_frame(
        self,
        jpeg_data: bytes,
        source: str = "",
        resolution: str = "",
        label: str | None = None,
    ):
        """Display a JPEG frame in the viewer."""
        if not self._video_image:
            return
        # Measure the rate frames are actually being rendered (display fps).
        now = time.monotonic()
        if not self._fps_start:
            self._fps_start = now
        self._fps_count += 1
        if now - self._fps_start >= 1.0:
            self._display_fps = self._fps_count
            self._fps_count = 0
            self._fps_start = now

        b64 = base64.b64encode(jpeg_data).decode()
        self._video_image.src_base64 = b64
        self._current_source = source
        if self._metadata_label:
            parts = []
            if label:
                parts.append(f"Source: {label}")
            elif source:
                parts.append(f"Source: {source}")
            if resolution:
                parts.append(f"Resolution: {resolution}")
            parts.append(f"{self._display_fps} fps (feed {self._feed_fps})")
            self._metadata_label.value = " | ".join(parts)
        self.page.update()

    def _on_stream_change(self, e):
        """Switch video stream."""
        stream = e.control.value
        if stream:
            self._selected_stream = stream
            if stream in self._frames:
                self._show_frame(self._frames[stream], source=stream)

    def _on_res_change(self, e):
        """Change the screen-share capture resolution."""
        w, h = _RES_MAP.get(e.control.value, (640, 360))
        if self.client is not None:
            self.client.set_screen_resolution(w, h)

    def _toggle_floating(self, e):
        """Open/close the floating desktop viewer window.

        Opening the floating window hides the in-app panel: the Tk window is
        the full-resolution, fully movable viewer, so the panel only covers
        the app. Reopen the panel from the View menu if needed.
        """
        if self.client is None:
            return
        opened = self.client.toggle_floating_viewer()
        if opened:
            self._close()

    # --- capture toggles ---------------------------------------------------

    def _toggle_camera(self, e):
        """Toggle camera feed."""
        video = getattr(self.client, 'video', None)
        if video:
            self.page.run_task(self._toggle_cam)

    async def _toggle_cam(self):
        video = getattr(self.client, 'video', None)
        if video:
            if video.camera_active:
                video.stop_camera()
            else:
                video.start_camera()

    def _toggle_screen(self, e):
        """Toggle screen share."""
        video = getattr(self.client, 'video', None)
        if video:
            self.page.run_task(self._toggle_scr)

    async def _toggle_scr(self):
        video = getattr(self.client, 'video', None)
        if not video:
            return
        if video.screen_active:
            self.client.stop_screen()
        else:
            self.client.start_screen()
        self._refresh_scr_btn()

    def _refresh_scr_btn(self):
        """Red icon while this client is streaming its screen."""
        on = bool(
            getattr(self.client, 'video', None)
            and getattr(self.client.video, 'screen_active', False)
        )
        btn = getattr(self, "_scr_btn", None)
        if btn is not None:
            btn.icon_color = RED if on else FG_DIM
            try:
                btn.update()
            except Exception:
                pass