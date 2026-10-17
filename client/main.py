#!/usr/bin/env python3
"""E2E encrypted chat client with Labhair-liom video and ADPCM voice."""

from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import os
import queue
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from typing import TYPE_CHECKING, Callable

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from shared.adpcm import SAMPLE_RATE
from shared.settings import Settings
from shared.crypto import (
    SessionKeys,
    b64,
    b64d,
    derive_session,
    generate_identity,
    new_ephemeral,
)
from shared.protocol import FrameReader, MsgType, Packet, pack_json, unpack_json
from shared.image_share import (
    ImageMessage,
    load_and_convert,
    pack_image_payload,
    unpack_image_payload,
    save_received_image,
    format_image_info,
    format_image_preview,
    DEFAULT_QUALITY,
)
from shared.file_share import (
    FileMessage,
    make_file_id,
    pack_file_payload,
    unpack_file_payload,
    save_received_file,
    format_file_info,
    MAX_FILE_SIZE,
)
from shared.privacy import inspect_file, neutral_filename, sanitize_image

if TYPE_CHECKING:
    from client.audio_io import VoiceEngine
    from client.video_io import VideoEngine


def _enable_windows_vt() -> None:
    """Enable VT100 escape code processing on Windows console."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        STD_OUTPUT_HANDLE = -11
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    except Exception:
        pass  # best-effort; works on Windows Terminal without this


_enable_windows_vt()


class ChatClient:
    AVATAR_MAX_SIZE = 8 * 1024 * 1024  # 8MB
    AVATAR_MIN_DIM = 16
    AVATAR_TARGET_SIZE = 32  # resize to this
    AVATAR_MIME_TYPES = {"image/png", "image/jpeg", "image/gif"}

    def __init__(
        self,
        host: str,
        port: int,
        room: str,
        user_id: str,
        display: str,
        voice: bool,
        video: bool,
        screen: bool,
        cam: int,
        monitor: int,
        ascii_w: int,
        ascii_h: int,
        ascii_fps: int,
        screen_w: int,
        screen_h: int,
        screen_fps: int,
        mode: int,
        pixel: bool,
        auto_show_screen: bool = False,
        want_viewer: bool = False,
        tor_proxy: str = "",
        upnp: bool = False,
        tls: bool = False,
        tls_no_verify: bool = False,
    ) -> None:
        self.host = host
        self.port = port
        self.room = room
        self.user_id = user_id
        self.display = display
        self.want_voice = voice
        self.want_video = video
        self.want_screen = screen
        self.want_viewer = want_viewer
        self.cam = cam
        self.monitor = monitor
        self.ascii_w = ascii_w
        self.ascii_h = ascii_h
        self.ascii_fps = ascii_fps
        self.screen_w = screen_w
        self.screen_h = screen_h
        self.screen_fps = screen_fps
        self.mode = mode
        self.pixel = pixel
        self.auto_show_screen = auto_show_screen
        self.tor_proxy = tor_proxy
        self.upnp = upnp
        self.tls = tls
        self.tls_no_verify = tls_no_verify
        self._upnp_mapping = None
        self._last_shown_seq: dict[str, int] = {}
        self._frame_lines: int = 0  # lines printed by last video frame (for in-place update)
        self._received_images: dict[str, tuple[ImageMessage, bytes, str]] = {}  # id → (meta, webp, preview)
        self._received_files: dict[str, tuple[FileMessage, bytes]] = {}  # id → (meta, file_bytes)
        self._last_invites: list[dict] = []  # invite list for current server
        self._input_device: int | None = None
        self._output_device: int | None = None
        self.settings = Settings()
        # Apply saved device settings
        if self.settings.input_device is not None:
            self._input_device = self.settings.input_device
        if self.settings.output_device is not None:
            self._output_device = self.settings.output_device
        # Apply saved camera/monitor settings
        self.cam = self.settings.camera_index
        self.monitor = self.settings.screen_monitor

        self.identity_priv, self.identity_pub = generate_identity()
        self.eph_priv: X25519PrivateKey | None = None
        self.eph_pub: bytes = b""

        self.sessions: dict[str, SessionKeys] = {}
        self._seen_sessions: set[str] = set()
        self.peer_identity: dict[str, bytes] = {}
        self.peer_display: dict[str, str] = {}
        self.pending_eph: dict[str, bytes] = {}  # peer → their eph pub awaiting ours

        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.loop: asyncio.AbstractEventLoop | None = None

        self.voice: VoiceEngine | None = None
        self.video: VideoEngine | None = None
        self._stop = asyncio.Event()
        self._print_lock = threading.Lock()
        self.voice_active_peers: dict[str, bool] = {}
        self.voice_is_active: bool = False
        self.screen_active_peers: dict[str, bool] = {}  # peer uid -> streaming screen
        self.camera_active_peers: dict[str, bool] = {}  # peer uid -> camera on
        self.on_streaming_update: Callable[[], None] | None = None  # fires on screen/camera presence change
        self._speaking_users: dict[str, bool] = {}  # user_id -> currently speaking
        self.on_speaking_update: Callable[[str, bool], None] | None = None  # fires(user_id, speaking)
        self._gui_queue: queue.Queue | None = None  # set by GUI
        self._gui_mode: bool = False
        self._channel_keys: dict[int, bytes] = {}  # channel_id → AES-256 key bytes

        # Auth state
        self.auth_token: str = ""
        self.db_user_id: int = 0
        self.authenticated: bool = False

        # Server/channel navigation state
        self.current_server_id: int = 0
        self.current_channel_id: int = 0
        self.servers: list[dict] = []
        self.channels: list[dict] = []
        self.members: list[dict] = []
        self.current_dm_user_id: int = 0  # >0 when viewing a DM conversation

        # Callbacks for GUI refresh (set by GUI)
        self.on_servers_updated: Callable[[], None] | None = None
        self.on_channels_updated: Callable[[], None] | None = None
        self.on_members_updated: Callable[[], None] | None = None
        self.on_messages_updated: Callable[[list[dict]], None] | None = None
        self.on_message_received: Callable[[dict], None] | None = None
        self.on_voice_members_update: Callable[[int, list[dict]], None] | None = None
        self.on_dm_updated: Callable[[list[dict]], None] | None = None
        self.on_dm_conversations: Callable[[list[dict]], None] | None = None
        self.on_dm_message: Callable[[dict], None] | None = None
        self.on_dm_unread: Callable[[int], None] | None = None
        self.on_dm_ignore_result: Callable[[int, bool], None] | None = None
        self.on_friends_updated: Callable[[list[dict]], None] | None = None
        self.on_friend_requests_updated: Callable[[list[dict]], None] | None = None
        self.on_settings_updated: Callable[[dict], None] | None = None
        self.on_reaction_updated: Callable[[dict], None] | None = None
        self.on_threads_updated: Callable[[], None] | None = None
        self.on_thread_list: Callable[[list[dict]], None] | None = None
        self.on_search_results: Callable[[list[dict]], None] | None = None
        self.on_auth_success: Callable[[dict], None] | None = None
        self.on_auth_error: Callable[[dict], None] | None = None
        self.on_local_video_frame: Callable[[bytes, str, str], None] | None = None
        self.on_remote_video_frame: Callable[[bytes, str, str], None] | None = None
        self._dm_conversations: list[dict] = []
        self.dm_unread_total: int = 0
        self.friend_request_count: int = 0
        self.auto_ignore_dm: bool = False
        self.settings_loaded: bool = False

    def _emit_dm_unread(self) -> None:
        """Notify the GUI of the combined unread badge count (DMs + friend reqs)."""
        if self.on_dm_unread:
            self.on_dm_unread(self.dm_unread_total + self.friend_request_count)

    # --- UI helpers ----------------------------------------------------------

    def ui(self, msg: str) -> None:
        if self._gui_queue is not None:
            self._gui_queue.put(("ui", (msg,), {}))
            return
        with self._print_lock:
            sys.stdout.write(msg + "\n")
            sys.stdout.flush()

    def ui_status(self, msg: str) -> None:
        if self._gui_queue is not None:
            self._gui_queue.put(("ui_status", (msg,), {}))
            return
        self.ui(f"\033[90m* {msg}\033[0m")

    def ui_sys(self, msg: str) -> None:
        if self._gui_queue is not None:
            self._gui_queue.put(("ui_sys", (msg,), {}))
            return
        self.ui(f"\033[36m* {msg}\033[0m")

    def ui_warning(self, msg: str) -> None:
        if self._gui_queue is not None:
            self._gui_queue.put(("ui_warning", (msg,), {}))
            return
        self.ui(f"\033[91mWARNING: {msg}\033[0m")

    def ui_typing(self, username: str) -> None:
        if self._gui_queue is not None:
            self._gui_queue.put(("ui_typing", (username,), {}))
            return
        # No-op for terminal client

    def ui_chat(self, who: str, text: str, mentioned: bool = False) -> None:
        if self._gui_queue is not None:
            self._gui_queue.put(("ui_chat", (who, text), {"mentioned": mentioned}))
            return
        self.ui(f"\033[1m<{who}>\033[0m {text}")
        # Play notification sound for incoming messages
        self._play_notification_sound()
        if mentioned:
            self._play_notification_sound()
            self.ui_sys("💬 You were mentioned!")

    def _play_notification_sound(self, dm: bool = False) -> None:
        """Play a notification beep if enabled in settings."""
        if not self.settings.notification_sound and not dm:
            return
        if dm and not self.settings.notification_dm_sound:
            return
        vol = self.settings.notification_volume
        if vol <= 0:
            return
        try:
            import sounddevice as sd
            import numpy as np
            sr = 22050
            duration = 0.15
            t = np.linspace(0, duration, int(sr * duration), dtype=np.float32)
            # Pleasant two-tone beep
            freq1 = 880 if dm else 660
            freq2 = 1100 if dm else 880
            tone = (np.sin(2 * np.pi * freq1 * t) * 0.3 +
                    np.sin(2 * np.pi * freq2 * t) * 0.2) * vol
            # Fade out
            fade = np.linspace(1.0, 0.0, len(tone), dtype=np.float32)
            tone = (tone * fade).astype(np.float32)
            sd.play(tone, sr, blocking=False)
        except Exception:
            pass  # silent fallback

    def ui_video_jpeg(self, jpeg_bytes: bytes, source: str, sender: str = "?") -> None:
        """Push a raw JPEG frame to the GUI (if active)."""
        if self._gui_queue is not None:
            self._gui_queue.put(("ui_video_jpeg", (jpeg_bytes, source, sender), {}))

    def ui_image(self, image_id: str, webp_bytes: bytes, sender: str, name: str, width: int, height: int) -> None:
        """Push a received image to the GUI for pixel display."""
        if self._gui_queue is not None:
            self._gui_queue.put(("ui_image", (image_id, webp_bytes, sender, name, width, height), {}))

    def ui_file(self, file_id: str, file_bytes: bytes, sender: str, name: str, mime_type: str, size: int) -> None:
        """Push a received file to the GUI for display."""
        if self._gui_queue is not None:
            self._gui_queue.put(("ui_file", (file_id, file_bytes, sender, name, mime_type, size), {}))

    def ui_video_frame(self, text: str, label: str = "Labhair-liom") -> None:
        lines = text.splitlines()
        if not lines:
            return
        n = len(lines)
        with self._print_lock:
            # Move cursor up to overwrite previous frame if we printed one
            if self._frame_lines > 0:
                sys.stdout.write(f"\033[{self._frame_lines + 1}A")
            # Header line
            sys.stdout.write(f"\033[33m── {label} ({n} rows) ──\033[0m\033[K\n")
            for line in lines:
                sys.stdout.write(line + "\033[K\n")
            sys.stdout.flush()
            self._frame_lines = n + 1  # header + frame rows

    # --- networking ----------------------------------------------------------

    async def connect(self) -> None:
        self.loop = asyncio.get_running_loop()
        ssl_ctx = None
        if self.tls:
            import ssl
            ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            if self.tls_no_verify:
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE
        try:
            if self.tor_proxy:
                try:
                    from python_socks.async_.asyncio import Proxy
                except ImportError:
                    self.ui_status("python-socks not installed. Run: pip install python-socks[asyncio]")
                    raise SystemExit(1)
                proxy = Proxy.from_url(self.tor_proxy)
                sock = await proxy.connect(dest_host=self.host, dest_port=self.port)
                self.reader, self.writer = await asyncio.open_connection(sock=sock, ssl=ssl_ctx)
            else:
                self.reader, self.writer = await asyncio.open_connection(self.host, self.port, ssl=ssl_ctx)
        except OSError as exc:
            self.ui_status(f"Cannot connect to {self.host}:{self.port} — {exc}")
            raise
        hello = pack_json(
            MsgType.HELLO,
            {
                "user_id": self.user_id,
                "display": self.display,
                "room": self.room,
                "identity_pub": b64(self.identity_pub),
            },
        )
        await self._send(hello)
        self.ui_sys(
            f"connected to {self.host}:{self.port} room={self.room!r} as {self.user_id}"
            + (" (via Tor)" if self.tor_proxy else "")
            + (" (TLS)" if self.tls else "")
        )
        self.ui_sys(f"identity fingerprint: {self._fp(self.identity_pub)}")
        self.ui_sys(
            "commands: /voice on|off|listen  /video on|off  /screen on|off  "
            "/screen show on|off  /monitor N  /monitors  /region L T W H  "
            "/peers  /show [camera|screen]  /mic N  /speaker N  /devices  "
            "/viewer [off]  /sendimage <path>  /sendfile <path>  /images  /files  /download <id>  /help  /quit"
        )

    async def _send(self, pkt: Packet) -> None:
        assert self.writer is not None
        self.writer.write(pkt.encode())
        await self.writer.drain()

    async def _send_request(self, msg_type: MsgType, body: dict | None = None) -> None:
        """Send a plaintext JSON packet to the server (management channel)."""
        await self._send(pack_json(msg_type, body or {}))

    # --- Auth helpers ---------------------------------------------------------

    async def send_register(self, username: str, email: str, password: str) -> None:
        await self._send_request(MsgType.REGISTER, {
            "username": username, "email": email, "password": password,
        })

    async def send_login(self, username: str, password: str) -> None:
        await self._send_request(MsgType.LOGIN, {
            "username": username, "password": password,
        })

    async def send_admin_auth_request(self, display: str = "") -> None:
        await self._send_request(MsgType.ADMIN_AUTH_REQUEST, {"display": display})

    async def send_logout(self) -> None:
        await self._send_request(MsgType.LOGOUT)

    # --- Server helpers -------------------------------------------------------

    async def send_server_create(self, name: str) -> None:
        await self._send_request(MsgType.SERVER_CREATE, {"name": name})

    async def send_server_join(self, server_id: int) -> None:
        await self._send_request(MsgType.SERVER_JOIN, {"server_id": server_id})

    async def send_server_leave(self, server_id: int) -> None:
        await self._send_request(MsgType.SERVER_LEAVE, {"server_id": server_id})

    async def send_server_list(self) -> None:
        await self._send_request(MsgType.SERVER_LIST)

    async def send_server_info(self, server_id: int) -> None:
        await self._send_request(MsgType.SERVER_INFO, {"server_id": server_id})

    async def send_server_update(self, server_id: int, **kwargs) -> None:
        await self._send_request(MsgType.SERVER_UPDATE, {"server_id": server_id, **kwargs})

    async def send_channel_update(self, channel_id: int, **kwargs) -> None:
        await self._send_request(MsgType.CHANNEL_UPDATE, {"channel_id": channel_id, **kwargs})

    async def send_role_update(self, role_id: int, **kwargs) -> None:
        await self._send_request(MsgType.ROLE_UPDATE, {"role_id": role_id, **kwargs})

    async def send_role_delete(self, role_id: int) -> None:
        await self._send_request(MsgType.ROLE_DELETE, {"role_id": role_id})

    async def send_role_create(self, server_id: int, name: str, color: int = 0, permissions: int = 0) -> None:
        await self._send_request(MsgType.ROLE_CREATE, {"server_id": server_id, "name": name, "color": color, "permissions": permissions})

    async def send_role_list(self, server_id: int) -> None:
        await self._send_request(MsgType.ROLE_LIST, {"server_id": server_id})

    async def send_status_update(self, status: str) -> None:
        await self._send_request(MsgType.STATUS_UPDATE, {"status": status})

    async def send_invite_create(self, server_id: int, max_uses: int = 0, expires_in_seconds: int = 0) -> None:
        await self._send_request(MsgType.INVITE_CREATE, {"server_id": server_id, "max_uses": max_uses, "expires_in_seconds": expires_in_seconds})

    async def send_invite_join(self, code: str) -> None:
        await self._send_request(MsgType.INVITE_JOIN, {"code": code})

    async def send_invite_list(self, server_id: int) -> None:
        await self._send_request(MsgType.INVITE_LIST, {"server_id": server_id})

    async def send_invite_delete(self, invite_id: int, server_id: int) -> None:
        await self._send_request(MsgType.INVITE_DELETE, {"invite_id": invite_id, "server_id": server_id})

    async def send_msg_pin(self, message_id: int) -> None:
        await self._send_request(MsgType.MSG_PIN, {"message_id": message_id})

    async def send_msg_unpin(self, message_id: int) -> None:
        await self._send_request(MsgType.MSG_UNPIN, {"message_id": message_id})

    async def send_pinned_list(self, channel_id: int) -> None:
        await self._send_request(MsgType.MSG_PINNED_LIST, {"channel_id": channel_id})

    async def send_profile_get(self, user_id: int = 0) -> None:
        await self._send_request(MsgType.PROFILE_GET, {"user_id": user_id})

    async def send_avatar_get(self, user_id: int) -> None:
        await self._send_request(MsgType.AVATAR_GET, {"user_id": user_id})

    async def send_profile_update(self, bio: str = None, avatar_url: str = None, custom_status: str = None, avatar_path: str = None) -> str:
        body = {}
        if bio is not None:
            body["bio"] = bio
        if avatar_url is not None:
            body["avatar_url"] = avatar_url
        if custom_status is not None:
            body["custom_status"] = custom_status
        if avatar_path:
            if not os.path.isfile(avatar_path):
                return "Warning: avatar file not found"
            size = os.path.getsize(avatar_path)
            if size > self.AVATAR_MAX_SIZE:
                return f"Warning: avatar too large ({size} bytes, max {self.AVATAR_MAX_SIZE})"
            from PIL import Image
            from io import BytesIO
            try:
                img = Image.open(avatar_path)
                img.verify()
                img = Image.open(avatar_path)
            except Exception:
                return "Warning: image file is corrupted or unreadable"
            w, h = img.size
            if w < self.AVATAR_MIN_DIM or h < self.AVATAR_MIN_DIM:
                return f"Warning: image too small ({w}x{h}), minimum is {self.AVATAR_MIN_DIM}x{self.AVATAR_MIN_DIM}"
            mime = mimetypes.guess_type(avatar_path)[0] or "image/png"
            if mime not in self.AVATAR_MIME_TYPES:
                return f"Warning: unsupported format {mime} (use PNG, JPEG, or GIF)"
            img = img.convert("RGBA") if img.mode == "RGBA" else img.convert("RGB")
            img = img.resize((32, 32), Image.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="PNG")
            data = buf.getvalue()
            body["avatar"] = b64(data)
            body["avatar_mime"] = "image/png"
        await self._send_request(MsgType.PROFILE_UPDATE, body)
        return ""

    async def send_server_delete(self, server_id: int) -> None:
        await self._send_request(MsgType.SERVER_DELETE, {"server_id": server_id})

    # --- Channel helpers ------------------------------------------------------

    async def send_channel_create(self, server_id: int, name: str, channel_type: str = "text") -> None:
        await self._send_request(MsgType.CHANNEL_CREATE, {
            "server_id": server_id, "name": name, "channel_type": channel_type,
        })

    async def send_channel_delete(self, channel_id: int) -> None:
        await self._send_request(MsgType.CHANNEL_DELETE, {"channel_id": channel_id})

    async def send_channel_list(self, server_id: int) -> None:
        await self._send_request(MsgType.CHANNEL_LIST, {"server_id": server_id})

    async def send_channel_join(self, channel_id: int) -> None:
        self.current_channel_id = channel_id
        await self._send_request(MsgType.CHANNEL_JOIN, {"channel_id": channel_id})

    # --- Message helpers ------------------------------------------------------

    async def send_message_send(self, channel_id: int, content: str, **kwargs) -> None:
        await self._send_request(MsgType.MESSAGE_SEND, {
            "channel_id": channel_id, "content": content, **kwargs,
        })

    def _get_channel_key(self, channel_id: int) -> bytes | None:
        """Get the AES-256 key for a channel (32 raw bytes)."""
        return self._channel_keys.get(channel_id)

    def _encrypt_with_key(self, key: bytes, plaintext: bytes) -> bytes:
        """AES-256-GCM encrypt. Returns nonce(12) || ciphertext||tag."""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = os.urandom(12)
        ct = AESGCM(key).encrypt(nonce, plaintext, None)
        return nonce + ct

    def _decrypt_with_key(self, key: bytes, blob: bytes) -> bytes:
        """AES-256-GCM decrypt (reverses _encrypt_with_key)."""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        if len(blob) < 12 + 16:
            raise ValueError("ciphertext too short")
        nonce, ct = blob[:12], blob[12:]
        return AESGCM(key).decrypt(nonce, ct, None)

    async def _fetch_channel_key(self, channel_id: int) -> None:
        """Request the channel encryption key from the server."""
        await self._send_request(MsgType.CHANNEL_JOIN, {"channel_id": channel_id})

    def _derive_channel_key(self, channel_key_b64: str, channel_id: int) -> bytes:
        """Derive a 32-byte AES key from the base64 channel key."""
        import base64 as _b64
        raw = _b64.b64decode(channel_key_b64)
        # The key is stored as a 32-byte token_urlsafe → 32 raw bytes when decoded
        if len(raw) == 32:
            return raw
        # If it was stored differently, derive via HKDF
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives import hashes
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=str(channel_id).encode(),
            info=b"channel-attachment-key",
        ).derive(raw)

    async def send_image_channel(self, path: str) -> None:
        """Send an image as an E2E-encrypted attachment in the current channel."""
        import base64 as _b64
        from pathlib import Path
        p = Path(path)
        if not p.is_file():
            self.ui_status(f"file not found: {path}")
            return
        key = self._get_channel_key(self.current_channel_id)
        if not key:
            self.ui_status("channel encryption key not available — rejoin channel")
            return
        try:
            from shared.image_share import load_and_convert
            meta, webp_bytes, preview = load_and_convert(path)
            meta.name = p.name
            # Encrypt the image data with channel key
            encrypted_data = self._encrypt_with_key(key, webp_bytes)
            content = f"[image: {meta.name} {meta.width}x{meta.height}]"
            attachment = {
                "type": "image",
                "name": p.name,
                "data": _b64.b64encode(encrypted_data).decode(),
                "mime": "image/webp",
                "size": len(webp_bytes),
                "width": meta.width,
                "height": meta.height,
                "encrypted": True,
            }
            await self.send_message_send(
                self.current_channel_id, content, attachments=[attachment],
            )
        except Exception as exc:
            self.ui_status(f"image send failed: {exc}")

    async def send_file_channel(self, path: str) -> None:
        """Send a file as an E2E-encrypted attachment in the current channel."""
        import base64 as _b64
        from pathlib import Path
        p = Path(path)
        if not p.is_file():
            self.ui_status(f"file not found: {path}")
            return
        key = self._get_channel_key(self.current_channel_id)
        if not key:
            self.ui_status("channel encryption key not available — rejoin channel")
            return
        data = p.read_bytes()
        if len(data) > 10 * 1024 * 1024:
            self.ui_status("file too large (max 10 MB)")
            return
        # Encrypt the file data with channel key
        encrypted_data = self._encrypt_with_key(key, data)
        import mimetypes
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        content = f"[file: {p.name}]"
        attachment = {
            "type": "file",
            "name": p.name,
            "data": _b64.b64encode(encrypted_data).decode(),
            "mime": mime,
            "size": len(data),
            "encrypted": True,
        }
        await self.send_message_send(
            self.current_channel_id, content, attachments=[attachment],
        )

    async def send_typing_start(self, channel_id: int) -> None:
        await self._send_request(MsgType.TYPING_START, {"channel_id": channel_id})

    async def send_message_history(self, channel_id: int, limit: int = 50, before: int | None = None) -> None:
        body: dict = {"channel_id": channel_id, "limit": limit}
        if before is not None:
            body["before"] = before
        await self._send_request(MsgType.MESSAGE_HISTORY, body)

    async def send_message_edit(self, message_id: int, content: str) -> None:
        await self._send_request(MsgType.MESSAGE_EDIT, {
            "message_id": message_id, "content": content,
        })

    async def send_message_delete(self, message_id: int) -> None:
        await self._send_request(MsgType.MESSAGE_DELETE, {"message_id": message_id})

    # --- Reaction helpers -----------------------------------------------------

    async def send_reaction_add(self, message_id: int, emoji: str) -> None:
        await self._send_request(MsgType.MESSAGE_REACTION_ADD, {
            "message_id": message_id, "emoji": emoji,
        })

    async def send_reaction_remove(self, message_id: int, emoji: str) -> None:
        await self._send_request(MsgType.MESSAGE_REACTION_REMOVE, {
            "message_id": message_id, "emoji": emoji,
        })

    # --- Thread helpers -------------------------------------------------------

    async def send_thread_create(self, channel_id: int, name: str, parent_message_id: int | None = None) -> None:
        body: dict = {"channel_id": channel_id, "name": name}
        if parent_message_id is not None:
            body["parent_message_id"] = parent_message_id
        await self._send_request(MsgType.THREAD_CREATE, body)

    async def send_thread_join(self, thread_id: int) -> None:
        await self._send_request(MsgType.THREAD_JOIN, {"thread_id": thread_id})

    async def send_thread_leave(self, thread_id: int) -> None:
        await self._send_request(MsgType.THREAD_LEAVE, {"thread_id": thread_id})

    async def send_thread_list(self, channel_id: int) -> None:
        await self._send_request(MsgType.THREAD_LIST, {"channel_id": channel_id})

    async def send_thread_info(self, thread_id: int) -> None:
        await self._send_request(MsgType.THREAD_INFO, {"thread_id": thread_id})

    async def send_thread_message(self, thread_id: int, content: str) -> None:
        await self._send_request(MsgType.THREAD_MESSAGE_SEND, {
            "thread_id": thread_id, "content": content,
        })

    async def send_thread_history(self, thread_id: int, limit: int = 50, before: int | None = None) -> None:
        body: dict = {"thread_id": thread_id, "limit": limit}
        if before is not None:
            body["before"] = before
        await self._send_request(MsgType.THREAD_MESSAGE_HISTORY, body)

    async def send_thread_archive(self, thread_id: int) -> None:
        await self._send_request(MsgType.THREAD_ARCHIVE, {"thread_id": thread_id})

    # --- Search helpers -------------------------------------------------------

    async def send_search_messages(self, query: str, server_id: int | None = None,
                                   channel_id: int | None = None, limit: int = 50) -> None:
        body: dict = {"query": query, "limit": limit}
        if server_id is not None:
            body["server_id"] = server_id
        if channel_id is not None:
            body["channel_id"] = channel_id
        await self._send_request(MsgType.SEARCH_MESSAGES, body)

    # --- DM helpers -----------------------------------------------------------

    async def send_dm_send(self, recipient_id: int, content: str) -> None:
        await self._send_request(MsgType.DM_SEND, {
            "recipient_id": recipient_id, "content": content,
        })

    async def send_dm_history(self, user_id: int, limit: int = 50, before: int | None = None) -> None:
        body: dict = {"user_id": user_id, "limit": limit}
        if before is not None:
            body["before"] = before
        await self._send_request(MsgType.DM_HISTORY, body)

    async def send_dm_list(self) -> None:
        await self._send_request(MsgType.DM_LIST)

    async def send_dm_read(self, user_id: int) -> None:
        await self._send_request(MsgType.DM_READ, {"user_id": user_id})

    async def send_dm_ignore(self, user_id: int) -> None:
        await self._send_request(MsgType.DM_IGNORE, {"user_id": user_id})

    # --- Friend helpers -------------------------------------------------------

    async def send_friend_add(self, friend_id: int) -> None:
        await self._send_request(MsgType.FRIEND_ADD, {"friend_id": friend_id})

    async def send_friend_remove(self, friend_id: int) -> None:
        await self._send_request(MsgType.FRIEND_REMOVE, {"friend_id": friend_id})

    async def send_friend_list(self) -> None:
        await self._send_request(MsgType.FRIEND_LIST)

    async def send_friend_accept(self, friend_id: int) -> None:
        await self._send_request(MsgType.FRIEND_ACCEPT, {"friend_id": friend_id})

    async def send_friend_decline(self, friend_id: int) -> None:
        await self._send_request(MsgType.FRIEND_DECLINE, {"friend_id": friend_id})

    async def send_friend_requests(self) -> None:
        await self._send_request(MsgType.FRIEND_REQUESTS)

    # --- User settings --------------------------------------------------------

    async def send_settings_get(self) -> None:
        await self._send_request(MsgType.SETTINGS_GET)

    async def send_settings_update(self, auto_ignore_dm: bool) -> None:
        await self._send_request(MsgType.SETTINGS_UPDATE, {"auto_ignore_dm": auto_ignore_dm})

    # --- Member helpers -------------------------------------------------------

    async def send_member_list(self, server_id: int) -> None:
        await self._send_request(MsgType.MEMBER_LIST, {"server_id": server_id})

    async def send_member_leave(self, server_id: int) -> None:
        await self._send_request(MsgType.MEMBER_LEAVE, {"server_id": server_id})

    async def send_member_kick(self, server_id: int, target_id: int) -> None:
        await self._send_request(MsgType.MEMBER_KICK, {
            "server_id": server_id, "target_id": target_id,
        })

    async def send_member_ban(self, server_id: int, target_id: int, reason: str = "") -> None:
        await self._send_request(MsgType.MEMBER_BAN, {
            "server_id": server_id, "target_id": target_id, "reason": reason,
        })

    # --- Status helpers -------------------------------------------------------

    def _fp(self, pub: bytes) -> str:
        import hashlib

        return hashlib.sha256(pub).hexdigest()[:16]

    def _i_am_initiator(self, peer_id: str, peer_pub: bytes) -> bool:
        # Deterministic: lower identity fingerprint initiates
        return self.identity_pub < peer_pub or (
            self.identity_pub == peer_pub and self.user_id < peer_id
        )

    async def _ensure_session(self, peer_id: str) -> SessionKeys | None:
        if peer_id in self.sessions:
            return self.sessions[peer_id]
        peer_pub = self.peer_identity.get(peer_id)
        if not peer_pub:
            return None
        # Start key exchange if we don't have one in flight
        if self.eph_priv is None:
            self.eph_priv, self.eph_pub = new_ephemeral()
        await self._send(
            pack_json(
                MsgType.KEY_EXCHANGE,
                {
                    "from": self.user_id,
                    "to": peer_id,  # advisory; room-broadcast
                    "identity_pub": b64(self.identity_pub),
                    "ephemeral_pub": b64(self.eph_pub),
                },
            )
        )
        return None

    async def _complete_session(self, peer_id: str, peer_eph: bytes) -> None:
        peer_pub = self.peer_identity.get(peer_id)
        if not peer_pub:
            return
        if self.eph_priv is None:
            self.eph_priv, self.eph_pub = new_ephemeral()
            # send our eph so peer can finish too
            await self._send(
                pack_json(
                    MsgType.KEY_EXCHANGE,
                    {
                        "from": self.user_id,
                        "to": peer_id,
                        "identity_pub": b64(self.identity_pub),
                        "ephemeral_pub": b64(self.eph_pub),
                    },
                )
            )
        initiator = self._i_am_initiator(peer_id, peer_pub)
        try:
            sess = derive_session(
                self.identity_priv,
                self.eph_priv,
                peer_pub,
                peer_eph,
                i_am_initiator=initiator,
            )
        except Exception as exc:
            self.ui_status(f"key exchange failed with {peer_id}: {exc}")
            return
        self.sessions[peer_id] = sess
        if peer_id not in self._seen_sessions:
            self._seen_sessions.add(peer_id)
            self.ui_sys(
                f"E2E session established with {self.peer_display.get(peer_id, peer_id)} "
                f"[{self._fp(peer_pub)}] initiator={initiator}"
            )

    async def _encrypt_to_all(self, msg_type: MsgType, plaintext: bytes, meta: dict | None = None) -> None:
        """Encrypt the same plaintext under each peer session and send envelopes."""
        if not self.sessions:
            return
        for peer_id, sess in list(self.sessions.items()):
            try:
                aad = f"{self.user_id}|{peer_id}|{int(msg_type)}".encode()
                ct = sess.encrypt(plaintext, aad=aad)
                body = {
                    "from": self.user_id,
                    "to": peer_id,
                    "ct": b64(ct),
                }
                if meta:
                    body.update(meta)
                await self._send(pack_json(msg_type, body))
            except Exception as exc:
                self.ui_status(f"encrypt error → {peer_id}: {exc}")

    async def send_chat(self, text: str) -> None:
        if not self.sessions:
            self.ui_status("no E2E sessions yet — wait for a peer")
            return
        payload = json.dumps({"text": text}, separators=(",", ":")).encode()
        await self._encrypt_to_all(MsgType.CHAT, payload)
        self.ui_chat(self.display, text)

    async def send_image(self, path: str, orig_name: str = "") -> None:
        if not self.sessions:
            self.ui_status("no E2E sessions yet — wait for a peer")
            return
        try:
            meta, webp_bytes, preview = load_and_convert(path)
        except Exception as exc:
            self.ui_status(f"image load failed: {exc}")
            return
        # Image conversion removes embedded metadata; keep the source name
        # private as well.
        meta.name = "image.webp"
        payload = pack_image_payload(meta, webp_bytes, preview)
        if len(payload) > 1 << 20:
            self.ui_status(f"image too large after WebP ({len(payload)} bytes)")
            return
        await self._encrypt_to_all(MsgType.IMAGE, payload)
        size_kb = meta.webp_size / 1024
        self.ui_sys(
            f"sent image {meta.name} ({meta.width}x{meta.height}, "
            f"WebP {size_kb:.1f} KB, id={meta.id})"
        )

    async def send_file(self, path: str, orig_name: str = "", allow_unsanitized: bool = False) -> None:
        if not self.sessions:
            self.ui_status("no E2E sessions yet — wait for a peer")
            return
        import hashlib as _hl
        from pathlib import Path as _P
        p = _P(path)
        if not p.is_file():
            self.ui_status(f"file not found: {path}")
            return
        report = inspect_file(p)
        if report.warning and not allow_unsanitized:
            self.ui_warning(report.warning + " Send cancelled.")
            return
        if report.can_strip:
            try:
                file_bytes, safe_name, mime = sanitize_image(p)
            except Exception as exc:
                self.ui_warning(f"Identifying metadata could not be stripped ({exc}). Send cancelled.")
                return
            safe_name = safe_name if allow_unsanitized is False else safe_name
        else:
            file_bytes = p.read_bytes()
            safe_name = neutral_filename(p, orig_name)
            mime = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
            if allow_unsanitized:
                self.ui_warning("IDENTIFYING METADATA NOT STRIPPED — file sent as selected.")
        if len(file_bytes) > MAX_FILE_SIZE:
            self.ui_status(f"file too large ({len(file_bytes)} bytes, max {MAX_FILE_SIZE})")
            return
        meta = FileMessage(
            id=make_file_id(file_bytes),
            name=safe_name,
            mime_type=mime,
            size=len(file_bytes),
            sha256=_hl.sha256(file_bytes).hexdigest(),
        )
        payload = pack_file_payload(meta, file_bytes)
        await self._encrypt_to_all(MsgType.FILE, payload)
        size_kb = len(file_bytes) / 1024
        self.ui_sys(
            f"sent file {meta.name} ({mime}, {size_kb:.1f} KB, id={meta.id})"
        )

    # --- media hooks (called from other threads) -----------------------------

    def _voice_frame_cb(self, blob: bytes, track: str = "mic") -> None:
        if not self.loop or not self.sessions:
            return
        meta = {"codec": "ADPCM/IMA", "sr": SAMPLE_RATE, "ptime": 20}
        asyncio.run_coroutine_threadsafe(
            self._encrypt_to_all(MsgType.VOICE, blob, meta=meta),
            self.loop,
        )

    def _on_speaking(self, sender: str, speaking: bool) -> None:
        """Called from VoiceEngine when a remote user starts/stops speaking."""
        self._speaking_users[sender] = speaking
        if self.on_speaking_update:
            try:
                self.on_speaking_update(sender, speaking)
            except Exception:
                pass
        # Broadcast speaking state to other peers
        if self.loop:
            asyncio.run_coroutine_threadsafe(
                self._send_speaking_state(sender, speaking), self.loop
            )

    async def _send_speaking_state(self, sender: str, speaking: bool) -> None:
        """Send speaking indicator to all peers via CONTROL."""
        if not self.sessions:
            return
        for peer_id, sess in list(self.sessions.items()):
            try:
                payload = json.dumps({"speaking_user": sender, "speaking": speaking}).encode()
                aad = f"{self.user_id}|{peer_id}|{int(MsgType.CONTROL)}".encode()
                ct = sess.encrypt(payload, aad=aad)
                body = {"from": self.user_id, "to": peer_id, "ct": b64(ct)}
                await self._send(pack_json(MsgType.CONTROL, body))
            except Exception:
                pass

    def _video_frame_cb(self, blob: bytes, source: str) -> None:
        if not self.loop or not self.sessions:
            return
        meta = {"codec": "LABHAIR-LIOM/1.0", "source": source}
        asyncio.run_coroutine_threadsafe(
            self._encrypt_to_all(MsgType.VIDEO, blob, meta=meta),
            self.loop,
        )

    def _emit_local_video_frame(self, jpg_bytes: bytes, source: str, resolution: str) -> None:
        """Fired from the capture thread with each locally captured JPEG frame."""
        cb = self.on_local_video_frame
        if cb:
            try:
                cb(jpg_bytes, source, resolution)
            except Exception:
                pass

    def _gui_sized_jpeg(self, jpg_bytes: bytes) -> bytes:
        """Downscale a remote JPEG to <=854px wide for the Flet panel.

        Safety net for senders that embed full-resolution img_b64 in their
        Labhair-liom frames (e.g. older android builds): full-res base64 pushed
        through page.update() is what makes remote viewers crawl at ~1fps.
        """
        try:
            import cv2
            import numpy as np
            arr = cv2.imdecode(np.frombuffer(jpg_bytes, np.uint8), cv2.IMREAD_COLOR)
            if arr is None:
                return jpg_bytes
            h, w = arr.shape[:2]
            if w <= 854:
                return jpg_bytes
            ph = max(1, round(h * 854 / w))
            small = cv2.resize(arr, (854, ph), interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 60])
            return buf.tobytes() if ok else jpg_bytes
        except Exception:
            return jpg_bytes

    def _emit_remote_video_frame(self, jpg_bytes: bytes, source: str, sender: str) -> None:
        """Fired from the network thread with each decoded remote video frame."""
        cb = self.on_remote_video_frame
        if cb:
            try:
                cb(jpg_bytes, source, sender)
            except Exception:
                pass

    def _ensure_video_engine(self) -> "VideoEngine":
        from client.video_io import VideoEngine
        if self.video is None:
            self.video = VideoEngine(
                self._video_frame_cb,
                width=self.ascii_w,
                height=self.ascii_h,
                fps=self.ascii_fps,
                camera_index=self.cam,
                monitor=self.monitor,
                screen_width=self.screen_w,
                screen_height=self.screen_h,
                screen_fps=self.screen_fps,
                mode=self.mode,
                pixel=self.pixel,
            )
            self.video.local_jpeg_cb = self._emit_local_video_frame
        return self.video

    def start_voice(self, listen_only: bool = False) -> None:
        if self.voice is not None:
            return
        from client.audio_io import VoiceEngine
        if listen_only:
            self.voice = VoiceEngine(
                self._voice_frame_cb,
                input_device=None,
                output_device=self._output_device,
            )
            self.voice.on_speaking = self._on_speaking
            try:
                self.voice.start_listen()
                self.ui_sys("voice LISTEN — speaker output only (no mic)")
            except Exception as exc:
                self.voice = None
                self.ui_status(f"voice listen failed: {exc}")
                return
        else:
            self.voice = VoiceEngine(
                self._voice_frame_cb,
                input_device=self._input_device,
                output_device=self._output_device,
            )
            self.voice.on_speaking = self._on_speaking
            try:
                self.voice.start()
                in_dev = self._input_device if self._input_device is not None else "default"
                out_dev = self._output_device if self._output_device is not None else "default"
                self.ui_sys(f"voice ON — ADPCM mic={in_dev} speaker={out_dev}")
            except Exception as exc:
                self.voice = None
                self.ui_status(f"voice failed: {exc}")
                return
        if not self.voice:
            return
        self.voice_is_active = True
        if self.loop:
            asyncio.run_coroutine_threadsafe(
                self._send_voice_presence(self.user_id, True), self.loop
            )

    def stop_voice(self) -> None:
        if self.voice:
            self.voice.stop()
            self.voice = None
            self.voice_is_active = False
            if self.loop:
                asyncio.run_coroutine_threadsafe(
                    self._send_voice_presence(self.user_id, False), self.loop
                )
            self.ui_sys("voice OFF")

    async def _send_voice_presence(self, who: str, active: bool) -> None:
        """Broadcast voice presence to all peers."""
        if not self.sessions:
            return
        for peer_id, sess in list(self.sessions.items()):
            plaintext = f'{{"voice_active":{str(active).lower()},"user":"{who}"}}'.encode()
            aad = f"{self.user_id}|{peer_id}|{int(MsgType.CONTROL)}".encode()
            ct = sess.encrypt(plaintext, aad=aad)
            body = {"from": self.user_id, "to": peer_id, "ct": b64(ct)}
            try:
                await self._send(pack_json(MsgType.CONTROL, body))
            except Exception:
                pass

    async def _send_media_presence(self, who: str, media_type: str, active: bool) -> None:
        """Broadcast screen/camera presence to all peers."""
        if not self.sessions:
            return
        for peer_id, sess in list(self.sessions.items()):
            plaintext = f'{{"media_type":"{media_type}","media_active":{str(active).lower()},"user":"{who}"}}'.encode()
            aad = f"{self.user_id}|{peer_id}|{int(MsgType.CONTROL)}".encode()
            ct = sess.encrypt(plaintext, aad=aad)
            body = {"from": self.user_id, "to": peer_id, "ct": b64(ct)}
            try:
                await self._send(pack_json(MsgType.CONTROL, body))
            except Exception:
                pass

    def start_video(self) -> None:
        eng = self._ensure_video_engine()
        if eng.camera_active:
            return
        eng.start_camera()
        note = "camera" if eng._cap is not None else "test-pattern (no camera)"
        self.ui_sys(
            f"camera ON — Labhair-liom {self.ascii_w}x{self.ascii_h} "
            f"@ {self.ascii_fps} fps ({note})"
        )
        if self.loop:
            asyncio.run_coroutine_threadsafe(
                self._send_media_presence(self.user_id, "camera", True), self.loop
            )

    def stop_video(self) -> None:
        if not self.video:
            return
        self.video.stop_camera()
        self.ui_sys("camera OFF")
        if not self.video.screen_active:
            self.video = None
        if self.loop:
            asyncio.run_coroutine_threadsafe(
                self._send_media_presence(self.user_id, "camera", False), self.loop
            )

    def open_web_viewer(self) -> int | None:
        """Open the video viewer in a separate movable/resizable window.

        Flet 0.25 has no secondary native-window support, so this uses the
        lightweight HTTP canvas viewer opened in the default browser (a real
        separate window: movable, resizable, closable via the tab's X).
        Re-opens the browser tab if the server is already running.
        """
        from client.web_viewer import open_viewer_window

        try:
            port = open_viewer_window()
        except Exception as exc:
            self.ui_status(f"viewer failed: {exc}")
            return None
        self.ui_sys(f"canvas viewer open at http://127.0.0.1:{port}")
        return port

    def toggle_floating_viewer(self) -> bool | None:
        """Toggle the floating desktop viewer (movable outside the app).

        Returns True when the floating window is now open, False when hidden.
        """
        try:
            from client.floating_viewer import toggle

            opened = toggle()
        except Exception as exc:
            self.ui_status(f"floating viewer failed: {exc}")
            return None
        if opened:
            self.ui_sys("floating viewer open — drag it anywhere on screen")
        else:
            self.ui_sys("floating viewer hidden")
        return opened

    def set_screen_resolution(self, width: int, height: int) -> None:
        """Set the screen-share capture resolution (applies now if sharing)."""
        eng = self.video or self._ensure_video_engine()
        try:
            eng.set_screen_resolution(width, height)
        except (ValueError, AttributeError) as exc:
            self.ui_status(str(exc))
            return
        label = f"{width}x{height}"
        if eng.screen_active:
            self.stop_screen()
            self.start_screen()
            self.ui_sys(f"screen resumed at {label}")
        else:
            self.ui_sys(f"screen resolution set to {label} (next screen share)")

    def start_screen(self) -> None:
        eng = self._ensure_video_engine()
        if eng.screen_active:
            return
        try:
            eng.monitor = self.monitor
            eng.start_screen()
        except Exception as exc:
            self.ui_status(f"screen share failed: {exc}")
            if not eng.camera_active:
                self.video = None
            return
        region = eng.region
        if region:
            where = f"region {region.left},{region.top} {region.width}x{region.height}"
        else:
            where = f"monitor {eng.monitor}"
        backend = eng.screen_backend_name or "?"
        fps = eng._screen.fps if eng._screen else eng.screen_fps
        cw = getattr(eng, "capture_width", eng.screen_width)
        ch = getattr(eng, "capture_height", eng.screen_height)
        self.ui_sys(
            f"screen ON — Labhair-liom {cw}x{ch} "
            f"@ {fps} fps ({where}, backend={backend})"
        )
        self.screen_active_peers[self.user_id] = True
        if self.on_streaming_update:
            try:
                self.on_streaming_update()
            except Exception:
                pass
        if self.loop:
            asyncio.run_coroutine_threadsafe(
                self._send_media_presence(self.user_id, "screen", True), self.loop
            )

    def stop_screen(self) -> None:
        if not self.video:
            return
        self.video.stop_screen()
        self._frame_lines = 0
        self.ui_sys("screen OFF")
        self.screen_active_peers.pop(self.user_id, None)
        if self.on_streaming_update:
            try:
                self.on_streaming_update()
            except Exception:
                pass
        if not self.video.camera_active:
            self.video = None
        if self.loop:
            asyncio.run_coroutine_threadsafe(
                self._send_media_presence(self.user_id, "screen", False), self.loop
            )

    # --- receive path --------------------------------------------------------

    async def recv_loop(self) -> None:
        assert self.reader is not None
        fr = FrameReader()
        try:
            while not self._stop.is_set():
                data = await self.reader.read(65536)
                if not data:
                    self.ui_status("server closed connection")
                    break
                try:
                    packets = fr.feed(data)
                except ValueError as exc:
                    self.ui_status(f"protocol error: {exc}")
                    break
                for pkt in packets:
                    try:
                        await self._on_packet(pkt)
                    except Exception as exc:
                        self.ui_status(f"packet handler error: {exc}")
        except Exception as exc:
            self.ui_status(f"recv error: {exc}")
        finally:
            self._stop.set()

    async def _on_packet(self, pkt: Packet) -> None:
        if pkt.type == MsgType.WELCOME:
            body = unpack_json(pkt.payload)
            for p in body.get("peers", []):
                await self._register_peer(p)
            self.ui_sys(f"room peers: {len(body.get('peers', []))}")
            return
        if pkt.type == MsgType.PEER_JOIN:
            body = unpack_json(pkt.payload)
            if body.get("user_id") == self.user_id:
                return
            await self._register_peer(body)
            return
        if pkt.type == MsgType.PEER_LEAVE:
            body = unpack_json(pkt.payload)
            uid = body.get("user_id", "")
            self.sessions.pop(uid, None)
            self.peer_identity.pop(uid, None)
            self.voice_active_peers.pop(uid, None)
            self.screen_active_peers.pop(uid, None)
            self.camera_active_peers.pop(uid, None)
            name = self.peer_display.pop(uid, uid)
            self.ui_sys(f"{name} left")
            if self.on_streaming_update:
                try:
                    self.on_streaming_update()
                except Exception:
                    pass
            return
        if pkt.type == MsgType.KEY_EXCHANGE:
            body = unpack_json(pkt.payload)
            src = body.get("from", "")
            if src == self.user_id:
                return
            if body.get("to") not in (None, "", self.user_id):
                return
            try:
                ident = b64d(body["identity_pub"])
                eph = b64d(body["ephemeral_pub"])
            except Exception:
                return
            self.peer_identity[src] = ident
            await self._complete_session(src, eph)
            return
        if pkt.type in (MsgType.CHAT, MsgType.VOICE, MsgType.VIDEO, MsgType.IMAGE, MsgType.FILE, MsgType.CONTROL):
            await self._on_encrypted(pkt)
            return

        # --- Management responses (plaintext, server → client) ---

        if pkt.type in (MsgType.AUTH_SUCCESS, MsgType.AUTH_ERROR):
            body = unpack_json(pkt.payload)
            if pkt.type == MsgType.AUTH_SUCCESS:
                self.authenticated = True
                self.auth_token = body.get("token", "")
                self.db_user_id = body.get("user_id", 0)
                self.ui_sys(f"authenticated as {body.get('username', '?')} (id={self.db_user_id})")
                if self.on_auth_success:
                    self.on_auth_success(body)
            else:
                self.ui_status(f"auth failed: {body.get('error', 'unknown')}")
                if self.on_auth_error:
                    self.on_auth_error(body)
            return

        if pkt.type == MsgType.SERVER_NOTICE:
            body = unpack_json(pkt.payload)
            self.ui_sys(body.get("message", "Server notice"))
            return

        if pkt.type == MsgType.MSG_PIN:
            body = unpack_json(pkt.payload)
            if body.get("success"):
                username = body.get("username", "?")
                msg_id = body.get("message_id", "?")
                self.ui_sys(f"message #{msg_id} pinned by {username}")
            else:
                self.ui_status(f"pin error: {body.get('error', 'unknown')}")
            return

        if pkt.type == MsgType.MSG_UNPIN:
            body = unpack_json(pkt.payload)
            if body.get("success"):
                username = body.get("username", "?")
                msg_id = body.get("message_id", "?")
                self.ui_sys(f"message #{msg_id} unpinned by {username}")
            else:
                self.ui_status(f"unpin error: {body.get('error', 'unknown')}")
            return

        if pkt.type == MsgType.MSG_PINNED_LIST:
            body = unpack_json(pkt.payload)
            if body.get("success"):
                messages = body.get("messages", [])
                if messages:
                    self.ui_sys(f"pinned messages ({len(messages)}):")
                    for msg in messages:
                        name = msg.get("display_name", f"user:{msg.get('pinned_by', '?')}")
                        content = msg.get("content", "")
                        self.ui_sys(f"  #{msg.get('id')} by {name}: {content}")
                else:
                    self.ui_sys("no pinned messages")
            else:
                self.ui_status(f"pins error: {body.get('error', 'unknown')}")
            return

        if pkt.type == MsgType.ROLE_CREATE:
            body = unpack_json(pkt.payload)
            if body.get("success"):
                name = body.get('name', '?')
                role_id = body.get('role_id', '?')
                self.ui_sys(f"role created: {name} (id={role_id})")
            else:
                self.ui_status(f"role error: {body.get('error', 'unknown')}")
            return

        if pkt.type == MsgType.ROLE_LIST:
            body = unpack_json(pkt.payload)
            roles = body.get("roles", [])
            self.ui_sys(f"{len(roles)} role(s)")
            return

        if pkt.type == MsgType.ROLE_UPDATE:
            body = unpack_json(pkt.payload)
            if body.get("success"):
                self.ui_sys("role updated")
            else:
                self.ui_status(f"role error: {body.get('error', 'unknown')}")
            return

        if pkt.type == MsgType.ROLE_DELETE:
            body = unpack_json(pkt.payload)
            if body.get("success"):
                self.ui_sys("role deleted")
            else:
                self.ui_status(f"role error: {body.get('error', 'unknown')}")
            return

        if pkt.type == MsgType.CHANNEL_UPDATE:
            body = unpack_json(pkt.payload)
            if body.get("success"):
                self.ui_sys("channel updated")
            else:
                self.ui_status(f"channel error: {body.get('error', 'unknown')}")
            return

        if pkt.type == MsgType.TYPING_START:
            body = unpack_json(pkt.payload)
            username = body.get("username", "someone")
            self.ui_typing(username)
            return

        if pkt.type == MsgType.LOGOUT:
            self.authenticated = False
            self.auth_token = ""
            self.db_user_id = 0
            self.ui_sys("logged out")
            return

        if pkt.type == MsgType.SERVER_LIST:
            body = unpack_json(pkt.payload)
            self.servers = body.get("servers", [])
            self.ui_sys(f"server list: {len(self.servers)} servers")
            if self.on_servers_updated:
                self.on_servers_updated()
            return

        if pkt.type in (MsgType.SERVER_CREATE, MsgType.SERVER_JOIN, MsgType.SERVER_LEAVE,
                        MsgType.SERVER_INFO, MsgType.SERVER_UPDATE, MsgType.SERVER_DELETE):
            body = unpack_json(pkt.payload)
            if body.get("success", False):
                if pkt.type == MsgType.SERVER_CREATE:
                    srv = body.get("server", {})
                    self.ui_sys(f"created server: {srv.get('name', '?')} (id={srv.get('id', '?')})")
                    # Refresh list — creator is already a member via db.create_server
                    await self.send_server_list()
                    sid = srv.get("id") or body.get("server_id")
                    if sid:
                        await self.send_channel_list(sid)
                        await self.send_member_list(sid)
                elif pkt.type == MsgType.SERVER_JOIN:
                    self.ui_sys(f"joined server (id={body.get('server_id', '?')})")
                    await self.send_server_list()
                    # Fetch channels and members for this server
                    sid = body.get("server_id") or self.current_server_id
                    if sid:
                        await self.send_channel_list(sid)
                        await self.send_member_list(sid)
                elif pkt.type == MsgType.SERVER_LEAVE:
                    self.ui_sys(f"left server (id={body.get('server_id', '?')})")
                    if self.current_server_id == body.get("server_id"):
                        self.current_server_id = 0
                        self.current_channel_id = 0
                        self.channels = []
                    await self.send_server_list()
                elif pkt.type == MsgType.SERVER_DELETE:
                    self.ui_sys(f"deleted server (id={body.get('server_id', '?')})")
                    await self.send_server_list()
                elif pkt.type in (MsgType.SERVER_INFO, MsgType.SERVER_UPDATE):
                    await self.send_server_list()
            else:
                self.ui_status(f"server error: {body.get('error', 'unknown')}")
            return

        if pkt.type in (MsgType.INVITE_CREATE, MsgType.INVITE_JOIN, MsgType.INVITE_LIST, MsgType.INVITE_DELETE):
            body = unpack_json(pkt.payload)
            if pkt.type == MsgType.INVITE_CREATE:
                if body.get("code"):
                    self.ui_sys(f"invite created: {body['code']}")
                    # Refresh invite list
                    if self.current_server_id:
                        await self.send_invite_list(self.current_server_id)
                else:
                    self.ui_status(f"invite error: {body.get('error', 'unknown')}")
            elif pkt.type == MsgType.INVITE_JOIN:
                if body.get("success"):
                    self.ui_sys(f"joined server via invite (id={body.get('server_id', '?')})")
                    await self.send_server_list()
                    sid = body.get("server_id")
                    if sid:
                        await self.send_channel_list(sid)
                else:
                    self.ui_status(f"invite error: {body.get('error', 'unknown')}")
            elif pkt.type == MsgType.INVITE_LIST:
                if body.get("success"):
                    self._last_invites = body.get("invites", [])
                else:
                    self._last_invites = []
                    self.ui_status(f"invite error: {body.get('error', 'unknown')}")
            elif pkt.type == MsgType.INVITE_DELETE:
                if body.get("success"):
                    self.ui_sys("invite deleted")
                    # Refresh invite list
                    if self.current_server_id:
                        await self.send_invite_list(self.current_server_id)
                else:
                    self.ui_status(f"invite error: {body.get('error', 'unknown')}")
            return

        if pkt.type in (MsgType.PROFILE_GET, MsgType.PROFILE_UPDATE):
            body = unpack_json(pkt.payload)
            if pkt.type == MsgType.PROFILE_GET:
                if body.get("success"):
                    profile = body.get("profile", {})
                    name = profile.get("username", "?")
                    bio = profile.get("bio", "")
                    status = profile.get("custom_status", "")
                    avatar = profile.get("avatar_url", "")
                    # Store on client for GUI access
                    self._bio = bio
                    self._custom_status = status
                    self._avatar_url = avatar
                    self.ui_sys(f"profile for {name}:")
                    if status:
                        self.ui_sys(f"  status: {status}")
                    if bio:
                        self.ui_sys(f"  bio: {bio}")
                    if avatar:
                        self.ui_sys(f"  avatar: {avatar}")
                else:
                    self.ui_status(f"profile error: {body.get('error', 'unknown')}")
            elif pkt.type == MsgType.PROFILE_UPDATE:
                if body.get("success"):
                    self.ui_sys("profile updated")
                    # Refresh profile to get updated data
                    await self.send_profile_get(self.db_user_id)
                else:
                    self.ui_status(f"profile error: {body.get('error', 'unknown')}")
            return

        if pkt.type == MsgType.AVATAR_GET:
            body = unpack_json(pkt.payload)
            if body.get("success"):
                data = b64d(body["avatar"])
                mime = body.get("mime", "image/png")
                ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif"}.get(mime, ".png")
                import tempfile
                path = os.path.join(tempfile.gettempdir(), f"avatar_{body.get('user_id', 0)}{ext}")
                with open(path, "wb") as f:
                    f.write(data)
                self.ui_sys(f"avatar saved to {path}")
            else:
                self.ui_status(f"avatar: {body.get('error', 'not found')}")
            return

        if pkt.type in (MsgType.CHANNEL_CREATE, MsgType.CHANNEL_DELETE, MsgType.CHANNEL_JOIN):
            body = unpack_json(pkt.payload)
            if body.get("success", False):
                if pkt.type == MsgType.CHANNEL_CREATE:
                    self.ui_sys(f"created channel: {body.get('name', '?')}")
                    if self.current_server_id:
                        await self.send_channel_list(self.current_server_id)
                elif pkt.type == MsgType.CHANNEL_JOIN:
                    cid = body.get("channel_id")
                    update_only = body.get("update_only", False)
                    voice_members = body.get("voice_members", [])
                    # Store channel encryption key
                    enc_key = body.get("encryption_key")
                    if cid and enc_key:
                        try:
                            self._channel_keys[int(cid)] = self._derive_channel_key(enc_key, int(cid))
                        except Exception:
                            pass
                    if update_only:
                        # Voice channel member list update
                        if self.on_voice_members_update:
                            self.on_voice_members_update(cid, voice_members)
                    else:
                        self.ui_sys(f"joined channel (id={cid})")
                        # Update voice members display (including self)
                        if voice_members and self.on_voice_members_update:
                            self.on_voice_members_update(cid, voice_members)
                        elif voice_members:
                            self.ui_sys(f"voice: {len(voice_members)} users connected")
                        # Load message history for text channels
                        if cid:
                            await self.send_message_history(cid)
                            if self.current_server_id:
                                await self.send_member_list(self.current_server_id)
            else:
                self.ui_status(f"channel error: {body.get('error', 'unknown')}")
            return

        if pkt.type == MsgType.CHANNEL_LIST:
            body = unpack_json(pkt.payload)
            self.channels = body.get("channels", [])
            # Store channel encryption keys
            for ch in self.channels:
                cid = ch.get("id")
                key_b64 = ch.get("encryption_key")
                if cid and key_b64:
                    try:
                        self._channel_keys[int(cid)] = self._derive_channel_key(key_b64, int(cid))
                    except Exception:
                        pass
            self.ui_sys(f"channel list: {len(self.channels)} channels")
            if self.on_channels_updated:
                self.on_channels_updated()
            return

        if pkt.type == MsgType.MESSAGE_SEND:
            body = unpack_json(pkt.payload)
            if body.get("success"):
                msg = body.get("message", {})
                if not msg.get("username"):
                    msg["username"] = body.get("username", f"user:{msg.get('author_id', '?')}")
                content = msg.get("content", "")
                mentioned = False
                if content and msg.get("author_id") != self.db_user_id:
                    mentioned = (f"@{self.display}" in content if self.display else False) or \
                                (f"@{self.user_id}" in content if self.user_id else False)
                msg["mentioned"] = mentioned
                if self.on_message_received:
                    self.on_message_received(msg)
                # If this is our own message echo from the server, display it
                if msg.get("author_id") == self.db_user_id:
                    who = self.display
                else:
                    who = body.get("username", f"user:{msg.get('author_id', '?')}")
                if content:
                    self.ui_chat(who, content, mentioned=mentioned)
            return

        if pkt.type == MsgType.MESSAGE_HISTORY:
            body = unpack_json(pkt.payload)
            messages = body.get("messages", [])
            self.ui_sys(f"loaded {len(messages)} messages")
            if self.on_messages_updated:
                self.on_messages_updated(messages)
            return

        if pkt.type in (MsgType.MESSAGE_EDIT, MsgType.MESSAGE_DELETE):
            body = unpack_json(pkt.payload)
            if body.get("success"):
                self.ui_sys(f"message {'edited' if pkt.type == MsgType.MESSAGE_EDIT else 'deleted'}")
            return

        if pkt.type in (MsgType.MESSAGE_REACTION_ADD, MsgType.MESSAGE_REACTION_REMOVE):
            body = unpack_json(pkt.payload)
            if body.get("success"):
                action = "reacted" if pkt.type == MsgType.MESSAGE_REACTION_ADD else "unreacted"
                emoji = body.get("emoji", "")
                msg_id = body.get("message_id", 0)
                username = body.get("username", "")
                self.ui_sys(f"{username} {action} {emoji} to message #{msg_id}")
                if self.on_reaction_updated:
                    self.on_reaction_updated(body)
            return

        if pkt.type in (MsgType.THREAD_CREATE, MsgType.THREAD_JOIN, MsgType.THREAD_LEAVE,
                        MsgType.THREAD_ARCHIVE):
            body = unpack_json(pkt.payload)
            if body.get("success"):
                thread = body.get("thread", {})
                thread_id = thread.get("id", body.get("thread_id", 0))
                if pkt.type == MsgType.THREAD_CREATE:
                    self.ui_sys(f"thread created: {thread.get('name', '?')} #{thread_id}")
                elif pkt.type == MsgType.THREAD_JOIN:
                    self.ui_sys(f"joined thread #{thread_id}")
                elif pkt.type == MsgType.THREAD_LEAVE:
                    self.ui_sys(f"left thread #{thread_id}")
                elif pkt.type == MsgType.THREAD_ARCHIVE:
                    self.ui_sys(f"archived thread #{thread_id}")
                if self.on_threads_updated:
                    self.on_threads_updated()
            return

        if pkt.type == MsgType.THREAD_LIST:
            body = unpack_json(pkt.payload)
            threads = body.get("threads", [])
            self.ui_sys(f"{len(threads)} thread(s)")
            if self.on_thread_list:
                self.on_thread_list(threads)
            return

        if pkt.type == MsgType.THREAD_INFO:
            body = unpack_json(pkt.payload)
            if body.get("success"):
                thread = body.get("thread", {})
                members = thread.get("members", [])
                self.ui_sys(f"thread #{thread.get('id')}: {thread.get('name')} ({len(members)} members)")
            return

        if pkt.type == MsgType.THREAD_MESSAGE_SEND:
            body = unpack_json(pkt.payload)
            if body.get("success"):
                msg = body.get("message", {})
                username = msg.get("username", f"user:{msg.get('author_id', '?')}")
                content = msg.get("content", "")
                thread_id = msg.get("thread_id", 0)
                if content:
                    self.ui_sys(f"[thread #{thread_id}] <{username}> {content}")
            return

        if pkt.type == MsgType.THREAD_MESSAGE_HISTORY:
            body = unpack_json(pkt.payload)
            messages = body.get("messages", [])
            self.ui_sys(f"loaded {len(messages)} thread messages")
            return

        if pkt.type == MsgType.SEARCH_RESULTS:
            body = unpack_json(pkt.payload)
            if body.get("success"):
                messages = body.get("messages", [])
                query = body.get("query", "")
                self.ui_sys(f"search '{query}': {len(messages)} result(s)")
                if self.on_search_results:
                    self.on_search_results(messages)
            else:
                self.ui_sys(f"search error: {body.get('error', 'unknown')}")
            return

        if pkt.type == MsgType.DM_SEND:
            body = unpack_json(pkt.payload)
            if body.get("success"):
                dm = body.get("dm", {})
                if dm.get("sender_id") == self.db_user_id:
                    dm.setdefault("username", self.display)
                    self.ui_sys(f"DM sent to user {dm.get('recipient_id')}")
                else:
                    # incoming DM — bump unread unless we're viewing that chat
                    try:
                        viewing = int(self.current_dm_user_id)
                    except (TypeError, ValueError):
                        viewing = 0
                    if int(dm.get("sender_id", 0) or 0) != viewing:
                        self.dm_unread_total += 1
                        self._emit_dm_unread()
                if self.on_dm_message:
                    self.on_dm_message(dm)
            else:
                self.ui_status(f"DM not sent: {body.get('error', 'unknown')}")
            return

        if pkt.type == MsgType.DM_HISTORY:
            body = unpack_json(pkt.payload)
            messages = body.get("messages", [])
            self.ui_sys(f"loaded {len(messages)} DMs")
            if self.on_dm_updated:
                self.on_dm_updated(messages)
            return

        if pkt.type == MsgType.DM_LIST:
            body = unpack_json(pkt.payload)
            conversations = body.get("conversations", [])
            self._dm_conversations = conversations
            self.ui_sys(f"DM conversations: {len(conversations)}")
            self.dm_unread_total = sum(
                int(c.get("unread_count", 0) or 0) for c in conversations
            )
            self._emit_dm_unread()
            if self._gui_queue is not None:
                self._gui_queue.put(("_refresh_dm_conversations", (conversations,), {}))
            if self.on_dm_conversations:
                self.on_dm_conversations(conversations)
            return

        if pkt.type == MsgType.DM_READ:
            return

        if pkt.type == MsgType.DM_IGNORE:
            body = unpack_json(pkt.payload)
            other_id = body.get("user_id", 0)
            if self.on_dm_ignore_result:
                self.on_dm_ignore_result(int(other_id), bool(body.get("success")))
            return

        if pkt.type in (MsgType.FRIEND_ADD, MsgType.FRIEND_REMOVE, MsgType.FRIEND_ACCEPT, MsgType.FRIEND_DECLINE):
            body = unpack_json(pkt.payload)
            if body.get("success"):
                action = pkt.type.name.split("_")[1].lower()
                self.ui_sys(f"friend {action}: ok")
            else:
                self.ui_status(f"friend error: {body.get('error', 'unknown')}")
            return

        if pkt.type == MsgType.FRIEND_LIST:
            body = unpack_json(pkt.payload)
            friends = body.get("friends", [])
            self.ui_sys(f"friends: {len(friends)}")
            if self.on_friends_updated:
                self.on_friends_updated(friends)
            return

        if pkt.type == MsgType.FRIEND_REQUESTS:
            body = unpack_json(pkt.payload)
            requests = body.get("requests", [])
            self.friend_request_count = len(requests)
            self._emit_dm_unread()
            self.ui_sys(f"friend requests: {len(requests)}")
            if self.on_friend_requests_updated:
                self.on_friend_requests_updated(requests)
            return

        if pkt.type == MsgType.SETTINGS_GET:
            body = unpack_json(pkt.payload)
            settings = body.get("settings", {})
            if "auto_ignore_dm" in settings:
                self.auto_ignore_dm = bool(settings.get("auto_ignore_dm"))
            self.settings_loaded = True
            if self.on_settings_updated:
                self.on_settings_updated(settings)
            return

        if pkt.type == MsgType.SETTINGS_UPDATE:
            body = unpack_json(pkt.payload)
            settings = body.get("settings", {})
            if "auto_ignore_dm" in settings:
                self.auto_ignore_dm = bool(settings.get("auto_ignore_dm"))
            self.settings_loaded = True
            if self.on_settings_updated:
                self.on_settings_updated(settings)
            if not body.get("success"):
                self.ui_status(f"settings update failed: {body.get('error', 'unknown')}")
            return

        if pkt.type == MsgType.MEMBER_LIST:
            body = unpack_json(pkt.payload)
            self.members = body.get("members", [])
            self.ui_sys(f"members: {len(self.members)}")
            if self.on_members_updated:
                self.on_members_updated()
            return

        if pkt.type in (MsgType.MEMBER_KICK, MsgType.MEMBER_BAN):
            body = unpack_json(pkt.payload)
            if body.get("success"):
                action = "kicked" if pkt.type == MsgType.MEMBER_KICK else "banned"
                self.ui_sys(f"{action} user {body.get('target_id', '?')}")
            else:
                self.ui_status(f"member error: {body.get('error', 'unknown')}")
            return

        if pkt.type == MsgType.STATUS_UPDATE:
            body = unpack_json(pkt.payload)
            self.ui_sys(f"status: {body.get('status', '?')}")
            return

        if pkt.type == MsgType.ERROR:
            body = unpack_json(pkt.payload)
            self.ui_status(f"server error: {body.get('error')}")
            return

    async def _register_peer(self, p: dict) -> None:
        uid = p.get("user_id", "")
        if not uid or uid == self.user_id:
            return
        try:
            ident = b64d(p["identity_pub"])
        except Exception:
            return
        self.peer_identity[uid] = ident
        self.peer_display[uid] = p.get("display", uid)
        self.ui_sys(
            f"peer {self.peer_display[uid]} joined  fp={self._fp(ident)}"
        )
        # Kick off key exchange
        if self.eph_priv is None:
            self.eph_priv, self.eph_pub = new_ephemeral()
        await self._send(
            pack_json(
                MsgType.KEY_EXCHANGE,
                {
                    "from": self.user_id,
                    "to": uid,
                    "identity_pub": b64(self.identity_pub),
                    "ephemeral_pub": b64(self.eph_pub),
                },
            )
        )
        # Notify new peer of our voice status
        if self.voice_is_active:
            await self._send_voice_presence(self.user_id, True)
        # And our current screen/camera presence so the dot shows immediately
        for media_type, active_map in (
            ("screen", self.screen_active_peers),
            ("camera", self.camera_active_peers),
        ):
            if active_map.get(self.user_id):
                await self._send_media_presence(self.user_id, media_type, True)

    async def _on_encrypted(self, pkt: Packet) -> None:
        body = unpack_json(pkt.payload)
        src = body.get("from", "")
        dst = body.get("to", "")
        if dst and dst != self.user_id:
            return
        if src == self.user_id:
            return
        sess = self.sessions.get(src)
        if not sess:
            # maybe we can still establish
            await self._ensure_session(src)
            sess = self.sessions.get(src)
            if not sess:
                return
        try:
            aad = f"{src}|{self.user_id}|{int(pkt.type)}".encode()
            pt = sess.decrypt(b64d(body["ct"]), aad=aad)
        except Exception as exc:
            self.ui_status(f"decrypt fail from {src}: {exc}")
            return

        if pkt.type == MsgType.CHAT:
            try:
                msg = json.loads(pt.decode())
                text = msg.get("text", "")
            except Exception:
                text = pt.decode("utf-8", errors="replace")
            who = self.peer_display.get(src, src)
            self.ui_chat(who, text)
        elif pkt.type == MsgType.VOICE:
            if self.voice:
                self.voice.push_remote_frame(pt, sender=body.get("from", ""))
        elif pkt.type == MsgType.VIDEO:
            source_hint = body.get("source")
            sender = body.get("from", "")
            try:
                try:
                    eng = self._ensure_video_engine()
                    key = eng.push_remote_frame(pt, source_hint=source_hint, sender=sender)
                    msg_sender, src = key
                    # Push JPEG to GUI if active
                    if self._gui_queue is not None and src in ("screen", "camera"):
                        fr = eng.decoder.decode(pt)
                        if fr and fr.img_b64:
                            import base64 as _b64
                            jpg = self._gui_sized_jpeg(_b64.b64decode(fr.img_b64))
                            self._gui_queue.put(("ui_video_jpeg", (jpg, src, sender), {}))
                            self._emit_remote_video_frame(jpg, src, sender)
                    # Show screen frames in terminal only when Canvas viewer has never been active
                    if src == "screen" and self.auto_show_screen:
                        from client.web_viewer import _viewer_ever_active
                        if not _viewer_ever_active:
                            meta = eng._latest_meta.get(key, {})
                            seq = int(meta.get("seq", 0))
                            last = self._last_shown_seq.get(key, -1)
                            if seq - last >= max(1, eng.screen_fps):
                                self._last_shown_seq[key] = seq
                                view = eng.get_remote_view("screen", sender=msg_sender)
                                if view:
                                    who = self.peer_display.get(sender, sender)
                                    self.ui_video_frame(view, label=f"Labhair-liom screen from {who}")
                except Exception:
                    # Android / headless: VideoEngine unavailable — decode Labhair-liom directly
                    from shared.labhair_liom import LabhairLiomDecoder
                    decoder = LabhairLiomDecoder()
                    fr = decoder.decode(pt)
                    src = source_hint or (fr.source if fr else None) or "screen"
                    if fr and fr.img_b64 and self._gui_queue is not None:
                        import base64 as _b64
                        jpg = self._gui_sized_jpeg(_b64.b64decode(fr.img_b64))
                        self._gui_queue.put(("ui_video_jpeg", (jpg, src, sender), {}))
                        self._emit_remote_video_frame(jpg, src, sender)
            except Exception as exc:
                self.ui_status(f"video decode fail: {exc}")
        elif pkt.type == MsgType.IMAGE:
            who = self.peer_display.get(src, src)
            try:
                meta, webp_bytes, preview = unpack_image_payload(pt)
                self._received_images[meta.id] = (meta, webp_bytes, preview)
                self.ui(format_image_info(meta, who))
                if self._gui_queue is not None:
                    self.ui_image(meta.id, webp_bytes, who, meta.name, meta.width, meta.height)
                elif preview:
                    self.ui(format_image_preview(meta, preview, who))
            except Exception as exc:
                self.ui_status(f"image decode fail: {exc}")
        elif pkt.type == MsgType.FILE:
            who = self.peer_display.get(src, src)
            try:
                meta, file_bytes = unpack_file_payload(pt)
                self._received_files[meta.id] = (meta, file_bytes)
                self.ui(format_file_info(meta, who))
                if self._gui_queue is not None:
                    self.ui_file(meta.id, file_bytes, who, meta.name, meta.mime_type, meta.size)
            except Exception as exc:
                self.ui_status(f"file decode fail: {exc}")
        elif pkt.type == MsgType.CONTROL:
            await self._on_control_decrypted(pt, src)

    async def _on_control_decrypted(self, pt: bytes, src: str):
        try:
            msg = json.loads(pt.decode())
        except Exception:
            return
        if "voice_active" in msg:
            self.voice_active_peers[src] = msg["voice_active"]
            who = self.peer_display.get(src, src)
            status = "joined voice" if msg["voice_active"] else "left voice"
            self.ui_sys(f"{who} {status}")
        elif "speaking_user" in msg:
            speaker = msg["speaking_user"]
            speaking = msg.get("speaking", False)
            self._speaking_users[speaker] = speaking
            if self.on_speaking_update:
                try:
                    self.on_speaking_update(speaker, speaking)
                except Exception:
                    pass
        elif "media_type" in msg:
            who = self.peer_display.get(src, src)
            media = msg["media_type"]
            active = msg.get("media_active", False)
            if media == "screen":
                self.screen_active_peers[src] = active
            elif media == "camera":
                self.camera_active_peers[src] = active
            else:
                return
            if self.on_streaming_update:
                try:
                    self.on_streaming_update()
                except Exception:
                    pass
            if active:
                self.ui_sys(f"{who} sharing {media}")
            else:
                self.ui_sys(f"{who} stopped sharing {media}")

    # --- stdin commands ------------------------------------------------------

    async def input_loop(self) -> None:
        if self._gui_mode:
            return  # GUI handles input directly
        # Run blocking stdin in a thread
        while not self._stop.is_set():
            line = await asyncio.to_thread(sys.stdin.readline)
            if line == "":
                self._stop.set()
                break
            line = line.rstrip("\n")
            if not line:
                continue
            if line.startswith("/"):
                await self._command(line)
            else:
                await self.send_chat(line)

    async def _command(self, line: str) -> None:
        parts = line.split()
        cmd = parts[0].lower()
        arg = parts[1].lower() if len(parts) > 1 else ""

        if cmd in ("/quit", "/exit", "/q"):
            self._stop.set()
            return
        if cmd == "/help":
            self.ui_sys("available commands:")
            self.ui_sys("  /voice on|off|listen        — toggle voice chat")
            self.ui_sys("  /video on|off               — toggle camera")
            self.ui_sys("  /screen on|off [mode] [px]  — toggle screen share")
            self.ui_sys("  /screen show on|off         — toggle remote screen in terminal")
            self.ui_sys("  /show [camera|screen]       — show latest remote frame")
            self.ui_sys("  /monitor N                 — set screen capture monitor")
            self.ui_sys("  /monitors                  — list available monitors")
            self.ui_sys("  /region L T W H | clear     — set screen capture region")
            self.ui_sys("  /peers                     — list connected peers")
            self.ui_sys("  /devices                   — list audio devices")
            self.ui_sys("  /admin-auth [display]      — request admin auth from relay operator")
            self.ui_sys("  /server join|leave <id>    — join or leave a server")
            self.ui_sys("  /invite create|join|list|delete — manage server invites")
            self.ui_sys("  /profile view|set          — view or update user profile")
            self.ui_sys("  /pin list|pin|unpin        — manage pinned messages")
            self.ui_sys("  /mic N                     — set mic input device")
            self.ui_sys("  /speaker N                 — set speaker output device")
            self.ui_sys("  /viewer [off]              — toggle browser canvas viewer")
            self.ui_sys("  /sendimage <path>          — send an image")
            self.ui_sys("  /sendfile <path>           — send a file")
            self.ui_sys("  /images                    — list received images")
            self.ui_sys("  /files                     — list received files")
            self.ui_sys("  /download <id>             — re-save a received image")
            self.ui_sys("  /quit                      — disconnect and exit")
            return
        if cmd == "/admin-auth":
            display = parts[1] if len(parts) > 1 else ""
            await self.send_admin_auth_request(display)
            return
        if cmd == "/server":
            if arg == "join" and len(parts) > 2:
                await self.send_server_join(int(parts[2]))
            elif arg == "leave" and len(parts) > 2:
                await self.send_server_leave(int(parts[2]))
            else:
                self.ui_status("usage: /server join <id> | /server leave <id>")
            return
        if cmd == "/invite":
            subcmd = arg
            if subcmd == "create" and len(parts) > 2:
                server_id = int(parts[2]) if parts[2].isdigit() else self.current_server_id
                max_uses = int(parts[3]) if len(parts) > 3 else 0
                if not server_id:
                    self.ui_status("usage: /invite create [server_id] [max_uses]")
                    return
                await self.send_invite_create(server_id, max_uses=max_uses)
            elif subcmd == "join" and len(parts) > 2:
                await self.send_invite_join(parts[2])
            elif subcmd == "list":
                server_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else self.current_server_id
                if not server_id:
                    self.ui_status("usage: /invite list [server_id]")
                    return
                await self.send_invite_list(server_id)
            elif subcmd == "delete" and len(parts) > 2:
                server_id = int(parts[3]) if len(parts) > 3 else self.current_server_id
                if not server_id:
                    self.ui_status("usage: /invite delete <invite_id> [server_id]")
                    return
                await self.send_invite_delete(int(parts[2]), server_id)
            else:
                self.ui_status("usage: /invite create [server_id] [max_uses] | /invite join <code> | /invite list [server_id] | /invite delete <id> [server_id]")
            return
        if cmd == "/profile":
            subcmd = arg
            if subcmd == "set" and len(parts) > 2:
                field = parts[2].lower()
                value = " ".join(parts[3:])
                if field == "bio":
                    await self.send_profile_update(bio=value)
                elif field == "status":
                    await self.send_profile_update(custom_status=value)
                elif field == "avatar":
                    await self.send_profile_update(avatar_path=value)
                elif field == "avatar_url":
                    await self.send_profile_update(avatar_url=value)
                else:
                    self.ui_status("usage: /profile set bio|status|avatar|avatar_url <value>")
            elif subcmd == "view":
                uid = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
                await self.send_profile_get(uid)
            elif subcmd == "avatar":
                uid = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
                await self.send_avatar_get(uid)
            else:
                self.ui_status("usage: /profile view [user_id] | /profile set bio|status|avatar <value> | /profile avatar [user_id]")
            return
        if cmd == "/pin":
            if arg == "list":
                await self.send_pinned_list(self.current_channel_id)
            elif arg == "pin":
                mid = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
                if not mid:
                    self.ui_status("usage: /pin pin <message_id>")
                else:
                    await self.send_msg_pin(mid)
            elif arg == "unpin":
                mid = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
                if not mid:
                    self.ui_status("usage: /pin unpin <message_id>")
                else:
                    await self.send_msg_unpin(mid)
            else:
                self.ui_status("usage: /pin list | /pin pin <message_id> | /pin unpin <message_id>")
            return
        if cmd == "/voice":
            if arg in ("on", "1", "start"):
                self.start_voice()
            elif arg in ("off", "0", "stop"):
                self.stop_voice()
            elif arg in ("listen", "rx", "only"):
                self.start_voice(listen_only=True)
            else:
                self.ui_status("usage: /voice on|off|listen")
            return
        if cmd == "/video":
            if arg in ("on", "1", "start", "camera"):
                self.start_video()
            elif arg in ("off", "0", "stop"):
                self.stop_video()
            else:
                self.ui_status("usage: /video on|off  (camera track)")
            return
        if cmd in ("/screen", "/screenshare", "/share"):
            if arg in ("on", "1", "start"):
                # Parse additional arguments: /screen on [mode] [pixel]
                mode = int(parts[2]) if len(parts) > 2 else 5
                pixel = parts[3].lower() not in ("off", "false", "0") if len(parts) > 3 else (mode == 5)

                # 1. Store them in the correct variables
                self.mode = mode
                self.pixel = pixel

                # 2. If the video engine is already running, update it instantly
                if self.video:
                    self.video.mode = self.mode
                    self.video.pixel = self.pixel

                self.start_screen()
            elif arg in ("off", "0", "stop"):
                self.stop_screen()
            elif parts[1].lower() == "show" if len(parts) > 1 else False:
                sub = parts[2].lower() if len(parts) > 2 else ""
                if sub in ("on", "1", "true"):
                    self.auto_show_screen = True
                    self.ui_status("terminal screen display ON")
                elif sub in ("off", "0", "false"):
                    self.auto_show_screen = False
                    self.ui_status("terminal screen display OFF")
                else:
                    self.ui_status(f"terminal screen display: {'ON' if self.auto_show_screen else 'OFF'}")
            else:
                self.ui_status("usage: /screen on|off [mode] [pixel]  |  /screen show on|off")
            return
        if cmd in ("/video-show", "/show"):
            which = arg if arg in ("camera", "screen", "video") else (
                parts[1].lower() if len(parts) > 1 else "screen"
            )
            if which not in ("camera", "screen", "video"):
                which = "screen"
            eng = self._ensure_video_engine()
            view = eng.get_remote_view(which)
            if view:
                self.ui_video_frame(view, label=f"Labhair-liom {which}")
            else:
                avail = eng.remote_sources()
                self.ui_status(
                    f"no remote {which} frame yet"
                    + (f" (have: {', '.join(avail)})" if avail else "")
                )
            return
        if cmd == "/monitor":
            if len(parts) < 2:
                self.ui_status("usage: /monitor <index>  (see /monitors)")
                return
            try:
                idx = int(parts[1])
            except ValueError:
                self.ui_status("monitor index must be int")
                return
            self.monitor = idx
            eng = self._ensure_video_engine()
            eng.set_monitor(idx)
            self.ui_sys(f"screen capture monitor → {idx}")
            return
        if cmd == "/region":
            if len(parts) == 2 and parts[1].lower() in ("clear", "off", "full"):
                eng = self._ensure_video_engine()
                eng.clear_region()
                self.ui_sys("screen region cleared (full monitor)")
                return
            if len(parts) < 5:
                self.ui_status("usage: /region <left> <top> <width> <height>  |  /region clear")
                return
            try:
                left, top, width, height = map(int, parts[1:5])
            except ValueError:
                self.ui_status("region values must be integers")
                return
            eng = self._ensure_video_engine()
            try:
                eng.set_region(left, top, width, height)
            except ValueError as exc:
                self.ui_status(str(exc))
                return
            self.ui_sys(f"screen region → {left},{top} {width}x{height}")
            return
        if cmd == "/monitors":
            from client.video_io import list_monitors, backend_status
            try:
                mons = list_monitors()
            except Exception as exc:
                self.ui_status(f"cannot list monitors: {exc}")
                return
            for m in mons:
                prim = " (primary)" if m.get("primary") else ""
                self.ui(
                    f"  [{m['index']}] {m.get('label', '?')}  "
                    f"{m['width']}x{m['height']} @ {m['left']},{m['top']}{prim}"
                )
            self.ui_sys(backend_status())
            return
        if cmd == "/peers":
            if not self.peer_identity:
                self.ui_status("no peers")
                return
            for uid, pub in self.peer_identity.items():
                ok = "E2E" if uid in self.sessions else "no-session"
                voice = " VOICE" if self.voice_active_peers.get(uid) else ""
                self.ui(f"  {self.peer_display.get(uid, uid)}  {ok}{voice}  fp={self._fp(pub)}")
            return
        if cmd == "/devices":
            from client.audio_io import list_devices
            self.ui(list_devices())
            return
        if cmd == "/viewer":
            from client.web_viewer import start_viewer, stop_viewer
            if arg in ("off", "0", "stop"):
                stop_viewer()
                self.ui_sys("canvas viewer stopped")
            else:
                try:
                    port = start_viewer()
                except Exception as exc:
                    self.ui_status(f"viewer failed: {exc}")
                    return
                self.ui_sys(f"canvas viewer open at http://127.0.0.1:{port}")
            return
        if cmd == "/mic":
            if arg in ("list", ""):
                from client.audio_io import list_devices
                self.ui(list_devices())
                return
            try:
                idx = int(arg)
            except ValueError:
                self.ui_status("usage: /mic <device-index>  (see /devices)")
                return
            self._input_device = idx
            self.settings.input_device = idx
            self.settings.save()
            was_running = self.voice is not None
            if was_running:
                self.stop_voice()
            if was_running:
                self.start_voice()
            else:
                self.ui_sys(f"mic input set to device {idx}")
            return
        if cmd in ("/speaker", "/spk"):
            if arg in ("list", ""):
                from client.audio_io import list_devices
                self.ui(list_devices())
                return
            try:
                idx = int(arg)
            except ValueError:
                self.ui_status("usage: /speaker <device-index>  (see /devices)")
                return
            self._output_device = idx
            self.settings.output_device = idx
            self.settings.save()
            was_running = self.voice is not None
            if was_running:
                self.stop_voice()
            if was_running:
                self.start_voice()
            else:
                self.ui_sys(f"speaker output set to device {idx}")
            return
        if cmd == "/settings":
            if arg == "test":
                self._play_notification_sound()
                self.ui_sys("notification sound played")
            elif arg in ("on", "1", "enable"):
                self.settings.notification_sound = True
                self.settings.save()
                self.ui_sys("notification sounds ON")
            elif arg in ("off", "0", "disable"):
                self.settings.notification_sound = False
                self.settings.save()
                self.ui_sys("notification sounds OFF")
            elif arg == "volume":
                vol = parts[2] if len(parts) > 2 else ""
                if vol:
                    try:
                        self.settings.notification_volume = float(vol)
                        self.settings.save()
                        self.ui_sys(f"notification volume: {self.settings.notification_volume:.0%}")
                    except ValueError:
                        self.ui_status("usage: /settings volume <0.0-1.0>")
                else:
                    self.ui_sys(f"notification volume: {self.settings.notification_volume:.0%}")
            elif arg == "dm":
                sub = parts[2] if len(parts) > 2 else ""
                if sub in ("on", "1"):
                    self.settings.notification_dm_sound = True
                    self.settings.save()
                    self.ui_sys("DM notification sounds ON")
                elif sub in ("off", "0"):
                    self.settings.notification_dm_sound = False
                    self.settings.save()
                    self.ui_sys("DM notification sounds OFF")
                else:
                    self.ui_sys(f"DM notification: {'ON' if self.settings.notification_dm_sound else 'OFF'}")
            else:
                self.ui_sys(f"notifications: {'ON' if self.settings.notification_sound else 'OFF'}")
                self.ui_sys(f"DM notifications: {'ON' if self.settings.notification_dm_sound else 'OFF'}")
                self.ui_sys(f"notification volume: {self.settings.notification_volume:.0%}")
                self.ui_sys(f"mic device: {self._input_device or 'default'}")
                self.ui_sys(f"speaker device: {self._output_device or 'default'}")
                self.ui_sys("usage: /settings [on|off|test|volume <0-1>|dm on|off]")
            return
        if cmd in ("/sendimage", "/image", "/img"):
            if len(parts) < 2:
                self.ui_status("usage: /sendimage <path>")
                return
            path = " ".join(parts[1:])
            await self.send_image(path)
            return
        if cmd in ("/sendfile", "/file"):
            if len(parts) < 2:
                self.ui_status("usage: /sendfile <path>")
                return
            path = " ".join(parts[1:])
            from shared.privacy import inspect_file
            report = inspect_file(path)
            if report.warning:
                self.ui_warning(report.warning)
                answer = input("Send anyway? Identifying metadata will NOT be stripped [y/N]: ").strip().lower()
                if answer not in ("y", "yes"):
                    self.ui_status("send cancelled")
                    return
                self.ui_warning("IDENTIFYING METADATA NOT STRIPPED — file sent as selected.")
                await self.send_file(path, allow_unsanitized=True)
            else:
                await self.send_file(path)
            return
        if cmd == "/download":
            if len(parts) < 2:
                self.ui_status("usage: /download <id>  (see /images or /files for IDs)")
                return
            dl_id = parts[1]
            if dl_id in self._received_images:
                meta, webp_bytes, preview = self._received_images[dl_id]
                saved = save_received_image(meta, webp_bytes)
                self.ui_sys(f"saved {meta.name} → {saved}")
            elif dl_id in self._received_files:
                meta, file_bytes = self._received_files[dl_id]
                saved = save_received_file(meta, file_bytes)
                self.ui_sys(f"saved {meta.name} → {saved}")
            else:
                self.ui_status(f"unknown id: {dl_id}  (try /images or /files)")
            return
        if cmd == "/images":
            if not self._received_images:
                self.ui_status("no images received yet")
                return
            for img_id, (meta, webp, _) in self._received_images.items():
                size_kb = meta.webp_size / 1024
                self.ui(
                    f"  [{img_id}] {meta.name}  {meta.width}x{meta.height}  "
                    f"WebP {size_kb:.1f} KB"
                )
            self.ui_sys("use /download <id> to save, or /preview <id> to show again")
            return
        if cmd == "/files":
            if not self._received_files:
                self.ui_status("no files received yet")
                return
            for fid, (meta, _) in self._received_files.items():
                size_kb = meta.size / 1024
                self.ui(
                    f"  [{fid}] {meta.name}  {meta.mime_type}  {size_kb:.1f} KB"
                )
            self.ui_sys("use /download <id> to save")
            return
        if cmd == "/preview":
            if len(parts) < 2:
                self.ui_status("usage: /preview <image-id>")
                return
            img_id = parts[1]
            if img_id not in self._received_images:
                self.ui_status(f"unknown image id: {img_id}")
                return
            meta, webp_bytes, preview = self._received_images[img_id]
            if not preview:
                self.ui_status("no preview available for this image")
                return
            self.ui(format_image_preview(meta, preview, "cached"))
            return
        if cmd == "/edit":
            if len(parts) < 3:
                self.ui_status("usage: /edit <message_id> <new content>")
                return
            try:
                msg_id = int(parts[1])
            except ValueError:
                self.ui_status("message_id must be a number")
                return
            content = " ".join(parts[2:])
            await self.send_message_edit(msg_id, content)
            return
        if cmd == "/delete":
            if len(parts) < 2:
                self.ui_status("usage: /delete <message_id>")
                return
            try:
                msg_id = int(parts[1])
            except ValueError:
                self.ui_status("message_id must be a number")
                return
            await self.send_message_delete(msg_id)
            return
        if cmd == "/react":
            if len(parts) < 3:
                self.ui_status("usage: /react <message_id> <emoji>")
                return
            try:
                msg_id = int(parts[1])
            except ValueError:
                self.ui_status("message_id must be a number")
                return
            emoji = parts[2]
            await self.send_reaction_add(msg_id, emoji)
            return
        if cmd == "/unreact":
            if len(parts) < 3:
                self.ui_status("usage: /unreact <message_id> <emoji>")
                return
            try:
                msg_id = int(parts[1])
            except ValueError:
                self.ui_status("message_id must be a number")
                return
            emoji = parts[2]
            await self.send_reaction_remove(msg_id, emoji)
            return
        if cmd == "/search":
            if len(parts) < 2:
                self.ui_status("usage: /search <query> [--channel <id>] [--server <id>]")
                return
            query_parts = parts[1:]
            ch_id = None
            srv_id = None
            i = 0
            while i < len(query_parts):
                if query_parts[i] == "--channel" and i + 1 < len(query_parts):
                    ch_id = int(query_parts[i + 1])
                    i += 2
                elif query_parts[i] == "--server" and i + 1 < len(query_parts):
                    srv_id = int(query_parts[i + 1])
                    i += 2
                else:
                    i += 1
            query = " ".join(p for p in query_parts if not p.startswith("--"))
            if not query:
                self.ui_status("usage: /search <query>")
                return
            await self.send_search_messages(query, server_id=srv_id, channel_id=ch_id)
            return
        if cmd == "/thread":
            if len(parts) < 2:
                self.ui_status("usage: /thread create <name> | /thread list | /thread join <id> | /thread leave <id> | /thread msg <id> <text>")
                return
            subcmd = parts[1].lower()
            if subcmd == "create":
                if len(parts) < 3:
                    self.ui_status("usage: /thread create <name>")
                    return
                name = " ".join(parts[2:])
                ch_id = self.current_channel_id or 0
                await self.send_thread_create(ch_id, name)
            elif subcmd == "list":
                ch_id = self.current_channel_id or 0
                await self.send_thread_list(ch_id)
            elif subcmd == "join":
                if len(parts) < 3:
                    self.ui_status("usage: /thread join <thread_id>")
                    return
                await self.send_thread_join(int(parts[2]))
            elif subcmd == "leave":
                if len(parts) < 3:
                    self.ui_status("usage: /thread leave <thread_id>")
                    return
                await self.send_thread_leave(int(parts[2]))
            elif subcmd in ("msg", "send", "message"):
                if len(parts) < 4:
                    self.ui_status("usage: /thread msg <thread_id> <message>")
                    return
                thread_id = int(parts[2])
                content = " ".join(parts[3:])
                await self.send_thread_message(thread_id, content)
            elif subcmd == "archive":
                if len(parts) < 3:
                    self.ui_status("usage: /thread archive <thread_id>")
                    return
                await self.send_thread_archive(int(parts[2]))
            else:
                self.ui_status("usage: /thread create|list|join|leave|msg|archive")
            return
        self.ui_status(f"unknown command {cmd} — try /help")

    async def run(self) -> None:
        try:
            await self.connect()
        except OSError:
            return
        # Send auth if pending (set by GUI before starting thread)
        auth = getattr(self, '_pending_auth', None)
        if auth:
            mode, username, email, password = auth
            if mode == "register":
                await self.send_register(username, email, password)
            elif mode == "login":
                await self.send_login(username, password)
            self._pending_auth = None
        if self.want_voice:
            self.start_voice()
        if self.want_video:
            self.start_video()
        if self.want_viewer:
            from client.web_viewer import start_viewer
            try:
                port = start_viewer()
                self.ui_sys(f"canvas viewer open at http://127.0.0.1:{port}")
                if self.upnp:
                    from shared.upnp import setup_port_mapping
                    self._upnp_mapping = setup_port_mapping(
                        port, description="Labhair-liom Viewer",
                    )
                    if self._upnp_mapping:
                        ext_ip = self._upnp_mapping.external_ip or "?"
                        self.ui_sys(f"UPnP: viewer reachable at http://{ext_ip}:{port}")
            except Exception as exc:
                self.ui_status(f"viewer failed: {exc}")
        if self.want_screen:
            self.start_screen()
        recv_task = asyncio.create_task(self.recv_loop())
        input_task = asyncio.create_task(self.input_loop())
        await self._stop.wait()
        self.stop_voice()
        self.stop_video()
        self.stop_screen()
        if self._upnp_mapping:
            self._upnp_mapping.cleanup()
            self._upnp_mapping = None
        recv_task.cancel()
        input_task.cancel()
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except Exception:
                pass
        self.ui_sys("bye")


def main() -> None:
    from client.gui_flet import main as flet_main
    flet_main()


if __name__ == "__main__":
    main()
