"""Labhair-liom Android client — Kivy-based mobile UI for E2E encrypted chat.

Feature parity with the desktop tkinter GUI:
- Connect screen with host/port + auth (register/login) or legacy room mode
- Server/channel sidebar with navigation
- Chat log with colored messages (system, status, chat, image, file)
- Message history loaded on channel join
- Reactions display and quick-react
- Inline image thumbnails with download button
- Inline file info with save button
- Video viewer overlay for incoming JPEG frames
- Voice chat (mic toggle + speaker playback via pyjnius)
- Camera and screen share toggles
- Send image/file via plyer file chooser
- /download command for saving images/files to disk
- DM conversations, friend list, threads, search
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import queue
import sys
import tempfile
import threading
import traceback
from pathlib import Path

_log = logging.getLogger("labhairliom.android")

_self = Path(__file__).resolve()
if _self.parent.name in ("android_app", "client") and _self.parent.parent.name == "client":
    ROOT = _self.parents[2]
else:
    ROOT = _self.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("KIVY_NO_FILELOG", "1")

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.properties import BooleanProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.image import Image as KivyImage
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.metrics import sp, dp

BG = [0.118, 0.118, 0.118]
BG_PANEL = [0.145, 0.145, 0.145]
FG = [0.831, 0.831, 0.831]
FG_DIM = [0.502, 0.502, 0.502]
FG_SYS = [0.337, 0.612, 0.835]
FG_STATUS = [0.416, 0.600, 0.333]
FG_USER = [0.863, 0.863, 0.545]
FG_IMG = [0.808, 0.569, 0.471]
ACCENT = [0.055, 0.388, 0.612]
ACCENT_DIM = [0.08, 0.22, 0.36]





# ── Chat message widgets ────────────────────────────────────────────
def _make_chat_label(text: str, color: list[float], bold: bool = False,
                     font_size: float = 13, markup: bool = True) -> Label:
    lbl = Label(
        text=text,
        font_size=sp(font_size),
        color=color,
        size_hint_y=None,
        height=dp(20),
        text_size=(None, None),
        valign="top",
        halign="left",
        markup=markup,
        padding=[dp(4), dp(2)],
    )
    lbl.bind(width=lambda inst, w: setattr(inst, 'text_size', (w, None)))
    lbl.bind(texture_size=lambda inst, sz: setattr(inst, 'height', max(dp(18), sz[1] + dp(4))))
    return lbl


def _make_chat_spacer(height_dp: float = 4) -> Widget:
    return Widget(size_hint_y=None, height=dp(height_dp))


# ── Screens ──────────────────────────────────────────────────────────
class ConnectScreen(BoxLayout):
    def __init__(self, app: "LabhairLiomApp", **kwargs) -> None:
        super().__init__(orientation="vertical", padding=dp(24), spacing=dp(12), **kwargs)
        self.app = app

        self.add_widget(Label(
            text="Labhair-liom Chat v0.5", font_size=sp(28), bold=True, color=FG,
            size_hint_y=None, height=dp(48),
        ))
        self.add_widget(Label(
            text="E2E Encrypted", font_size=sp(14), color=[0.5, 0.5, 0.5],
            size_hint_y=None, height=dp(24),
        ))
        self.add_widget(Widget(size_hint_y=None, height=dp(8)))

        # Connection fields
        conn_fields = BoxLayout(orientation="vertical", spacing=dp(6), size_hint_y=None, height=dp(100))
        self.host_input = self._make_input("Relay IP or hostname", "")
        self.port_input = self._make_input("Port", "9473", input_filter="int")
        for w in (self.host_input, self.port_input):
            conn_fields.add_widget(w)
        self.add_widget(conn_fields)

        # Auth mode selector
        mode_row = BoxLayout(orientation="horizontal", spacing=dp(4), size_hint_y=None, height=dp(36))
        self.btn_signin = Button(text="Sign In", font_size=sp(13),
                                 background_color=ACCENT, color=FG, size_hint_x=0.33)
        self.btn_register = Button(text="Register", font_size=sp(13),
                                   background_color=[0.2, 0.2, 0.2, 1], color=FG, size_hint_x=0.33)
        self.btn_legacy = Button(text="Legacy", font_size=sp(13),
                                 background_color=[0.2, 0.2, 0.2, 1], color=FG, size_hint_x=0.34)
        self.btn_signin.bind(on_release=lambda *a: self._set_mode("signin"))
        self.btn_register.bind(on_release=lambda *a: self._set_mode("register"))
        self.btn_legacy.bind(on_release=lambda *a: self._set_mode("legacy"))
        mode_row.add_widget(self.btn_signin)
        mode_row.add_widget(self.btn_register)
        mode_row.add_widget(self.btn_legacy)
        self.add_widget(mode_row)

        # Auth fields (sign in / register)
        self.auth_fields = BoxLayout(orientation="vertical", spacing=dp(6), size_hint_y=None, height=dp(130))
        self.username_input = self._make_input("Username", "")
        self.password_input = self._make_input("Password", "", password=True)
        self.email_input = self._make_input("Email (register only)", "")
        self.confirm_input = self._make_input("Confirm password", "", password=True)
        for w in (self.username_input, self.password_input, self.email_input, self.confirm_input):
            self.auth_fields.add_widget(w)
        self.add_widget(self.auth_fields)

        # Legacy fields (room + name)
        self.legacy_fields = BoxLayout(orientation="vertical", spacing=dp(6), size_hint_y=None, height=dp(90))
        self.room_input = self._make_input("Room", "demo")
        self.name_input = self._make_input("Name (random if blank)", "")
        for w in (self.room_input, self.name_input):
            self.legacy_fields.add_widget(w)
        self.add_widget(self.legacy_fields)

        self._auth_mode = "signin"
        self._set_mode("signin")

        connect_btn = Button(
            text="Connect", font_size=sp(18), bold=True,
            size_hint_y=None, height=dp(52),
            background_color=ACCENT, color=FG,
        )
        connect_btn.bind(on_release=lambda *a: self.do_connect())
        self.add_widget(connect_btn)
        self.add_widget(Widget())

    def _set_mode(self, mode: str) -> None:
        self._auth_mode = mode
        for btn in (self.btn_signin, self.btn_register, self.btn_legacy):
            btn.background_color = [0.2, 0.2, 0.2, 1]
        if mode == "signin":
            self.btn_signin.background_color = ACCENT
            self.auth_fields.opacity = 1
            self.auth_fields.disabled = False
            self.legacy_fields.opacity = 0
            self.legacy_fields.disabled = True
            self.email_input.opacity = 0
            self.email_input.disabled = True
            self.confirm_input.opacity = 0
            self.confirm_input.disabled = True
        elif mode == "register":
            self.btn_register.background_color = ACCENT
            self.auth_fields.opacity = 1
            self.auth_fields.disabled = False
            self.legacy_fields.opacity = 0
            self.legacy_fields.disabled = True
            self.email_input.opacity = 1
            self.email_input.disabled = False
            self.confirm_input.opacity = 1
            self.confirm_input.disabled = False
        else:
            self.btn_legacy.background_color = ACCENT
            self.auth_fields.opacity = 0
            self.auth_fields.disabled = True
            self.legacy_fields.opacity = 1
            self.legacy_fields.disabled = False

    @staticmethod
    def _make_input(hint: str, text: str = "", input_filter: str = "") -> TextInput:
        kw = dict(
            hint_text=hint, text=text, multiline=False, font_size=sp(16),
            size_hint_y=None, height=dp(44),
            background_color=[0.18, 0.18, 0.18, 1], foreground_color=FG,
            hint_text_color=[0.4, 0.4, 0.4, 1], cursor_color=FG,
        )
        if input_filter:
            kw["input_filter"] = input_filter
        return TextInput(**kw)

    def do_connect(self) -> None:
        import random
        host = self.host_input.text.strip()
        if not host:
            self.host_input.hint_text = "Relay IP or hostname is required"
            return
        try:
            port = int(self.port_input.text.strip() or "9473")
        except ValueError:
            port = 9473

        if self._auth_mode == "legacy":
            room = self.room_input.text.strip() or "demo"
            name = self.name_input.text.strip() or f"user-{random.randint(1000, 9999)}"
            self.app.start_client(host, port, room=room, name=name)
        else:
            username = self.username_input.text.strip()
            password = self.password_input.text.strip()
            if not username or not password:
                return
            if self._auth_mode == "register":
                email = self.email_input.text.strip()
                confirm = self.confirm_input.text.strip()
                if not email or password != confirm:
                    return
                self.app.start_client(host, port, auth=("register", username, email, password))
            else:
                self.app.start_client(host, port, auth=("login", username, "", password))


class ChatScreen(BoxLayout):
    _viewer_visible = BooleanProperty(False)

    def __init__(self, app: "LabhairLiomApp", **kwargs) -> None:
        super().__init__(orientation="vertical", **kwargs)
        self.app = app
        self._max_lines = 500
        self._line_count = 0
        self._build_ui()

    def _build_ui(self) -> None:
        # ── top bar ──
        top = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40),
                        padding=[dp(8), dp(4)], spacing=dp(8))
        with top.canvas.before:
            from kivy.graphics import Color, Rectangle
            Color(rgba=[0.08, 0.08, 0.08, 1])
            top._bg = Rectangle(pos=top.pos, size=top.size)
            top.bind(pos=lambda i, p: setattr(i._bg, 'pos', p))
            top.bind(size=lambda i, s: setattr(i._bg, 'size', s))

        self.lbl_room = Label(text="", font_size=sp(13), bold=True, color=FG,
                              size_hint_x=0.4, valign="middle")
        self.lbl_room.bind(size=lambda i, s: setattr(i, 'text_size', s))
        top.add_widget(self.lbl_room)

        self.lbl_peers = Label(text="", font_size=sp(12), color=FG_DIM,
                               size_hint_x=0.3, valign="middle", halign="center")
        self.lbl_peers.bind(size=lambda i, s: setattr(i, 'text_size', s))
        top.add_widget(self.lbl_peers)

        self.lbl_status = Label(text="connecting...", font_size=sp(11), color=FG_STATUS,
                                size_hint_x=0.3, valign="middle", halign="right")
        self.lbl_status.bind(size=lambda i, s: setattr(i, 'text_size', s))
        top.add_widget(self.lbl_status)

        self.add_widget(top)

        # ── chat area ──
        sv = ScrollView(do_scroll_x=False, bar_color=[0.3, 0.3, 0.3, 0.5])
        self.chat_container = BoxLayout(orientation="vertical", size_hint_y=None,
                                        height=0, padding=[dp(8), dp(4)], spacing=dp(4))
        self.chat_container.bind(minimum_height=lambda i, h: setattr(i, 'height', h))
        sv.add_widget(self.chat_container)
        self.scroll_chat = sv
        self.add_widget(sv)

        # ── message input row ──
        input_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(48),
                              padding=dp(4), spacing=dp(4))
        self.msg_input = TextInput(
            hint_text="Type a message or /command...", multiline=False, font_size=sp(14),
            size_hint_x=0.75, background_color=[0.18, 0.18, 0.18, 1], foreground_color=FG,
            hint_text_color=[0.4, 0.4, 0.4, 1], cursor_color=FG,
        )
        self.msg_input.bind(on_text_validate=lambda i: self.send_message())
        input_row.add_widget(self.msg_input)
        send_btn = Button(text="Send", font_size=sp(14), size_hint_x=0.25,
                          background_color=ACCENT, color=FG)
        send_btn.bind(on_release=lambda *a: self.send_message())
        input_row.add_widget(send_btn)
        self.add_widget(input_row)

        # ── toolbar row ──
        tb = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(48),
                       padding=dp(4), spacing=dp(4))
        with tb.canvas.before:
            from kivy.graphics import Color, Rectangle
            Color(rgba=[0.08, 0.08, 0.08, 1])
            tb._bg = Rectangle(pos=tb.pos, size=tb.size)
            tb.bind(pos=lambda i, p: setattr(i._bg, 'pos', p))
            tb.bind(size=lambda i, s: setattr(i._bg, 'size', s))

        self.btn_mic = ToggleButton(text="Mic", font_size=sp(11),
                                     background_color=[0.2, 0.2, 0.2, 1], color=FG)
        self.btn_mic.bind(on_press=lambda i: self._on_toggle(i, self.toggle_voice))
        tb.add_widget(self.btn_mic)

        self.btn_cam = ToggleButton(text="Cam", font_size=sp(11),
                                     background_color=[0.2, 0.2, 0.2, 1], color=FG)
        self.btn_cam.bind(on_press=lambda i: self._on_toggle(i, self.toggle_video))
        tb.add_widget(self.btn_cam)

        self.btn_screen = ToggleButton(text="Screen", font_size=sp(11),
                                        background_color=[0.2, 0.2, 0.2, 1], color=FG)
        self.btn_screen.bind(on_press=lambda i: self._on_toggle(i, self.toggle_screen))
        tb.add_widget(self.btn_screen)

        img_btn = Button(text="Img", font_size=sp(11),
                         background_color=[0.2, 0.2, 0.2, 1], color=FG)
        img_btn.bind(on_release=lambda *a: self.send_image_dialog())
        tb.add_widget(img_btn)

        file_btn = Button(text="File", font_size=sp(11),
                          background_color=[0.2, 0.2, 0.2, 1], color=FG)
        file_btn.bind(on_release=lambda *a: self.send_file_dialog())
        tb.add_widget(file_btn)

        self.btn_viewer = ToggleButton(text="Viewer", font_size=sp(11))
        self.btn_viewer.bind(on_press=lambda i: self._on_viewer_toggle(i.state))
        tb.add_widget(self.btn_viewer)

        self.add_widget(tb)

    def _on_viewer_toggle(self, state: str) -> None:
        if state == "down":
            self.show_viewer()
        else:
            self.hide_viewer()

    @staticmethod
    def _on_toggle(btn: ToggleButton, callback) -> None:
        state = btn.state
        btn.background_color = ACCENT if state == "down" else [0.2, 0.2, 0.2, 1]
        try:
            callback(state)
        except Exception as exc:
            tb = traceback.format_exc()
            _write_crash(f"_on_toggle error: {exc}\n{tb}")
            print(f"[labhairliom] _on_toggle error: {exc}", flush=True)

    # ── chat line management ─────────────────────────────────────
    def _add_widget_to_chat(self, widget: Widget) -> None:
        container = self.chat_container
        container.add_widget(widget)
        self._line_count += 1
        self._trim_chat()
        Clock.schedule_once(lambda dt: self._scroll_to_bottom(), 0.05)

    def _trim_chat(self) -> None:
        container = self.chat_container
        while self._line_count > self._max_lines and len(container.children) > 0:
            container.remove_widget(container.children[-1])
            self._line_count -= 1

    def _scroll_to_bottom(self) -> None:
        sv = self.scroll_chat
        sv.scroll_y = 0

    def append_chat(self, text: str, color: list[float] | None = None) -> None:
        lbl = _make_chat_label(text, color or FG)
        self._add_widget_to_chat(lbl)

    def append_chat_markup(self, markup_text: str) -> None:
        lbl = _make_chat_label(markup_text, FG)
        self._add_widget_to_chat(lbl)

    def clear_chat(self) -> None:
        self.chat_container.clear_widgets()
        self._line_count = 0

    # ── message handling ─────────────────────────────────────────
    def send_message(self) -> None:
        text = self.msg_input.text.strip()
        if not text:
            return
        self.msg_input.text = ""
        if text.startswith("/"):
            asyncio.run_coroutine_threadsafe(
                self.app.client._command(text), self.app.client.loop
            )
        elif self.app.client.current_dm_user_id:
            asyncio.run_coroutine_threadsafe(
                self.app.client.send_dm_send(self.app.client.current_dm_user_id, text),
                self.app.client.loop,
            )
        elif self.app.client.current_channel_id:
            asyncio.run_coroutine_threadsafe(
                self.app.client.send_message_send(self.app.client.current_channel_id, text),
                self.app.client.loop,
            )
        else:
            asyncio.run_coroutine_threadsafe(
                self.app.client.send_chat(text), self.app.client.loop
            )

    def toggle_voice(self, state: str) -> None:
        client = self.app.client
        if client.loop is None:
            self.append_chat("* voice: not connected yet", FG_STATUS)
            self.btn_mic.state = "normal"
            return
        if state == "down":
            try:
                from client.android_app.android_audio import AndroidAudio
                from shared.adpcm import ADPCMCodec, SAMPLE_RATE as ADPCM_SR
                from shared.protocol import MsgType
                codec = ADPCMCodec(dtx=True)
                audio = AndroidAudio()
                self._android_audio = audio
                self._android_audio_codec = codec

                def _on_pcm(pcm_int16):
                    if not client.loop or not client.sessions:
                        return
                    # Split into 320-sample (20ms) ADPCM frames
                    # AudioRecord reads 1280 samples (80ms) per chunk;
                    # ADPCMCodec.encode() takes exactly 320 samples.
                    for i in range(0, len(pcm_int16), 320):
                        frame = pcm_int16[i : i + 320]
                        if len(frame) < 160:
                            break  # skip tiny trailing tail
                        blob = codec.encode(frame)
                        if blob is not None:
                            meta = {"codec": "ADPCM/IMA", "sr": ADPCM_SR, "ptime": 20}
                            asyncio.run_coroutine_threadsafe(
                                client._encrypt_to_all(MsgType.VOICE, blob, meta=meta),
                                client.loop,
                            )

                rx_codec = ADPCMCodec()

                def _play_rx(blob: bytes, track: str = "mic") -> None:
                    pcm = rx_codec.decode(blob)
                    if pcm is not None:
                        audio.push_playback(pcm)

                class _VoiceShim:
                    def __init__(self, play_fn):
                        self._play_fn = play_fn
                    def push_remote_frame(self, blob, track="mic"):
                        self._play_fn(blob, track)
                    def stop(self):
                        pass

                shim = _VoiceShim(_play_rx)
                client.voice = shim
                audio.start(record_cb=_on_pcm)
                import time as _t
                _t.sleep(0.5)
                if audio._record_thread and audio._record_thread.is_alive():
                    client.voice_is_active = True
                    if client.loop:
                        asyncio.run_coroutine_threadsafe(
                            client._send_voice_presence(client.user_id, True),
                            client.loop,
                        )
                    client.ui_sys("voice ON (Android mic)")
                else:
                    real_err = audio.last_error or "unknown error"
                    audio.stop()
                    self._android_audio = None
                    self._android_audio_codec = None
                    client.voice = None
                    self.btn_mic.state = "normal"
                    self.btn_mic.background_color = [0.2, 0.2, 0.2, 1]
                    client.ui_status(f"voice failed: {real_err}")
            except Exception as exc:
                _write_crash(f"toggle_voice error: {exc}\n{traceback.format_exc()}")
                self.btn_mic.state = "normal"
                self.btn_mic.background_color = [0.2, 0.2, 0.2, 1]
                client.ui_status(f"voice failed: {exc}")
        else:
            audio = getattr(self, "_android_audio", None)
            if audio:
                audio.stop()
                self._android_audio = None
                self._android_audio_codec = None
            client.voice = None
            client.voice_is_active = False
            if client.loop:
                asyncio.run_coroutine_threadsafe(
                    client._send_voice_presence(client.user_id, False),
                    client.loop,
                )
            client.ui_sys("voice OFF")

    def toggle_video(self, state: str) -> None:
        client = self.app.client
        if client.loop is None:
            self.append_chat("* camera: not connected yet", FG_STATUS)
            self.btn_cam.state = "normal"
            return
        if state == "down":
            try:
                from client.android_app.android_video import AndroidCamera
                from shared.labhair_liom import LabhairLiomEncoder, FLAG_CAMERA
                from shared.protocol import MsgType
                encoder = LabhairLiomEncoder(
                    width=client.ascii_w, height=client.ascii_h,
                    fps=client.ascii_fps, flags=FLAG_CAMERA,
                )
                cam = AndroidCamera()
                self._android_cam = cam
                self._android_cam_encoder = encoder

                _cam_frame_count = [0]
                _cam_skipped = [0]

                def _on_frame(rgb_frame):
                    _cam_frame_count[0] += 1
                    if not client.loop or not client.sessions:
                        _cam_skipped[0] += 1
                        if _cam_skipped[0] <= 3 or _cam_skipped[0] % 30 == 0:
                            _write_crash(f"cam frame #{_cam_frame_count[0]} SKIPPED (no sessions, skipped={_cam_skipped[0]})")
                        return
                    try:
                        import numpy as _np
                        from PIL import Image as _PILImage
                        import base64 as _b64
                        import io as _io
                        # Downsample early — all downstream work (JPEG, ASCII encode)
                        # operates on much smaller data, critical for phone CPUs.
                        src_h, src_w = rgb_frame.shape[:2]
                        small_w, small_h = min(src_w, 320), min(src_h, 240)
                        pil_small = _PILImage.fromarray(rgb_frame).resize(
                            (small_w, small_h), _PILImage.BILINEAR)
                        small_rgb = _np.array(pil_small)

                        # JPEG thumbnail for PC viewer (from small version)
                        img_b64 = ""
                        try:
                            buf = _io.BytesIO()
                            pil_small.save(buf, format="JPEG", quality=60)
                            img_b64 = _b64.b64encode(buf.getvalue()).decode()
                        except Exception:
                            pass
                        blob = encoder.encode_color(small_rgb, use_blocks=client.pixel, img_b64=img_b64)
                        asyncio.run_coroutine_threadsafe(
                            client._encrypt_to_all(MsgType.VIDEO, blob,
                                                   meta={"codec": "LABHAIR-LIOM/1.0", "source": "camera"}),
                            client.loop,
                        )
                        if _cam_frame_count[0] % 30 == 1:
                            _write_crash(f"cam frame sent #{_cam_frame_count[0]}: {len(blob)} bytes, sessions={list(client.sessions.keys())}")
                    except Exception as exc:
                        _write_crash(f"cam frame error: {exc}")
                        print(f"[labhairliom] cam frame error: {exc}", flush=True)

                cam.start(frame_cb=_on_frame, width=320, height=240)
                _write_crash(f"camera started, sessions={list(client.sessions.keys())}")
                if client.loop:
                    asyncio.run_coroutine_threadsafe(
                        client._send_media_presence(client.user_id, "camera", True),
                        client.loop,
                    )
                client.ui_sys(f"camera ON — Labhair-liom {client.ascii_w}x{client.ascii_h}")
            except Exception as exc:
                _write_crash(f"toggle_video error: {exc}\n{traceback.format_exc()}")
                self.btn_cam.state = "normal"
                self.btn_cam.background_color = [0.2, 0.2, 0.2, 1]
                client.ui_status(f"camera failed: {exc}")
        else:
            cam = getattr(self, "_android_cam", None)
            if cam:
                cam.stop()
                self._android_cam = None
                self._android_cam_encoder = None
                if client.loop:
                    asyncio.run_coroutine_threadsafe(
                        client._send_media_presence(client.user_id, "camera", False),
                        client.loop,
                    )
            client.ui_sys("camera OFF")

    def toggle_screen(self, state: str) -> None:
        client = self.app.client
        if client.loop is None:
            self.append_chat("* screen: not connected yet", FG_STATUS)
            self.btn_screen.state = "normal"
            return
        if state == "down":
            try:
                from client.android_app.android_video import AndroidScreenCapture
                from shared.labhair_liom import LabhairLiomEncoder, FLAG_SCREEN
                from shared.protocol import MsgType
                encoder = LabhairLiomEncoder(
                    width=client.screen_w, height=client.screen_h,
                    fps=client.screen_fps, flags=FLAG_SCREEN,
                )
                sc = AndroidScreenCapture()
                self._android_screen = sc
                self._android_screen_encoder = encoder

                _scr_frame_count = [0]
                _scr_skipped = [0]

                def _on_frame(rgb_frame):
                    _scr_frame_count[0] += 1
                    if not client.loop or not client.sessions:
                        _scr_skipped[0] += 1
                        if _scr_skipped[0] <= 3 or _scr_skipped[0] % 30 == 0:
                            _write_crash(f"screen frame #{_scr_frame_count[0]} SKIPPED (no sessions, skipped={_scr_skipped[0]})")
                        return
                    try:
                        # Create JPEG thumbnail for PC viewer
                        img_b64 = ""
                        try:
                            from PIL import Image as _PILImage
                            import base64 as _b64
                            thumb = _PILImage.fromarray(rgb_frame)
                            thumb.thumbnail((640, 360))
                            import io as _io
                            buf = _io.BytesIO()
                            thumb.save(buf, format="JPEG", quality=60)
                            img_b64 = _b64.b64encode(buf.getvalue()).decode()
                        except Exception:
                            pass
                        blob = encoder.encode_color(rgb_frame, use_blocks=client.pixel, img_b64=img_b64)
                        asyncio.run_coroutine_threadsafe(
                            client._encrypt_to_all(MsgType.VIDEO, blob,
                                                   meta={"codec": "LABHAIR-LIOM/1.0", "source": "screen"}),
                            client.loop,
                        )
                        if _scr_frame_count[0] % 30 == 1:
                            _write_crash(f"screen frame sent #{_scr_frame_count[0]}: {len(blob)} bytes, sessions={list(client.sessions.keys())}")
                    except Exception as exc:
                        _write_crash(f"screen frame error: {exc}")
                        print(f"[labhairliom] screen frame error: {exc}", flush=True)

                sc.start(frame_cb=_on_frame, width=640, height=360)
                _write_crash(f"screen started, sessions={list(client.sessions.keys())}")
                if client.loop:
                    asyncio.run_coroutine_threadsafe(
                        client._send_media_presence(client.user_id, "screen", True),
                        client.loop,
                    )
                client.ui_sys(f"screen share: please approve the screen capture dialog")
            except Exception as exc:
                _write_crash(f"toggle_screen error: {exc}\n{traceback.format_exc()}")
                self.btn_screen.state = "normal"
                self.btn_screen.background_color = [0.2, 0.2, 0.2, 1]
                client.ui_status(f"screen share failed: {exc}")
        else:
            sc = getattr(self, "_android_screen", None)
            if sc:
                sc.stop()
                self._android_screen = None
                self._android_screen_encoder = None
                if client.loop:
                    asyncio.run_coroutine_threadsafe(
                        client._send_media_presence(client.user_id, "screen", False),
                        client.loop,
                    )
            client.ui_sys("screen OFF")

    def toggle_viewer(self) -> None:
        if self._viewer_visible:
            self.hide_viewer()
        else:
            self.show_viewer()

    def show_viewer(self) -> None:
        self._viewer_visible = True
        self.btn_viewer.background_color = ACCENT

    def hide_viewer(self) -> None:
        self._viewer_visible = False
        self.btn_viewer.background_color = [0.2, 0.2, 0.2, 1]

    # ── send dialogs ─────────────────────────────────────────────
    def send_file_dialog(self) -> None:
        self._open_kivy_chooser(filters=[], mode="file")

    def send_image_dialog(self) -> None:
        self._open_kivy_chooser(
            filters=["*.png", "*.jpg", "*.jpeg", "*.webp", "*.gif"],
            mode="image",
        )

    def _open_kivy_chooser(self, filters: list[str], mode: str) -> None:
        from kivy.uix.popup import Popup
        from kivy.uix.filechooser import FileChooserIconView
        import os

        start = "/storage/emulated/0"
        if not os.path.isdir(start):
            start = "/sdcard"
        if not os.path.isdir(start):
            start = os.path.expanduser("~")

        fc = FileChooserIconView(
            path=start,
            filters=filters,
            size_hint=(1, 1),
            multiselect=False,
        )

        popup = Popup(
            title="Select file" if mode == "file" else "Select image",
            content=fc,
            size_hint=(0.95, 0.90),
            auto_dismiss=True,
        )

        def _on_select(instance, selection, **kw):
            if selection:
                popup.dismiss()
                path = selection[0]
                if mode == "image":
                    self._on_image_selected([path])
                else:
                    self._on_file_selected([path])

        fc.bind(selection=_on_select)
        popup.open()

    def _on_file_selected(self, selection: list[str]) -> None:
        if selection and selection[0]:
            uri = selection[0]
            path, orig_name = self._resolve_android_uri(uri)
            from shared.privacy import inspect_file
            report = inspect_file(path)
            if report.warning:
                self._confirm_unsanitized_file(path, orig_name, report.warning)
                return
            self._send_file(path, orig_name, False)
        else:
            self.append_chat("* no file selected", FG_DIM)

    def _send_file(self, path: str, orig_name: str, allow_unsanitized: bool) -> None:
        self.append_chat(f"* sending file: {orig_name}", FG_STATUS)
        asyncio.run_coroutine_threadsafe(
            self.app.client.send_file(
                path, orig_name=orig_name, allow_unsanitized=allow_unsanitized
            ),
            self.app.client.loop,
        )

    def _confirm_unsanitized_file(self, path: str, orig_name: str, warning: str) -> None:
        from kivy.uix.popup import Popup
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.button import Button

        body = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(10))
        body.add_widget(_make_chat_label(warning, [1, 0.25, 0.25], font_size=13))
        buttons = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        popup = Popup(title="Identifying metadata warning", content=body, size_hint=(.92, .46))
        cancel = Button(text="Cancel")
        send = Button(text="Send anyway", background_color=[0.65, 0.12, 0.12, 1])
        cancel.bind(on_release=popup.dismiss)

        def _send(_button):
            popup.dismiss()
            self.append_chat(
                "IDENTIFYING METADATA NOT STRIPPED — file sent as selected.",
                [1, 0.25, 0.25],
            )
            self._send_file(path, orig_name, True)

        send.bind(on_release=_send)
        buttons.add_widget(cancel)
        buttons.add_widget(send)
        body.add_widget(buttons)
        popup.open()

    def _on_image_selected(self, selection: list[str]) -> None:
        if selection and selection[0]:
            uri = selection[0]
            path, orig_name = self._resolve_android_uri(uri)
            self.append_chat(f"* sending image: {orig_name}", FG_STATUS)
            asyncio.run_coroutine_threadsafe(
                self.app.client.send_image(path, orig_name=orig_name),
                self.app.client.loop,
            )
        else:
            self.append_chat("* no image selected", FG_DIM)

    def _resolve_android_uri(self, uri: str) -> tuple[str, str]:
        """If *uri* is a content:// URI, copy the data to a temp file.

        Returns (temp_path, original_filename).
        """
        if not uri.startswith("content://"):
            return uri, os.path.basename(uri)
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            resolver = activity.getContentResolver()
            Uri = autoclass("android.net.Uri")
            parsed = Uri.parse(uri)

            orig_name = "file"
            try:
                cursor = resolver.query(parsed, None, None, None, None)
                if cursor and cursor.moveToFirst():
                    idx = cursor.getColumnIndex("_display_name")
                    if idx >= 0:
                        orig_name = cursor.getString(idx) or "file"
                    cursor.close()
            except Exception:
                pass

            input_stream = resolver.openInputStream(parsed)
            baos = bytearray()
            buf = bytearray(65536)
            while True:
                n = input_stream.read(buf, 0, 65536)
                if n <= 0:
                    break
                baos.extend(buf[:n])
            input_stream.close()

            ext = os.path.splitext(orig_name)[1] or ".bin"
            if not os.path.splitext(orig_name)[1]:
                orig_name = orig_name + ext
            tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
            tmp.write(bytes(baos))
            tmp.close()
            return tmp.name, orig_name
        except Exception as exc:
            _log.warning("_resolve_android_uri failed for %s: %s", uri, exc)
            return uri, os.path.basename(uri)

    # ── inline image ─────────────────────────────────────────────
    def show_inline_image(self, image_id: str, webp_bytes: bytes, sender: str,
                          name: str, width: int, height: int) -> None:
        box = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            padding=[dp(4), dp(4)],
            spacing=dp(2),
        )

        # Sender + info label
        info_text = f"<{sender}> [color=#ce9178]{name} ({width}x{height})[/color]"
        info_lbl = _make_chat_label(info_text, FG_USER, font_size=12)
        info_lbl.bold = True
        box.add_widget(info_lbl)

        # Thumbnail
        try:
            from PIL import Image as PILImage
            img = PILImage.open(io.BytesIO(webp_bytes))
            max_w = 400
            if img.width > max_w:
                ratio = max_w / img.width
                img = img.resize((max_w, int(img.height * ratio)), PILImage.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.write(buf.getvalue())
            tmp.close()
            kv_img = KivyImage(
                source=tmp.name,
                size_hint_y=None,
                height=min(dp(300), dp(img.height)),
                allow_stretch=True,
                keep_ratio=True,
            )
            box.add_widget(kv_img)
            # Schedule cleanup of temp file
            def _cleanup(dt, path=tmp.name):
                try:
                    os.unlink(path)
                except OSError:
                    pass
            Clock.schedule_once(_cleanup, 30)
        except Exception:
            box.add_widget(_make_chat_label("[color=#808080]  (image preview failed)[/color]", FG_DIM, font_size=11))

        # Download button
        btn = Button(
            text=f"Save {name}",
            size_hint_y=None,
            height=dp(32),
            font_size=sp(12),
            background_color=ACCENT_DIM,
            color=FG,
        )
        btn.bind(on_release=lambda inst, iid=image_id: self.app._download_image(iid))
        box.add_widget(btn)

        self._add_widget_to_chat(box)

    # ── inline file ──────────────────────────────────────────────
    def show_inline_file(self, file_id: str, sender: str, name: str,
                         mime_type: str, size: int) -> None:
        box = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(44),
            padding=[dp(6), dp(4)],
            spacing=dp(8),
        )
        with box.canvas.before:
            from kivy.graphics import Color, RoundedRectangle
            Color(rgba=[0.12, 0.12, 0.12, 1])
            box._bg_rect = RoundedRectangle(pos=box.pos, size=box.size, radius=[dp(4)])
            box.bind(pos=lambda inst, pos: setattr(inst._bg_rect, 'pos', pos))
            box.bind(size=lambda inst, size: setattr(inst._bg_rect, 'size', size))

        size_str = f"{size / 1024:.1f} KB" if size < 1048576 else f"{size / 1048576:.1f} MB"
        info_text = f"<{sender}> {name}\n{mime_type}  {size_str}"
        info_lbl = _make_chat_label(info_text, FG, font_size=11)
        info_lbl.size_hint_x = 0.7
        box.add_widget(info_lbl)

        btn = Button(
            text="Save",
            size_hint_x=0.3,
            size_hint_y=None,
            height=dp(32),
            font_size=sp(12),
            background_color=ACCENT_DIM,
            color=FG,
        )
        btn.bind(on_release=lambda inst, fid=file_id: self.app._download_file(fid))
        box.add_widget(btn)

        self._add_widget_to_chat(box)

    # ── video viewer overlay ─────────────────────────────────────
    def show_video_frame(self, jpeg_bytes: bytes, source: str) -> None:
        if not self._viewer_visible:
            return
        try:
            from kivy.core.image import Image as CoreImage
            from io import BytesIO as _BIO
            buf = _BIO(jpeg_bytes)
            core_img = CoreImage(buf, ext='jpg')
            # Reuse existing video widget if present
            for child in self.chat_container.children:
                if hasattr(child, '_is_video') and child._is_video:
                    child.texture = core_img.texture
                    return
            # First frame — create widget
            kv_img = KivyImage(
                texture=core_img.texture,
                size_hint_y=None,
                height=dp(240),
                allow_stretch=True,
                keep_ratio=True,
            )
            kv_img._is_video = True
            self.chat_container.add_widget(kv_img)
            self._line_count += 1
            Clock.schedule_once(lambda dt: self._scroll_to_bottom(), 0.05)
        except Exception:
            pass


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


# ── App ──────────────────────────────────────────────────────────────
class LabhairLiomApp(App):
    def build(self):
        try:
            self.title = "Labhair-liom Chat"
            Window.clearcolor = BG

            self.client = None
            self._gui_queue: queue.Queue = queue.Queue()

            # Clear crash file on startup
            _write_crash("--- app started ---")

            self._request_android_permissions()

            self.connect_screen = ConnectScreen(app=self)
            self.chat_screen = None
            self._poll_event = None

            return self.connect_screen
        except Exception as exc:
            import traceback as _tb
            _log.error("build() FAILED: %s", exc)
            _tb.print_exc()
            from kivy.uix.label import Label as _Lbl
            Window.clearcolor = [0.1, 0.1, 0.1, 1]
            return _Lbl(text=f"[color=ff4444]BUILD ERROR:\n{exc}[/color]",
                        markup=True, font_size=14)

    def _request_android_permissions(self) -> None:
        try:
            from android.permissions import request_permissions, Permission
            request_permissions([
                Permission.CAMERA,
                Permission.RECORD_AUDIO,
                Permission.WRITE_EXTERNAL_STORAGE,
                Permission.READ_EXTERNAL_STORAGE,
            ])
        except ImportError:
            pass
        except Exception as exc:
            _log.warning("permission request failed: %s", exc)
        # On Android 11+ request MANAGE_EXTERNAL_STORAGE via Settings intent
        try:
            from jnius import autoclass
            Environment = autoclass("android.os.Environment")
            if not Environment.isExternalStorageManager():
                Intent = autoclass("android.content.Intent")
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                intent = Intent(
                    "android.settings.MANAGE_APP_ALL_FILES_ACCESS_PERMISSION"
                )
                pkg = PythonActivity.mActivity.getPackageName()
                intent.setData(
                    autoclass("android.net.Uri").parse(f"package:{pkg}")
                )
                PythonActivity.mActivity.startActivity(intent)
        except Exception:
            try:
                from jnius import autoclass
                Intent = autoclass("android.content.Intent")
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                PythonActivity.mActivity.startActivity(
                    Intent("android.settings.MANAGE_ALL_FILES_ACCESS_PERMISSION")
                )
            except Exception:
                pass

    def start_client(self, host: str, port: int, room: str = "demo",
                     name: str = "", auth: tuple | None = None) -> None:
        if self.client is None:
            self.client = _make_client()
            if self.client is None:
                self.connect_screen.host_input.text = "FAILED — check logcat"
                return
            self.client._gui_queue = self._gui_queue
            self.client._gui_mode = True
        self.client.host = host
        self.client.port = port
        self.client.room = room
        if name:
            self.client.user_id = name
            self.client.display = name
        if auth:
            self.client._pending_auth = auth

        self.chat_screen = ChatScreen(app=self)
        label = f"{host}:{port}"
        if auth:
            label = f"{auth[1]} @ {host}:{port}"
        elif room:
            label = f"{room} @ {host}:{port}"
        self.chat_screen.lbl_room.text = label
        self.root_window.remove_widget(self.connect_screen)
        self.root_window.add_widget(self.chat_screen)

        self._start_asyncio_thread()
        self._poll_event = Clock.schedule_interval(self._poll_queue, 0.05)

        # Wire up callbacks for new features
        self.client.on_messages_updated = self._on_messages_updated
        self.client.on_auth_success = self._on_auth_success
        self.client.on_servers_updated = self._on_servers_updated
        self.client.on_channels_updated = self._on_channels_updated
        self.client.on_reaction_updated = self._on_reaction_updated

        from client.android_app.foreground_service import start_foreground_service
        start_foreground_service("Labhair-liom Chat", f"Connected to {host}:{port}")

    def _on_messages_updated(self, messages: list) -> None:
        """Display loaded message history in chat."""
        if self.chat_screen:
            self.chat_screen.clear_chat()
            for msg in messages:
                who = msg.get("username", f"user:{msg.get('author_id', '?')}")
                content = msg.get("content", "")
                ts = msg.get("created_at", "")
                reactions = msg.get("reactions", {})
                if content:
                    reaction_str = ""
                    if reactions:
                        reaction_str = " " + " ".join(
                            f"{e}({len(u)})" for e, u in reactions.items()
                        )
                    markup = (f"[color=#808080][{ts}] [/color]"
                              f"[color=#dcdcaa][b]<{who}>[/b][/color] "
                              f"{content}[color=#808080]{reaction_str}[/color]")
                    self.chat_screen.append_chat_markup(markup)
            self.chat_screen.append_chat(
                f"* loaded {len(messages)} messages", FG_STATUS)

    def _on_auth_success(self, body: dict) -> None:
        """Handle successful authentication."""
        if self.chat_screen:
            self.chat_screen.lbl_status.text = f"Logged in as {body.get('username', '?')}"
        # Request server list
        asyncio.run_coroutine_threadsafe(
            self.client.send_server_list(), self.client.loop
        )

    def _on_servers_updated(self) -> None:
        """Show server list in chat."""
        if not self.chat_screen or not self.client.servers:
            return
        self.chat_screen.append_chat("* Servers:", FG_STATUS)
        for srv in self.client.servers:
            sid = srv.get("id", 0)
            name = srv.get("name", "?")
            self.chat_screen.append_chat(f"  /server join {sid} — {name}", FG)

    def _on_channels_updated(self) -> None:
        """Show channel list in chat."""
        if not self.chat_screen or not self.client.channels:
            return
        self.chat_screen.append_chat("* Channels:", FG_STATUS)
        for ch in self.client.channels:
            cid = ch.get("id", 0)
            name = ch.get("name", "?")
            ctype = ch.get("channel_type", "text")
            icon = "🔊" if ctype == "voice" else "#"
            self.chat_screen.append_chat(f"  {icon} {name} (/channel join {cid})", FG)

    def _on_reaction_updated(self, body: dict) -> None:
        """Display reaction update in chat."""
        if self.chat_screen:
            action = "reacted" if body.get("emoji") else "unreacted"
            emoji = body.get("emoji", "")
            msg_id = body.get("message_id", 0)
            username = body.get("username", "")
            self.chat_screen.append_chat(
                f"* {username} {action} {emoji} to #{msg_id}", FG_STATUS)

    def _start_asyncio_thread(self) -> None:
        def _loop() -> None:
            self.client.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.client.loop)
            try:
                self.client.loop.run_until_complete(self.client.run())
            except Exception as exc:
                import traceback
                _log.error("async thread crashed: %s", exc)
                traceback.print_exc()
                self._gui_queue.put(("ui_sys", (f"disconnected: {exc}",), {}))

        t = threading.Thread(target=_loop, daemon=True, name="labhairliom-async")
        t.start()

    # ── queue polling (matches desktop 50ms poll) ────────────────
    def _poll_queue(self, dt: float) -> None:
        try:
            for _ in range(200):
                method, args, _kw = self._gui_queue.get_nowait()
                handler = getattr(self, f"_handle_{method}", None)
                if handler:
                    handler(*args)
                else:
                    _log.warning("no handler for queue event: %s", method)
        except queue.Empty:
            pass
        except Exception as exc:
            _log.error("poll_queue error: %s", exc)

    # ── message handlers (mirror desktop ChatGUI) ────────────────
    def _handle_ui(self, msg: str) -> None:
        if self.chat_screen:
            self.chat_screen.append_chat(msg)

    def _handle_ui_status(self, msg: str) -> None:
        if self.chat_screen:
            self.chat_screen.append_chat(f"* {msg}", FG_STATUS)
            self.chat_screen.lbl_status.text = msg

    def _handle_ui_sys(self, msg: str) -> None:
        if not self.chat_screen:
            return
        self.chat_screen.append_chat(f"* {msg}", FG_SYS)
        low = msg.lower()
        # sync media toggle states
        if "voice on" in low or "voice listen" in low:
            self.chat_screen.btn_mic.state = "down"
        elif "voice off" in low:
            self.chat_screen.btn_mic.state = "normal"
        if "camera on" in low:
            self.chat_screen.btn_cam.state = "down"
        elif "camera off" in low:
            self.chat_screen.btn_cam.state = "normal"
        if "screen on" in low:
            self.chat_screen.btn_screen.state = "down"
        elif "screen off" in low:
            self.chat_screen.btn_screen.state = "normal"
        # update status label
        if "connected to" in msg:
            self.chat_screen.lbl_status.text = msg
        # update peer count
        if "joined" in low or "left" in low or "sharing" in low or "voice" in low:
            self._refresh_peer_count()

    def _handle_ui_chat(self, who: str, text: str) -> None:
        if self.chat_screen:
            markup = f"[color=#dcdcaa][b]<{who}>[/b][/color] {text}"
            self.chat_screen.append_chat_markup(markup)

    def _handle_ui_video_frame(self, text: str, label: str = "Labhair-liom") -> None:
        if self.chat_screen:
            self.chat_screen.append_chat(f"── {label} ──", FG_STATUS)

    def _handle_ui_image(self, image_id: str, webp_bytes: bytes, sender: str,
                         name: str, width: int, height: int) -> None:
        if self.chat_screen:
            self.chat_screen.show_inline_image(image_id, webp_bytes, sender, name, width, height)

    def _handle_ui_video_jpeg(self, jpeg_bytes: bytes, source: str) -> None:
        if self.chat_screen:
            self.chat_screen.show_video_frame(jpeg_bytes, source)

    def _handle_ui_file(self, file_id: str, file_bytes: bytes, sender: str,
                        name: str, mime_type: str, size: int) -> None:
        if self.chat_screen:
            self.chat_screen.show_inline_file(file_id, sender, name, mime_type, size)

    # ── peer count ───────────────────────────────────────────────
    def _refresh_peer_count(self) -> None:
        if not self.chat_screen:
            return
        n = len(self.client.peer_identity)
        self.chat_screen.lbl_peers.text = f"{n} peer{'s' if n != 1 else ''}"

    # ── download handlers ────────────────────────────────────────
    def _download_image(self, image_id: str) -> None:
        if image_id not in self.client._received_images:
            if self.chat_screen:
                self.chat_screen.append_chat(f"* image {image_id} not found", FG_STATUS)
            return
        meta, webp_bytes, _ = self.client._received_images[image_id]
        self._pending_save = (meta.name, webp_bytes, "image")
        from plyer import filechooser
        filechooser.open_file(
            on_selection=self._on_save_image_path,
            filters=["*.webp", "*.png", "*.jpg"],
        )

    def _on_save_image_path(self, selection: list[str]) -> None:
        if not selection or not self._pending_save:
            return
        path = selection[0]
        name, data, kind = self._pending_save
        self._pending_save = None
        try:
            from pathlib import Path as P
            P(path).write_bytes(data)
            if self.chat_screen:
                self.chat_screen.append_chat(f"* saved → {path}", FG_STATUS)
        except Exception as exc:
            if self.chat_screen:
                self.chat_screen.append_chat(f"* save failed: {exc}", FG_IMG)

    def _download_file(self, file_id: str) -> None:
        if file_id not in self.client._received_files:
            if self.chat_screen:
                self.chat_screen.append_chat(f"* file {file_id} not found", FG_STATUS)
            return
        meta, file_bytes = self.client._received_files[file_id]
        self._pending_save = (meta.name, file_bytes, "file")
        from plyer import filechooser
        filechooser.open_file(
            on_selection=self._on_save_file_path,
        )

    def _on_save_file_path(self, selection: list[str]) -> None:
        if not selection or not self._pending_save:
            return
        path = selection[0]
        name, data, kind = self._pending_save
        self._pending_save = None
        try:
            from pathlib import Path as P
            P(path).write_bytes(data)
            if self.chat_screen:
                self.chat_screen.append_chat(f"* saved → {path}", FG_STATUS)
        except Exception as exc:
            if self.chat_screen:
                self.chat_screen.append_chat(f"* save failed: {exc}", FG_IMG)

    def on_stop(self) -> None:
        from client.android_app.foreground_service import stop_foreground_service
        stop_foreground_service()
        if self.client and self.client.loop:
            self.client._stop.set()

    def on_pause(self) -> bool:
        _log.info("app paused — keeping connection alive")
        return True

    def on_resume(self) -> None:
        _log.info("app resumed")
        if hasattr(self, '_poll_event') and self._poll_event is not None:
            try:
                self._poll_event.cancel()
            except Exception:
                pass
        if self._gui_queue is not None:
            self._poll_event = Clock.schedule_interval(self._poll_queue, 0.05)


def _write_crash(msg: str) -> None:
    for p in ("/sdcard/Download/labhairliom_crash.txt",
              os.path.join(os.path.expanduser("~"), "labhairliom_crash.txt")):
        try:
            with open(p, "a") as f:
                f.write(msg + "\n")
            break
        except Exception:
            continue


def _make_client():
    try:
        from client.main import ChatClient
        return ChatClient(
            host="127.0.0.1",
            port=9473,
            room="demo",
            user_id="android",
            display="android",
            voice=False,
            video=False,
            screen=False,
            cam=0,
            monitor=0,
            ascii_w=40,
            ascii_h=24,
            ascii_fps=10,
            screen_w=40,
            screen_h=24,
            screen_fps=10,
            mode=5,
            pixel=True,
        )
    except Exception as exc:
        import traceback
        msg = f"_make_client FAILED: {exc}\n{traceback.format_exc()}"
        _log.error(msg)
        _write_crash(msg)
        return None


if __name__ == "__main__":
    LabhairLiomApp().run()
