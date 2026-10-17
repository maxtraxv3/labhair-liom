#!/usr/bin/env python3
"""Labhair-liom Chat relay server with Discord-like features.

Routes packets between peers, manages authentication, servers, channels,
and persistent messages. E2E encrypted payloads remain opaque to the server.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import logging
import os
import queue
import ssl
import sys
import threading
from pathlib import Path
from typing import Callable

# Allow running as script without install
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.crypto import b64, b64d  # noqa: E402
from shared.protocol import FrameReader, MsgType, Packet, pack_json, unpack_json  # noqa: E402
from shared.database import Database  # noqa: E402
from shared.encryption import FieldEncryptor  # noqa: E402
from shared.auth import session_manager  # noqa: E402
from server.auth_handler import AuthHandler  # noqa: E402
from server.server_manager import ServerManager  # noqa: E402
from server.channel_manager import ChannelManager  # noqa: E402
from server.role_manager import RoleManager  # noqa: E402
from server.message_manager import MessageManager  # noqa: E402
from server.dm_manager import DMManager  # noqa: E402
from server.friend_manager import FriendManager  # noqa: E402
from server.member_manager import MemberManager  # noqa: E402
from server.thread_manager import ThreadManager  # noqa: E402

log = logging.getLogger("relay")


def _create_server_ssl_context(certfile: str, keyfile: str) -> ssl.SSLContext:
    """Create a server SSL context from cert and key files."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile, keyfile)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def _create_client_ssl_context(no_verify: bool = False) -> ssl.SSLContext:
    """Create a client SSL context. If no_verify, skip certificate verification."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    if no_verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _generate_self_signed_cert(cert_path: str, key_path: str) -> None:
    """Generate a self-signed certificate and key for development use."""
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    import datetime

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "labhairliom-relay"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName([
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        ]), critical=False)
        .sign(key, hashes.SHA256())
    )
    Path(cert_path).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    Path(key_path).write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))


class Peer:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer
        self.user_id: str = ""
        self.db_user_id: int = 0
        self.display: str = ""
        self.identity_pub: bytes = b""
        self.room: str = ""
        self.token: str = ""
        self.current_server_id: int = 0
        self.current_channel_id: int = 0

    async def send(self, packet: Packet) -> None:
        self.writer.write(packet.encode())
        await self.writer.drain()


class Relay:
    def __init__(self, db: Database = None) -> None:
        self.rooms: dict[str, dict[str, Peer]] = {}
        self.lock = asyncio.Lock()
        self.peer_count = 0
        self.room_count = 0
        self.db = db
        self.auth_handler = AuthHandler(db) if db else None
        self.server_manager = ServerManager(db) if db else None
        self.channel_manager = ChannelManager(db) if db else None
        self.role_manager = RoleManager(db) if db else None
        self.message_manager = MessageManager(db) if db else None
        self.dm_manager = DMManager(db) if db else None
        self.friend_manager = FriendManager(db) if db else None
        self.member_manager = MemberManager(db, self.role_manager) if db and self.role_manager else None
        self.thread_manager = ThreadManager(db) if db else None
        self.channel_peers: dict[int, set[str]] = {}  # channel_id → set of peer user_ids
        self.voice_channel_members: dict[int, dict[str, str]] = {}  # channel_id → {user_id: display_name}
        self.admin_auth_enabled: bool = False
        self.require_auth: bool = False
        self.auto_auth: bool = False
        self._max_connections: int = 1000

    async def _check_channel_membership(self, peer: Peer, channel_id: int) -> bool:
        """Check if peer is a member of the server that owns channel_id."""
        if not self.db or not channel_id:
            return False
        channel = await self.db.get_channel(channel_id)
        if not channel:
            return False
        server_id = channel.get("server_id", 0)
        if not server_id:
            return False
        return await self.db.is_member(server_id, peer.db_user_id)

    async def _check_server_membership(self, peer: Peer, server_id: int) -> bool:
        """Check if peer is a member of a server."""
        if not self.db or not server_id:
            return False
        return await self.db.is_member(server_id, peer.db_user_id)

    def list_peers(self) -> list[dict]:
        """Return a snapshot of all connected peers for the admin GUI."""
        result = []
        for room_peers in self.rooms.values():
            for peer in room_peers.values():
                result.append({
                    "user_id": peer.user_id,
                    "db_user_id": peer.db_user_id,
                    "display": peer.display,
                    "room": peer.room,
                    "authenticated": bool(peer.db_user_id),
                })
        return result

    async def kick_peer(self, display: str) -> dict:
        """Disconnect a peer by display name."""
        target = None
        async with self.lock:
            for room_peers in self.rooms.values():
                for peer in room_peers.values():
                    if peer.display == display:
                        target = peer
                        break
                if target:
                    break
        if not target:
            return {"success": False, "error": "Peer not found"}
        try:
            target.writer.close()
            await target.writer.wait_closed()
        except Exception:
            pass
        return {"success": True}

    async def broadcast_all(self, msg_type: MsgType, body: dict) -> None:
        """Send a packet to every connected peer."""
        pkt = pack_json(msg_type, body)
        async with self.lock:
            peers = [p for room in self.rooms.values() for p in room.values()]
        for peer in peers:
            try:
                await peer.send(pkt)
            except Exception:
                pass

    async def _broadcast_server_list(self, peer: Peer) -> None:
        """Send updated server list to a single peer."""
        servers = await self.server_manager.get_user_servers(peer.db_user_id)
        await peer.send(pack_json(MsgType.SERVER_LIST, {'servers': servers}))

    async def _broadcast_member_list_to_server(self, server_id: int) -> None:
        """Send updated member list to all peers in a server."""
        result = await self.member_manager.get_members(server_id)
        pkt = pack_json(MsgType.MEMBER_LIST, result)
        async with self.lock:
            for room_peers in self.rooms.values():
                for peer in room_peers.values():
                    if peer.current_server_id == server_id:
                        try:
                            await peer.send(pkt)
                        except Exception:
                            pass

    async def shutdown_gracefully(self, delay: int = 30) -> None:
        """Warn all peers, wait, then disconnect them all."""
        log.info("relay shutting down in %d seconds", delay)
        await self.broadcast_all(MsgType.SERVER_NOTICE, {
            "message": f"Server shutting down in {delay} seconds.",
        })
        await asyncio.sleep(delay)
        async with self.lock:
            peers = [p for room in self.rooms.values() for p in room.values()]
        for peer in peers:
            try:
                peer.writer.close()
                await peer.writer.wait_closed()
            except Exception:
                pass
        log.info("all peers disconnected")

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        # Connection limit
        if self.peer_count >= self._max_connections:
            log.warning("connection limit reached (%d), rejecting", self.peer_count)
            writer.close()
            return
        self.peer_count += 1
        peer = Peer(reader, writer)
        fr = FrameReader()
        log.info("connect (total: %d)", self.peer_count)

        auth_timeout: asyncio.Task | None = None
        if self.require_auth:
            async def _auth_timeout():
                await asyncio.sleep(30)
                if not peer.db_user_id:
                    log.info("auth timeout, kicking peer")
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception:
                        pass
            auth_timeout = asyncio.ensure_future(_auth_timeout())

        # Rate limiter: max 200 packets/sec per peer, burst of 50
        rate_tokens = 50
        rate_last = asyncio.get_event_loop().time()

        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                for pkt in fr.feed(data):
                    # Rate limiting
                    now = asyncio.get_event_loop().time()
                    elapsed = now - rate_last
                    rate_last = now
                    rate_tokens = min(50, rate_tokens + elapsed * 200)
                    if rate_tokens < 1:
                        log.warning("rate limit exceeded for %s, disconnecting", peer.user_id or peer.display)
                        break
                    rate_tokens -= 1
                    if auth_timeout and not auth_timeout.done() and peer.db_user_id:
                        auth_timeout.cancel()
                    await self._dispatch(peer, pkt)
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        except Exception:
            log.exception("peer error")
        finally:
            self.peer_count = max(0, self.peer_count - 1)
            if auth_timeout and not auth_timeout.done():
                auth_timeout.cancel()
            await self._leave(peer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            log.info("disconnect (%s) (total: %d)", peer.user_id or "?", self.peer_count)

    async def _dispatch(self, peer: Peer, pkt: Packet) -> None:
        t = pkt.type

        # Auth packets don't require prior auth
        if t in (MsgType.HELLO, MsgType.REGISTER, MsgType.LOGIN, MsgType.ADMIN_AUTH_REQUEST):
            handler = {
                MsgType.HELLO: self._hello,
                MsgType.REGISTER: self._handle_register,
                MsgType.LOGIN: self._handle_login,
                MsgType.ADMIN_AUTH_REQUEST: self._handle_admin_auth_request,
            }[t]
            await handler(peer, unpack_json(pkt.payload))
            return

        # Everything else requires authentication
        if not peer.db_user_id:
            if self.auto_auth and self.db:
                import random, string
                from shared.auth import Auth
                display = peer.display or f"peer-{id(peer) % 10000}"
                # Sanitize: strip to alphanumeric + dash/underscore, enforce length
                display = "".join(c for c in display if c.isalnum() or c in "-_")[:32]
                if not display or not display[0].isalpha():
                    display = f"peer-{id(peer) % 10000}"
                peer.display = display
                # Handle duplicate usernames
                base_name = display
                attempt = 0
                while True:
                    try:
                        user_id = await self.db.create_user(
                            display,
                            f"{display}@auto.local",
                            "auto",
                            "".join(random.choices(string.ascii_letters + string.digits, k=16)),
                        )
                        break
                    except Exception:
                        attempt += 1
                        display = f"{base_name}-{attempt}"
                        if attempt > 99:
                            log.warning("auto auth: could not create unique username for %s", base_name)
                            await peer.send(pack_json(MsgType.AUTH_ERROR, {"error": "username conflict"}))
                            return
                peer.db_user_id = user_id
                peer.user_id = str(user_id)
                try:
                    await peer.send(pack_json(MsgType.AUTH_SUCCESS, {
                        'user_id': user_id,
                        'username': display,
                        'admin_auth': True,
                    }))
                except Exception:
                    pass
                log.info("auto auth: user_id=%d display=%s", user_id, display)
            else:
                await peer.send(pack_json(MsgType.AUTH_ERROR, {"error": "Not authenticated"}))
                return

        # Session-destroying
        if t == MsgType.LOGOUT:
            await self._handle_logout(peer)
            return

        # Forward E2E payloads as-is
        if t in (MsgType.KEY_EXCHANGE, MsgType.CHAT, MsgType.VOICE, MsgType.VIDEO,
                 MsgType.IMAGE, MsgType.FILE, MsgType.CONTROL):
            await self._broadcast(peer, pkt)
            return

        # Server management
        if t == MsgType.SERVER_CREATE:
            await self._handle_server_create(peer, unpack_json(pkt.payload))
        elif t == MsgType.SERVER_JOIN:
            await self._handle_server_join(peer, unpack_json(pkt.payload))
        elif t == MsgType.SERVER_LEAVE:
            await self._handle_server_leave(peer, unpack_json(pkt.payload))
        elif t == MsgType.SERVER_LIST:
            await self._handle_server_list(peer)
        elif t == MsgType.SERVER_INFO:
            await self._handle_server_info(peer, unpack_json(pkt.payload))
        elif t == MsgType.SERVER_UPDATE:
            await self._handle_server_update(peer, unpack_json(pkt.payload))
        elif t == MsgType.SERVER_DELETE:
            await self._handle_server_delete(peer, unpack_json(pkt.payload))

        # Invites
        elif t == MsgType.INVITE_CREATE:
            await self._handle_invite_create(peer, unpack_json(pkt.payload))
        elif t == MsgType.INVITE_JOIN:
            await self._handle_invite_join(peer, unpack_json(pkt.payload))
        elif t == MsgType.INVITE_LIST:
            await self._handle_invite_list(peer, unpack_json(pkt.payload))
        elif t == MsgType.INVITE_DELETE:
            await self._handle_invite_delete(peer, unpack_json(pkt.payload))

        # Profiles
        elif t == MsgType.PROFILE_GET:
            await self._handle_profile_get(peer, unpack_json(pkt.payload))
        elif t == MsgType.PROFILE_UPDATE:
            await self._handle_profile_update(peer, unpack_json(pkt.payload))
        elif t == MsgType.AVATAR_GET:
            await self._handle_avatar_get(peer, unpack_json(pkt.payload))

        # Channel management
        elif t == MsgType.CHANNEL_CREATE:
            await self._handle_channel_create(peer, unpack_json(pkt.payload))
        elif t == MsgType.CHANNEL_DELETE:
            await self._handle_channel_delete(peer, unpack_json(pkt.payload))
        elif t == MsgType.CHANNEL_LIST:
            await self._handle_channel_list(peer, unpack_json(pkt.payload))
        elif t == MsgType.CHANNEL_JOIN:
            await self._handle_channel_join(peer, unpack_json(pkt.payload))
        elif t == MsgType.CHANNEL_UPDATE:
            await self._handle_channel_update(peer, unpack_json(pkt.payload))

        # Message management
        elif t == MsgType.MESSAGE_SEND:
            await self._handle_message_send(peer, unpack_json(pkt.payload))
        elif t == MsgType.MESSAGE_HISTORY:
            await self._handle_message_history(peer, unpack_json(pkt.payload))
        elif t == MsgType.MESSAGE_EDIT:
            await self._handle_message_edit(peer, unpack_json(pkt.payload))
        elif t == MsgType.MESSAGE_DELETE:
            await self._handle_message_delete(peer, unpack_json(pkt.payload))
        elif t == MsgType.MESSAGE_REACTION_ADD:
            await self._handle_reaction_add(peer, unpack_json(pkt.payload))
        elif t == MsgType.MESSAGE_REACTION_REMOVE:
            await self._handle_reaction_remove(peer, unpack_json(pkt.payload))

        # Thread management
        elif t == MsgType.THREAD_CREATE:
            await self._handle_thread_create(peer, unpack_json(pkt.payload))
        elif t == MsgType.THREAD_JOIN:
            await self._handle_thread_join(peer, unpack_json(pkt.payload))
        elif t == MsgType.THREAD_LEAVE:
            await self._handle_thread_leave(peer, unpack_json(pkt.payload))
        elif t == MsgType.THREAD_LIST:
            await self._handle_thread_list(peer, unpack_json(pkt.payload))
        elif t == MsgType.THREAD_INFO:
            await self._handle_thread_info(peer, unpack_json(pkt.payload))
        elif t == MsgType.THREAD_MESSAGE_SEND:
            await self._handle_thread_message_send(peer, unpack_json(pkt.payload))
        elif t == MsgType.THREAD_MESSAGE_HISTORY:
            await self._handle_thread_message_history(peer, unpack_json(pkt.payload))
        elif t == MsgType.THREAD_ARCHIVE:
            await self._handle_thread_archive(peer, unpack_json(pkt.payload))

        # Search
        elif t == MsgType.SEARCH_MESSAGES:
            await self._handle_search_messages(peer, unpack_json(pkt.payload))

        # Typing indicators
        elif t == MsgType.TYPING_START:
            await self._handle_typing_start(peer, unpack_json(pkt.payload))

        # Message pins
        elif t == MsgType.MSG_PIN:
            await self._handle_msg_pin(peer, unpack_json(pkt.payload))
        elif t == MsgType.MSG_UNPIN:
            await self._handle_msg_unpin(peer, unpack_json(pkt.payload))
        elif t == MsgType.MSG_PINNED_LIST:
            await self._handle_msg_pinned_list(peer, unpack_json(pkt.payload))

        # Role management
        elif t == MsgType.ROLE_CREATE:
            await self._handle_role_create(peer, unpack_json(pkt.payload))
        elif t == MsgType.ROLE_UPDATE:
            await self._handle_role_update(peer, unpack_json(pkt.payload))
        elif t == MsgType.ROLE_DELETE:
            await self._handle_role_delete(peer, unpack_json(pkt.payload))
        elif t == MsgType.ROLE_LIST:
            await self._handle_role_list(peer, unpack_json(pkt.payload))
        elif t == MsgType.MEMBER_ROLE_ADD:
            await self._handle_member_role_add(peer, unpack_json(pkt.payload))
        elif t == MsgType.MEMBER_ROLE_REMOVE:
            await self._handle_member_role_remove(peer, unpack_json(pkt.payload))

        # Member management
        elif t == MsgType.MEMBER_LIST:
            await self._handle_member_list(peer, unpack_json(pkt.payload))
        elif t == MsgType.MEMBER_LEAVE:
            await self._handle_member_leave(peer, unpack_json(pkt.payload))
        elif t == MsgType.MEMBER_KICK:
            await self._handle_member_kick(peer, unpack_json(pkt.payload))
        elif t == MsgType.MEMBER_BAN:
            await self._handle_member_ban(peer, unpack_json(pkt.payload))

        # Direct Messages
        elif t == MsgType.DM_SEND:
            await self._handle_dm_send(peer, unpack_json(pkt.payload))
        elif t == MsgType.DM_HISTORY:
            await self._handle_dm_history(peer, unpack_json(pkt.payload))
        elif t == MsgType.DM_LIST:
            await self._handle_dm_list(peer)
        elif t == MsgType.DM_READ:
            await self._handle_dm_read(peer, unpack_json(pkt.payload))
        elif t == MsgType.DM_IGNORE:
            await self._handle_dm_ignore(peer, unpack_json(pkt.payload))

        # Friends
        elif t == MsgType.FRIEND_ADD:
            await self._handle_friend_add(peer, unpack_json(pkt.payload))
        elif t == MsgType.FRIEND_REMOVE:
            await self._handle_friend_remove(peer, unpack_json(pkt.payload))
        elif t == MsgType.FRIEND_LIST:
            await self._handle_friend_list(peer)
        elif t == MsgType.FRIEND_ACCEPT:
            await self._handle_friend_accept(peer, unpack_json(pkt.payload))
        elif t == MsgType.FRIEND_DECLINE:
            await self._handle_friend_decline(peer, unpack_json(pkt.payload))
        elif t == MsgType.FRIEND_REQUESTS:
            await self._handle_friend_requests(peer)

        # Status
        elif t == MsgType.STATUS_UPDATE:
            await self._handle_status_update(peer, unpack_json(pkt.payload))
        elif t == MsgType.PRESENCE_UPDATE:
            await self._handle_presence_update(peer)
        elif t == MsgType.SETTINGS_GET:
            await self._handle_settings_get(peer)
        elif t == MsgType.SETTINGS_UPDATE:
            await self._handle_settings_update(peer, unpack_json(pkt.payload))

        else:
            await peer.send(pack_json(MsgType.ERROR, {"error": f"unsupported type {t}"}))

    # --- Auth handlers ---

    async def _handle_register(self, peer: Peer, body: dict) -> None:
        if not self.auth_handler:
            await peer.send(pack_json(MsgType.AUTH_ERROR, {"error": "Server not configured"}))
            return
        result = await self.auth_handler.register(
            body.get('username', ''), body.get('email', ''), body.get('password', '')
        )
        if result['success']:
            peer.db_user_id = result['user_id']
            peer.user_id = str(result['user_id'])
            peer.display = result['username']
            peer.token = result['token']
            await peer.send(pack_json(MsgType.AUTH_SUCCESS, result))
        else:
            await peer.send(pack_json(MsgType.AUTH_ERROR, result))

    async def _handle_login(self, peer: Peer, body: dict) -> None:
        if not self.auth_handler:
            await peer.send(pack_json(MsgType.AUTH_ERROR, {"error": "Server not configured"}))
            return
        result = await self.auth_handler.login(body.get('username', ''), body.get('password', ''))
        if result['success']:
            peer.db_user_id = result['user_id']
            peer.user_id = str(result['user_id'])
            peer.display = result.get('display_name') or result['username']
            peer.token = result['token']
            await peer.send(pack_json(MsgType.AUTH_SUCCESS, result))
        else:
            await peer.send(pack_json(MsgType.AUTH_ERROR, result))

    async def _handle_logout(self, peer: Peer) -> None:
        if peer.token and self.auth_handler:
            await self.auth_handler.logout(peer.token)
        peer.token = ""
        peer.db_user_id = 0
        peer.user_id = ""
        await peer.send(pack_json(MsgType.LOGOUT, {}))

    async def _handle_admin_auth_request(self, peer: Peer, body: dict) -> None:
        """Handle a client requesting admin auth. Stores the request for the relay operator."""
        display = body.get('display', '').strip() or f'peer-{id(peer) % 10000}'
        peer.display = display

        if self.auto_auth:
            import random, string
            user_id = await self.db.create_user(
                display,
                f"{display}@auto.local",
                "auto",
                "".join(random.choices(string.ascii_letters + string.digits, k=16)),
            )
            peer.db_user_id = user_id
            peer.user_id = str(user_id)
            await peer.send(pack_json(MsgType.AUTH_SUCCESS, {
                'user_id': user_id,
                'username': display,
                'admin_auth': True,
            }))
            log.info("auto auth: user_id=%d display=%s", user_id, display)
            return

        if not self.admin_auth_enabled:
            await peer.send(pack_json(MsgType.AUTH_ERROR, {
                'error': 'Admin auth not enabled on this relay'
            }))
            return

        await peer.send(pack_json(MsgType.AUTH_SUCCESS, {
            'success': True,
            'waiting_for_admin': True,
            'display': display,
            'message': f'Waiting for relay operator to authenticate you. Ask them to run: auth <your_id> {display}',
        }))
        log.info("admin auth request: display=%s (waiting for operator)", display)

    # --- Server handlers ---

    async def _handle_server_create(self, peer: Peer, body: dict) -> None:
        result = await self.server_manager.create_server(body.get('name', ''), peer.db_user_id)
        await peer.send(pack_json(MsgType.SERVER_CREATE, result))

    async def _handle_server_join(self, peer: Peer, body: dict) -> None:
        server_id = body.get('server_id', 0)
        result = await self.server_manager.join_server(server_id, peer.db_user_id)
        if result.get('success'):
            await self._broadcast_server_list(peer)
            await self._broadcast_member_list_to_server(server_id)
        await peer.send(pack_json(MsgType.SERVER_JOIN, result))

    async def _handle_server_leave(self, peer: Peer, body: dict) -> None:
        result = await self.server_manager.leave_server(body.get('server_id', 0), peer.db_user_id)
        await peer.send(pack_json(MsgType.SERVER_LEAVE, result))

    async def _handle_server_list(self, peer: Peer) -> None:
        servers = await self.server_manager.get_user_servers(peer.db_user_id)
        await peer.send(pack_json(MsgType.SERVER_LIST, {'servers': servers}))

    async def _handle_server_info(self, peer: Peer, body: dict) -> None:
        result = await self.server_manager.get_server_info(body.get('server_id', 0), peer.db_user_id)
        await peer.send(pack_json(MsgType.SERVER_INFO, result))

    async def _handle_server_update(self, peer: Peer, body: dict) -> None:
        result = await self.server_manager.update_server(
            body.get('server_id', 0), peer.db_user_id,
            name=body.get('name'), description=body.get('description'),
            icon_url=body.get('icon_url')
        )
        await peer.send(pack_json(MsgType.SERVER_UPDATE, result))

    async def _handle_server_delete(self, peer: Peer, body: dict) -> None:
        result = await self.server_manager.delete_server(body.get('server_id', 0), peer.db_user_id)
        await peer.send(pack_json(MsgType.SERVER_DELETE, result))

    # --- Invite handlers ---

    async def _handle_invite_create(self, peer: Peer, body: dict) -> None:
        result = await self.server_manager.create_invite(
            body.get('server_id', 0), peer.db_user_id,
            body.get('max_uses', 0), body.get('expires_in_seconds', 0),
        )
        await peer.send(pack_json(MsgType.INVITE_CREATE, result))

    async def _handle_invite_join(self, peer: Peer, body: dict) -> None:
        result = await self.server_manager.join_by_invite(body.get('code', ''), peer.db_user_id)
        if result.get('success'):
            await self._broadcast_server_list(peer)
            server_id = result.get('server_id', 0)
            if server_id:
                await self._broadcast_member_list_to_server(server_id)
        await peer.send(pack_json(MsgType.INVITE_JOIN, result))

    async def _handle_invite_list(self, peer: Peer, body: dict) -> None:
        result = await self.server_manager.list_invites(body.get('server_id', 0), peer.db_user_id)
        await peer.send(pack_json(MsgType.INVITE_LIST, result))

    async def _handle_invite_delete(self, peer: Peer, body: dict) -> None:
        result = await self.server_manager.delete_invite(
            body.get('invite_id', 0), body.get('server_id', 0), peer.db_user_id,
        )
        await peer.send(pack_json(MsgType.INVITE_DELETE, result))

    # --- Profile handlers ---

    async def _handle_profile_get(self, peer: Peer, body: dict) -> None:
        target_id = body.get("user_id", peer.db_user_id)
        profile = await self.db.get_user_profile(target_id)
        username = ""
        user = await self.db.get_user_by_id(target_id)
        if user:
            username = user.get("username", "")
        profile["username"] = username
        await peer.send(pack_json(MsgType.PROFILE_GET, {"success": True, "profile": profile}))

    async def _handle_profile_update(self, peer: Peer, body: dict) -> None:
        avatar_data = None
        avatar_mime = body.get("avatar_mime", "")
        if body.get("avatar"):
            avatar_data = b64d(body["avatar"])
        ok = await self.db.update_user_profile(
            peer.db_user_id,
            bio=body.get("bio"),
            avatar_url=body.get("avatar_url"),
            custom_status=body.get("custom_status"),
            avatar_data=avatar_data,
            avatar_mime=avatar_mime,
        )
        await peer.send(pack_json(MsgType.PROFILE_UPDATE, {"success": ok}))

    async def _handle_avatar_get(self, peer: Peer, body: dict) -> None:
        target_id = body.get("user_id", peer.db_user_id)
        result = await self.db.get_user_avatar(target_id)
        if result:
            data, mime = result
            await peer.send(pack_json(MsgType.AVATAR_GET, {
                "success": True,
                "user_id": target_id,
                "mime": mime,
                "avatar": b64(data),
            }))
        else:
            await peer.send(pack_json(MsgType.AVATAR_GET, {"success": False, "error": "No avatar"}))

    # --- Channel handlers ---

    async def _handle_channel_create(self, peer: Peer, body: dict) -> None:
        result = await self.channel_manager.create_channel(
            body.get('server_id', 0), body.get('name', ''),
            body.get('channel_type', 'text'), peer.db_user_id
        )
        await peer.send(pack_json(MsgType.CHANNEL_CREATE, result))

    async def _handle_channel_delete(self, peer: Peer, body: dict) -> None:
        result = await self.channel_manager.delete_channel(body.get('channel_id', 0), peer.db_user_id)
        await peer.send(pack_json(MsgType.CHANNEL_DELETE, result))

    async def _handle_channel_list(self, peer: Peer, body: dict) -> None:
        server_id = body.get('server_id', 0)
        if not server_id or not await self._check_server_membership(peer, server_id):
            await peer.send(pack_json(MsgType.CHANNEL_LIST, {'channels': [], 'error': 'not a member'}))
            return
        channels = await self.channel_manager.get_server_channels(server_id)
        await peer.send(pack_json(MsgType.CHANNEL_LIST, {'channels': channels}))

    async def _handle_channel_join(self, peer: Peer, body: dict) -> None:
        channel_id = body.get('channel_id', 0)
        # Remove from old channel
        if peer.current_channel_id and peer.current_channel_id in self.channel_peers:
            self.channel_peers[peer.current_channel_id].discard(peer.user_id)
        # If old channel was voice, remove from voice tracking
        if peer.current_channel_id and peer.current_channel_id in self.voice_channel_members:
            self.voice_channel_members[peer.current_channel_id].pop(peer.user_id, None)

        peer.current_channel_id = channel_id
        if channel_id:
            self.channel_peers.setdefault(channel_id, set()).add(peer.user_id)

        channel = await self.channel_manager.get_channel_info(channel_id)
        if channel:
            peer.current_server_id = channel.get('server_id', 0)
            # Track voice channel membership
            if channel.get('channel_type') == 'voice':
                self.voice_channel_members.setdefault(channel_id, {})[peer.user_id] = peer.display
                # Broadcast updated voice member list to all peers in the server
                await self._broadcast_voice_channel_members(channel_id, peer.current_server_id)

        # Get current voice members for this channel
        voice_members = list(self.voice_channel_members.get(channel_id, {}).items()) if channel and channel.get('channel_type') == 'voice' else []

        await peer.send(pack_json(MsgType.CHANNEL_JOIN, {
            'success': True, 'channel_id': channel_id,
            'voice_members': [{'user_id': uid, 'display': name} for uid, name in voice_members],
            'encryption_key': channel.get('encryption_key') if channel else None,
        }))

    # --- Message handlers ---

    async def _handle_message_send(self, peer: Peer, body: dict) -> None:
        channel_id = body.get('channel_id', peer.current_channel_id)
        if not channel_id:
            await peer.send(pack_json(MsgType.MESSAGE_SEND, {'success': False, 'error': 'no channel specified'}))
            return
        if not await self._check_channel_membership(peer, channel_id):
            await peer.send(pack_json(MsgType.MESSAGE_SEND, {'success': False, 'error': 'not a member of this channel'}))
            return
        result = await self.message_manager.send_message(
            channel_id,
            peer.db_user_id,
            body.get('content', ''),
            attachments=body.get('attachments'),
            embeds=body.get('embeds'),
            reply_to_id=body.get('reply_to_id')
        )
        if result.get('success') and result.get('message'):
            result['message']['username'] = peer.display
            # Include sender's role colors
            if peer.current_server_id:
                roles = await self.db.get_user_roles(peer.db_user_id, peer.current_server_id)
                result['message']['roles'] = [{"name": r["name"], "color": r["color"], "permissions": r["permissions"]} for r in roles]
        await peer.send(pack_json(MsgType.MESSAGE_SEND, result))
        # Broadcast to channel peers
        if result.get('success') and result.get('message'):
            await self._broadcast_to_channel(
                body.get('channel_id', peer.current_channel_id),
                pack_json(MsgType.MESSAGE_SEND, result),
                exclude_user=peer.db_user_id
            )

    async def _handle_message_history(self, peer: Peer, body: dict) -> None:
        channel_id = body.get('channel_id', 0)
        if not channel_id or not await self._check_channel_membership(peer, channel_id):
            await peer.send(pack_json(MsgType.MESSAGE_HISTORY, {'success': False, 'error': 'not a member', 'messages': []}))
            return
        result = await self.message_manager.get_message_history(
            channel_id,
            limit=body.get('limit', 50),
            before=body.get('before')
        )
        # Attach role colors to each message
        if result.get('success') and result.get('messages') and peer.current_server_id:
            role_cache = {}
            for msg in result['messages']:
                uid = msg.get('author_id')
                if uid:
                    if uid not in role_cache:
                        roles = await self.db.get_user_roles(uid, peer.current_server_id)
                        role_cache[uid] = [{"name": r["name"], "color": r["color"], "permissions": r["permissions"]} for r in roles]
                    msg['roles'] = role_cache[uid]
        await peer.send(pack_json(MsgType.MESSAGE_HISTORY, result))

    async def _handle_message_edit(self, peer: Peer, body: dict) -> None:
        result = await self.message_manager.edit_message(
            body.get('message_id', 0), peer.db_user_id, body.get('content', '')
        )
        await peer.send(pack_json(MsgType.MESSAGE_EDIT, result))
        if result.get('success'):
            await self._broadcast_to_channel(
                peer.current_channel_id,
                pack_json(MsgType.MESSAGE_EDIT, result),
                exclude_user=peer.db_user_id
            )

    async def _handle_message_delete(self, peer: Peer, body: dict) -> None:
        result = await self.message_manager.delete_message(
            body.get('message_id', 0), peer.db_user_id
        )
        await peer.send(pack_json(MsgType.MESSAGE_DELETE, result))
        if result.get('success'):
            await self._broadcast_to_channel(
                peer.current_channel_id,
                pack_json(MsgType.MESSAGE_DELETE, result),
                exclude_user=peer.db_user_id
            )

    async def _handle_reaction_add(self, peer: Peer, body: dict) -> None:
        result = await self.message_manager.add_reaction(
            body.get('message_id', 0), peer.db_user_id, body.get('emoji', '')
        )
        if result.get('success'):
            result['username'] = peer.display
        await peer.send(pack_json(MsgType.MESSAGE_REACTION_ADD, result))
        if result.get('success'):
            await self._broadcast_to_channel(
                peer.current_channel_id,
                pack_json(MsgType.MESSAGE_REACTION_ADD, result),
                exclude_user=peer.db_user_id
            )

    async def _handle_reaction_remove(self, peer: Peer, body: dict) -> None:
        result = await self.message_manager.remove_reaction(
            body.get('message_id', 0), peer.db_user_id, body.get('emoji', '')
        )
        if result.get('success'):
            result['username'] = peer.display
        await peer.send(pack_json(MsgType.MESSAGE_REACTION_REMOVE, result))
        if result.get('success'):
            await self._broadcast_to_channel(
                peer.current_channel_id,
                pack_json(MsgType.MESSAGE_REACTION_REMOVE, result),
                exclude_user=peer.db_user_id
            )

    # --- Thread handlers ---

    async def _handle_thread_create(self, peer: Peer, body: dict) -> None:
        result = await self.thread_manager.create_thread(
            body.get('channel_id', peer.current_channel_id),
            peer.db_user_id,
            body.get('name', ''),
            body.get('parent_message_id')
        )
        await peer.send(pack_json(MsgType.THREAD_CREATE, result))

    async def _handle_thread_join(self, peer: Peer, body: dict) -> None:
        result = await self.thread_manager.join_thread(
            body.get('thread_id', 0), peer.db_user_id
        )
        await peer.send(pack_json(MsgType.THREAD_JOIN, result))

    async def _handle_thread_leave(self, peer: Peer, body: dict) -> None:
        result = await self.thread_manager.leave_thread(
            body.get('thread_id', 0), peer.db_user_id
        )
        await peer.send(pack_json(MsgType.THREAD_LEAVE, result))

    async def _handle_thread_list(self, peer: Peer, body: dict) -> None:
        result = await self.thread_manager.get_channel_threads(
            body.get('channel_id', peer.current_channel_id)
        )
        await peer.send(pack_json(MsgType.THREAD_LIST, result))

    async def _handle_thread_info(self, peer: Peer, body: dict) -> None:
        result = await self.thread_manager.get_thread_info(body.get('thread_id', 0))
        await peer.send(pack_json(MsgType.THREAD_INFO, result))

    async def _handle_thread_message_send(self, peer: Peer, body: dict) -> None:
        result = await self.thread_manager.send_thread_message(
            body.get('thread_id', 0), peer.db_user_id, body.get('content', '')
        )
        if result.get('success') and result.get('message'):
            result['message']['username'] = peer.display
        await peer.send(pack_json(MsgType.THREAD_MESSAGE_SEND, result))

    async def _handle_thread_message_history(self, peer: Peer, body: dict) -> None:
        result = await self.thread_manager.get_thread_messages(
            body.get('thread_id', 0),
            limit=body.get('limit', 50),
            before=body.get('before')
        )
        await peer.send(pack_json(MsgType.THREAD_MESSAGE_HISTORY, result))

    async def _handle_thread_archive(self, peer: Peer, body: dict) -> None:
        result = await self.thread_manager.archive_thread(
            body.get('thread_id', 0), peer.db_user_id
        )
        await peer.send(pack_json(MsgType.THREAD_ARCHIVE, result))

    # --- Search handlers ---

    async def _handle_search_messages(self, peer: Peer, body: dict) -> None:
        query = body.get('query', '').strip()
        if not query:
            await peer.send(pack_json(MsgType.SEARCH_RESULTS, {'success': False, 'error': 'query required'}))
            return
        messages = await self.db.search_messages(
            query,
            server_id=body.get('server_id'),
            channel_id=body.get('channel_id'),
            limit=body.get('limit', 50)
        )
        await peer.send(pack_json(MsgType.SEARCH_RESULTS, {'success': True, 'messages': messages, 'query': query}))

    # --- Typing indicator ---

    async def _handle_typing_start(self, peer: Peer, body: dict) -> None:
        channel_id = body.get('channel_id', peer.current_channel_id)
        if not channel_id:
            return
        if not await self._check_channel_membership(peer, channel_id):
            return
        payload = pack_json(MsgType.TYPING_START, {
            'user_id': peer.db_user_id,
            'username': peer.display,
            'channel_id': channel_id,
        })
        await self._broadcast_to_channel(channel_id, payload, exclude_user=peer.db_user_id)

    # --- Message pins ---

    async def _handle_msg_pin(self, peer: Peer, body: dict) -> None:
        message_id = body.get('message_id')
        if not message_id:
            await peer.send(pack_json(MsgType.MSG_PIN, {'success': False, 'error': 'message_id required'}))
            return
        # Verify the message exists and peer can pin (must be member)
        msg = await self.db.get_message(message_id)
        if not msg:
            await peer.send(pack_json(MsgType.MSG_PIN, {'success': False, 'error': 'message not found'}))
            return
        channel_id = msg.get('channel_id')
        member = await self.db.get_server_member(msg.get('server_id', 0), peer.db_user_id)
        if not member:
            await peer.send(pack_json(MsgType.MSG_PIN, {'success': False, 'error': 'not a member'}))
            return
        ok = await self.db.pin_message(message_id, peer.db_user_id)
        if ok:
            result = {'success': True, 'message_id': message_id, 'username': peer.display}
            await peer.send(pack_json(MsgType.MSG_PIN, result))
            await self._broadcast_to_channel(channel_id, pack_json(MsgType.MSG_PIN, result), exclude_user=peer.db_user_id)
        else:
            await peer.send(pack_json(MsgType.MSG_PIN, {'success': False, 'error': 'pin failed'}))

    async def _handle_msg_unpin(self, peer: Peer, body: dict) -> None:
        message_id = body.get('message_id')
        if not message_id:
            await peer.send(pack_json(MsgType.MSG_UNPIN, {'success': False, 'error': 'message_id required'}))
            return
        msg = await self.db.get_message(message_id)
        if not msg:
            await peer.send(pack_json(MsgType.MSG_UNPIN, {'success': False, 'error': 'message not found'}))
            return
        channel_id = msg.get('channel_id')
        ok = await self.db.unpin_message(message_id)
        if ok:
            result = {'success': True, 'message_id': message_id, 'username': peer.display}
            await peer.send(pack_json(MsgType.MSG_UNPIN, result))
            await self._broadcast_to_channel(channel_id, pack_json(MsgType.MSG_UNPIN, result), exclude_user=peer.db_user_id)
        else:
            await peer.send(pack_json(MsgType.MSG_UNPIN, {'success': False, 'error': 'not pinned'}))

    async def _handle_msg_pinned_list(self, peer: Peer, body: dict) -> None:
        channel_id = body.get('channel_id', peer.current_channel_id)
        if not channel_id:
            await peer.send(pack_json(MsgType.MSG_PINNED_LIST, {'success': False, 'error': 'channel_id required'}))
            return
        if not await self._check_channel_membership(peer, channel_id):
            await peer.send(pack_json(MsgType.MSG_PINNED_LIST, {'success': True, 'messages': []}))
            return
        messages = await self.db.get_pinned_messages(channel_id)
        await peer.send(pack_json(MsgType.MSG_PINNED_LIST, {'success': True, 'messages': messages, 'channel_id': channel_id}))

    async def _handle_role_create(self, peer: Peer, body: dict) -> None:
        result = await self.role_manager.create_role(
            body.get('server_id', 0), body.get('name', ''),
            body.get('color', 0), body.get('permissions', 0), peer.db_user_id
        )
        await peer.send(pack_json(MsgType.ROLE_CREATE, result))

    async def _handle_role_list(self, peer: Peer, body: dict) -> None:
        server_id = body.get('server_id', 0)
        if not server_id or not await self._check_server_membership(peer, server_id):
            await peer.send(pack_json(MsgType.ROLE_LIST, {'roles': []}))
            return
        roles = await self.role_manager.get_server_roles(server_id)
        await peer.send(pack_json(MsgType.ROLE_LIST, {'roles': roles}))

    async def _handle_member_role_add(self, peer: Peer, body: dict) -> None:
        result = await self.role_manager.assign_role(
            body.get('user_id', 0), body.get('role_id', 0), peer.db_user_id
        )
        await peer.send(pack_json(MsgType.MEMBER_ROLE_ADD, result))

    async def _handle_member_role_remove(self, peer: Peer, body: dict) -> None:
        result = await self.role_manager.remove_role(
            body.get('user_id', 0), body.get('role_id', 0), peer.db_user_id
        )
        await peer.send(pack_json(MsgType.MEMBER_ROLE_REMOVE, result))

    async def _handle_role_update(self, peer: Peer, body: dict) -> None:
        result = await self.role_manager.update_role(
            body.get('role_id', 0), peer.db_user_id,
            name=body.get('name'), color=body.get('color'),
            permissions=body.get('permissions')
        )
        await peer.send(pack_json(MsgType.ROLE_UPDATE, result))

    async def _handle_role_delete(self, peer: Peer, body: dict) -> None:
        result = await self.role_manager.delete_role(
            body.get('role_id', 0), peer.db_user_id
        )
        await peer.send(pack_json(MsgType.ROLE_DELETE, result))

    # --- Channel update handler ---

    async def _handle_channel_update(self, peer: Peer, body: dict) -> None:
        result = await self.channel_manager.update_channel(
            body.get('channel_id', 0), peer.db_user_id,
            name=body.get('name'), topic=body.get('topic'),
            position=body.get('position')
        )
        await peer.send(pack_json(MsgType.CHANNEL_UPDATE, result))

    # --- Member management handlers ---

    async def _handle_member_list(self, peer: Peer, body: dict) -> None:
        server_id = body.get('server_id', 0)
        if not server_id or not await self._check_server_membership(peer, server_id):
            await peer.send(pack_json(MsgType.MEMBER_LIST, {'success': False, 'members': []}))
            return
        result = await self.member_manager.get_members(server_id)
        await peer.send(pack_json(MsgType.MEMBER_LIST, result))

    async def _handle_member_leave(self, peer: Peer, body: dict) -> None:
        server_id = body.get('server_id', 0)
        await self.db.remove_member(server_id, peer.db_user_id)
        await peer.send(pack_json(MsgType.MEMBER_LEAVE, {'success': True, 'server_id': server_id}))

    async def _handle_member_kick(self, peer: Peer, body: dict) -> None:
        result = await self.member_manager.kick_member(
            body.get('server_id', 0), body.get('target_id', 0), peer.db_user_id,
        )
        await peer.send(pack_json(MsgType.MEMBER_KICK, result))

    async def _handle_member_ban(self, peer: Peer, body: dict) -> None:
        result = await self.member_manager.ban_member(
            body.get('server_id', 0), body.get('target_id', 0), peer.db_user_id,
            reason=body.get('reason', ''),
        )
        await peer.send(pack_json(MsgType.MEMBER_BAN, result))

    # --- DM handlers ---

    async def _handle_dm_send(self, peer: Peer, body: dict) -> None:
        recipient_id = body.get('recipient_id', 0)
        # Stranger DM gate: respect the recipient's ignore list + auto-ignore setting
        recipient_settings = await self.db.get_user_settings(recipient_id)
        if recipient_id and recipient_id != peer.db_user_id:
            if recipient_settings.get('auto_ignore_dm'):
                if not await self.db.are_friends(peer.db_user_id, recipient_id):
                    await peer.send(pack_json(MsgType.DM_SEND, {
                        'success': False,
                        'error': 'this user ignores DMs from non-friends',
                    }))
                    return
            if await self.db.is_dm_ignored(recipient_id, peer.db_user_id):
                await peer.send(pack_json(MsgType.DM_SEND, {
                    'success': False,
                    'error': 'this user has ignored your DMs',
                }))
                return

        result = await self.dm_manager.send_dm(
            peer.db_user_id,
            recipient_id,
            body.get('content', ''),
            attachments=body.get('attachments'),
        )
        await peer.send(pack_json(MsgType.DM_SEND, result))
        # Push DM to recipient if online
        if result.get('success'):
            dm = result.get('dm', {})
            dm['username'] = peer.display
            dm['is_friend'] = await self.db.are_friends(peer.db_user_id, recipient_id)
            dm_pkt = pack_json(MsgType.DM_SEND, {'success': True, 'dm': dm})
            async with self.lock:
                for room_peers in self.rooms.values():
                    for p in room_peers.values():
                        if p.db_user_id == recipient_id:
                            try:
                                await p.send(dm_pkt)
                            except Exception:
                                pass

    async def _handle_dm_read(self, peer: Peer, body: dict) -> None:
        other_id = body.get('user_id', 0)
        await self.db.mark_dm_conversation_read(peer.db_user_id, other_id)
        await peer.send(pack_json(MsgType.DM_READ, {'success': True, 'user_id': other_id}))

    async def _handle_dm_ignore(self, peer: Peer, body: dict) -> None:
        other_id = body.get('user_id', 0)
        ok = await self.db.add_dm_ignore(peer.db_user_id, other_id)
        await peer.send(pack_json(MsgType.DM_IGNORE, {
            'success': ok, 'user_id': other_id,
        }))

    async def _handle_dm_history(self, peer: Peer, body: dict) -> None:
        result = await self.dm_manager.get_dm_history(
            peer.db_user_id,
            body.get('user_id', 0),
            limit=body.get('limit', 50),
            before=body.get('before'),
        )
        await peer.send(pack_json(MsgType.DM_HISTORY, result))

    async def _handle_dm_list(self, peer: Peer) -> None:
        result = await self.dm_manager.get_dm_conversations(peer.db_user_id)
        await peer.send(pack_json(MsgType.DM_LIST, result))

    # --- Friend handlers ---

    async def _handle_friend_add(self, peer: Peer, body: dict) -> None:
        result = await self.friend_manager.add_friend(
            peer.db_user_id, body.get('friend_id', 0),
        )
        await peer.send(pack_json(MsgType.FRIEND_ADD, result))
        # Notify the recipient of the new pending request so their badge updates
        if result.get('success'):
            await self._push_friend_requests(body.get('friend_id', 0))

    async def _handle_friend_remove(self, peer: Peer, body: dict) -> None:
        result = await self.friend_manager.remove_friend(
            peer.db_user_id, body.get('friend_id', 0),
        )
        await peer.send(pack_json(MsgType.FRIEND_REMOVE, result))

    async def _handle_friend_list(self, peer: Peer) -> None:
        result = await self.friend_manager.get_friends(peer.db_user_id)
        await peer.send(pack_json(MsgType.FRIEND_LIST, result))

    async def _handle_friend_accept(self, peer: Peer, body: dict) -> None:
        result = await self.friend_manager.accept_friend(
            peer.db_user_id, body.get('friend_id', 0),
        )
        await peer.send(pack_json(MsgType.FRIEND_ACCEPT, result))
        # pending-request count for this user changed — refresh their badge
        if result.get('success'):
            await self._push_friend_requests(peer.db_user_id)

    async def _handle_friend_decline(self, peer: Peer, body: dict) -> None:
        result = await self.friend_manager.remove_friend(
            peer.db_user_id, body.get('friend_id', 0),
        )
        await peer.send(pack_json(MsgType.FRIEND_DECLINE, result))
        if result.get('success'):
            await self._push_friend_requests(peer.db_user_id)

    async def _handle_friend_requests(self, peer: Peer) -> None:
        result = await self.friend_manager.get_pending_requests(peer.db_user_id)
        await peer.send(pack_json(MsgType.FRIEND_REQUESTS, result))

    async def _push_friend_requests(self, user_id: int) -> None:
        """Recompute + push pending friend requests to all of a user's connections."""
        result = await self.friend_manager.get_pending_requests(user_id)
        pkt = pack_json(MsgType.FRIEND_REQUESTS, result)
        async with self.lock:
            for room_peers in self.rooms.values():
                for p in room_peers.values():
                    if p.db_user_id == user_id:
                        try:
                            await p.send(pkt)
                        except Exception:
                            pass

    async def _handle_settings_get(self, peer: Peer) -> None:
        settings = await self.db.get_user_settings(peer.db_user_id)
        await peer.send(pack_json(MsgType.SETTINGS_GET, {'success': True, 'settings': settings}))

    async def _handle_settings_update(self, peer: Peer, body: dict) -> None:
        auto_ignore = body.get('auto_ignore_dm')
        if auto_ignore is None:
            await peer.send(pack_json(MsgType.SETTINGS_UPDATE, {
                'success': False, 'error': 'auto_ignore_dm required',
            }))
            return
        ok = await self.db.update_user_settings(peer.db_user_id, bool(auto_ignore))
        await peer.send(pack_json(MsgType.SETTINGS_UPDATE, {
            'success': ok,
            'settings': {'auto_ignore_dm': 1 if auto_ignore else 0},
        }))

    # --- Status handlers ---

    async def _handle_status_update(self, peer: Peer, body: dict) -> None:
        status = body.get('status', 'online')
        if status not in ("online", "idle", "dnd", "offline"):
            status = "online"
        if self.db:
            await self.db.update_user_status(peer.db_user_id, status)
        await peer.send(pack_json(MsgType.STATUS_UPDATE, {'status': status}))

    async def _handle_presence_update(self, peer: Peer) -> None:
        await peer.send(pack_json(MsgType.PRESENCE_UPDATE, {
            'user_id': peer.user_id,
            'display': peer.display,
            'status': 'online'
        }))

    # --- Legacy room handlers ---

    async def _hello(self, peer: Peer, body: dict) -> None:
        """Legacy room-based hello (for backward compatibility)."""
        user_id = str(body.get("user_id", "")).strip()
        room = str(body.get("room", "lobby")).strip() or "lobby"
        display = str(body.get("display", user_id)).strip() or user_id
        ident_b64 = body.get("identity_pub", "")
        if not user_id or not ident_b64:
            await peer.send(pack_json(MsgType.ERROR, {"error": "user_id and identity_pub required"}))
            return
        try:
            identity = b64d(ident_b64)
            if len(identity) != 32:
                raise ValueError("bad key length")
        except Exception:
            await peer.send(pack_json(MsgType.ERROR, {"error": "invalid identity_pub"}))
            return

        async with self.lock:
            room_peers = self.rooms.setdefault(room, {})
            if user_id in room_peers:
                await peer.send(pack_json(MsgType.ERROR, {"error": "user_id already in room"}))
                return
            peer.user_id = user_id
            peer.display = display
            peer.identity_pub = identity
            peer.room = room
            others = [
                {
                    "user_id": p.user_id,
                    "display": p.display,
                    "identity_pub": b64(p.identity_pub),
                }
                for p in room_peers.values()
            ]
            room_peers[user_id] = peer
            self.peer_count += 1
            self.room_count = len(self.rooms)

        await peer.send(
            pack_json(MsgType.WELCOME, {"user_id": user_id, "room": room, "peers": others})
        )
        join = pack_json(MsgType.PEER_JOIN, {
            "user_id": user_id, "display": display, "identity_pub": b64(identity),
        })
        await self._broadcast(peer, join, include_self=False)
        log.info("%s joined room %s (%d peers)", user_id, room, len(self.rooms.get(room, {})))

    async def _cleanup_peer(self, peer: Peer) -> None:
        """Remove a dead/disconnected peer without broadcasting (to avoid recursion)."""
        if not peer.user_id or not peer.room:
            return
        if peer.current_channel_id and peer.current_channel_id in self.channel_peers:
            self.channel_peers[peer.current_channel_id].discard(peer.user_id)
        if peer.current_channel_id and peer.current_channel_id in self.voice_channel_members:
            if peer.user_id in self.voice_channel_members[peer.current_channel_id]:
                del self.voice_channel_members[peer.current_channel_id][peer.user_id]
                if peer.current_server_id:
                    await self._broadcast_voice_channel_members(peer.current_channel_id, peer.current_server_id)
        async with self.lock:
            room_peers = self.rooms.get(peer.room, {})
            if peer.user_id in room_peers and room_peers[peer.user_id] is peer:
                del room_peers[peer.user_id]
                self.peer_count -= 1
            if peer.room in self.rooms and not self.rooms[peer.room]:
                del self.rooms[peer.room]
            self.room_count = len(self.rooms)

    async def _leave(self, peer: Peer) -> None:
        if not peer.user_id or not peer.room:
            return
        # Clean up channel membership
        if peer.current_channel_id and peer.current_channel_id in self.channel_peers:
            self.channel_peers[peer.current_channel_id].discard(peer.user_id)
        # Clean up voice channel membership
        if peer.current_channel_id and peer.current_channel_id in self.voice_channel_members:
            if peer.user_id in self.voice_channel_members[peer.current_channel_id]:
                del self.voice_channel_members[peer.current_channel_id][peer.user_id]
                if peer.current_server_id:
                    await self._broadcast_voice_channel_members(peer.current_channel_id, peer.current_server_id)
        async with self.lock:
            room_peers = self.rooms.get(peer.room, {})
            if peer.user_id in room_peers and room_peers[peer.user_id] is peer:
                del room_peers[peer.user_id]
                self.peer_count -= 1
            if peer.room in self.rooms and not self.rooms[peer.room]:
                del self.rooms[peer.room]
            self.room_count = len(self.rooms)
            # Check if user has any other connections
            still_connected = any(
                p.user_id == peer.user_id for room in self.rooms.values() for p in room.values()
            )
        if not still_connected:
            await self.db.update_user_status(peer.db_user_id, 'offline')
            if peer.current_server_id:
                await self._broadcast_member_list_to_server(peer.current_server_id)
        leave = pack_json(MsgType.PEER_LEAVE, {"user_id": peer.user_id})
        await self._broadcast_room(peer.room, leave, exclude=peer.user_id)

    async def _broadcast(self, sender: Peer, pkt: Packet, include_self: bool = False) -> None:
        await self._broadcast_room(
            sender.room, pkt, exclude=None if include_self else sender.user_id,
        )

    async def _broadcast_room(self, room: str, pkt: Packet, exclude: str | None) -> None:
        async with self.lock:
            targets = list(self.rooms.get(room, {}).values())
        dead: list[Peer] = []
        for p in targets:
            if exclude and p.user_id == exclude:
                continue
            try:
                await p.send(pkt)
            except Exception:
                dead.append(p)
        for p in dead:
            await self._cleanup_peer(p)

    async def _broadcast_to_channel(self, channel_id: int, pkt: Packet, exclude_user: int = 0) -> None:
        """Broadcast to all connected peers viewing the same channel."""
        viewer_ids = self.channel_peers.get(channel_id, set()).copy()
        if not viewer_ids:
            return
        async with self.lock:
            all_peers = []
            for room_peers in self.rooms.values():
                for peer in room_peers.values():
                    if peer.db_user_id in viewer_ids and peer.db_user_id != exclude_user:
                        all_peers.append(peer)
        for p in all_peers:
            try:
                await p.send(pkt)
            except Exception:
                pass

    async def _broadcast_voice_channel_members(self, channel_id: int, server_id: int) -> None:
        """Broadcast updated voice channel member list to all peers in the server."""
        members = [
            {'user_id': uid, 'display': name}
            for uid, name in self.voice_channel_members.get(channel_id, {}).items()
        ]
        pkt = pack_json(MsgType.CHANNEL_JOIN, {
            'success': True, 'channel_id': channel_id,
            'voice_members': members, 'update_only': True,
        })
        # Broadcast to all peers in the same room (server)
        async with self.lock:
            for room_peers in self.rooms.values():
                for peer in room_peers.values():
                    if peer.current_server_id == server_id:
                        try:
                            await peer.send(pkt)
                        except Exception:
                            pass

    # --- Admin auth methods (relay operator only) ---

    async def force_authenticate(self, user_id: int, display: str) -> dict:
        """Manually authenticate a user without going through normal auth flow.
        Requires admin_auth_enabled=True. Returns status dict.
        Matches by display name first (for admin auth requests), then falls back to
        the first unauthenticated peer.
        """
        if not self.admin_auth_enabled:
            return {'success': False, 'error': 'Admin auth not enabled (use --admin-auth)'}

        target_peer = None
        async with self.lock:
            # First pass: match by display name (for peers that sent ADMIN_AUTH_REQUEST)
            for room_peers in self.rooms.values():
                for peer in room_peers.values():
                    if not peer.db_user_id and peer.display == display:
                        target_peer = peer
                        break
                if target_peer:
                    break

            # Second pass: first unauthenticated peer with any display
            if not target_peer:
                for room_peers in self.rooms.values():
                    for peer in room_peers.values():
                        if not peer.db_user_id:
                            target_peer = peer
                            break
                    if target_peer:
                        break

        if not target_peer:
            return {'success': False, 'error': 'No unauthenticated peer found. Client must connect first.'}

        # Set auth state
        target_peer.db_user_id = user_id
        target_peer.user_id = str(user_id)
        target_peer.display = display

        # Send AUTH_SUCCESS to the peer
        try:
            await target_peer.send(pack_json(MsgType.AUTH_SUCCESS, {
                'user_id': user_id,
                'username': display,
                'admin_auth': True,
            }))
        except Exception:
            return {'success': False, 'error': 'Failed to send to peer'}

        log.info("admin auth: user_id=%d display=%s", user_id, display)
        return {'success': True, 'user_id': user_id, 'display': display}

    async def force_unauthenticate(self, user_id: int) -> dict:
        """Manually unauthenticate a user, clearing their auth state."""
        if not self.admin_auth_enabled:
            return {'success': False, 'error': 'Admin auth not enabled (use --admin-auth)'}

        target_peer = None
        async with self.lock:
            for room_peers in self.rooms.values():
                for peer in room_peers.values():
                    if peer.db_user_id == user_id:
                        target_peer = peer
                        break
                if target_peer:
                    break

        if not target_peer:
            return {'success': False, 'error': f'No peer with user_id={user_id}'}

        # Clear auth state
        target_peer.db_user_id = 0
        target_peer.user_id = ""
        target_peer.display = ""

        # Send AUTH_ERROR to notify the peer
        try:
            await target_peer.send(pack_json(MsgType.AUTH_ERROR, {
                'error': 'Force-unauthenticated by relay operator',
                'admin_unauth': True,
            }))
        except Exception:
            pass

        log.info("admin unauth: user_id=%d", user_id)
        return {'success': True, 'user_id': user_id}

    async def kick_peer(self, user_id: int) -> dict:
        """Disconnect a peer by user_id."""
        if not self.admin_auth_enabled:
            return {'success': False, 'error': 'Admin auth not enabled (use --admin-auth)'}

        target_peer = None
        async with self.lock:
            for room_peers in self.rooms.values():
                for peer in room_peers.values():
                    if peer.db_user_id == user_id:
                        target_peer = peer
                        break
                if target_peer:
                    break

        if not target_peer:
            return {'success': False, 'error': f'No peer with user_id={user_id}'}

        # Close the connection — _leave() will handle cleanup
        try:
            target_peer.writer.close()
        except Exception:
            pass

        log.info("admin kick: user_id=%d", user_id)
        return {'success': True, 'user_id': user_id}

    def list_peers(self) -> list[dict]:
        """List all connected peers with their auth state."""
        peers = []
        for room_peers in self.rooms.values():
            for peer in room_peers.values():
                peers.append({
                    'user_id': peer.db_user_id,
                    'display': peer.display,
                    'room': peer.room,
                    'authenticated': bool(peer.db_user_id),
                    'channel_id': peer.current_channel_id,
                    'server_id': peer.current_server_id,
                })
        return peers


async def main_async(host: str, port: int, upnp: bool = True, admin_auth: bool = False,
                     db_path: str = "labhairliom.db", encrypt_db: bool = True,
                     require_auth: bool = False, auto_auth: bool = False,
                     tls: bool = False, certfile: str = "", keyfile: str = "") -> None:
    encryptor = None
    if encrypt_db:
        key_path = Path(db_path).parent / ".labhairliom_key"
        key = FieldEncryptor.load_or_create_key(key_path)
        encryptor = FieldEncryptor(key)
        log.info("database encryption enabled (key: %s)", key_path)
        if not key_path.exists() or key_path.stat().st_size == 0:
            log.warning("")
            log.warning("=" * 70)
            log.warning("  IMPORTANT: A new encryption key has been generated.")
            log.warning("  Back up this file: %s", key_path)
            log.warning("")
            log.warning("  If you lose this key, your database WILL BE")
            log.warning("  PERMANENTLY UNREADABLE. No one can recover it.")
            log.warning("")
            log.warning("  Copy it to a safe location NOW:")
            log.warning("    cp %s /path/to/backup/", key_path)
            log.warning("=" * 70)
            log.warning("")
    db = Database(db_path, encryptor=encryptor)
    await db.connect()
    await db.update_all_users_offline()
    relay = Relay(db)
    relay.admin_auth_enabled = admin_auth
    relay.require_auth = require_auth
    relay.auto_auth = auto_auth
    ssl_ctx = None
    if tls:
        if certfile and keyfile:
            ssl_ctx = _create_server_ssl_context(certfile, keyfile)
            log.info("TLS enabled with provided cert: %s", certfile)
        else:
            # Auto-generate self-signed cert
            cert_dir = Path(db_path).parent
            auto_cert = str(cert_dir / ".labhairliom_cert.pem")
            auto_key = str(cert_dir / ".labhairliom_key.pem")
            if not Path(auto_cert).exists():
                _generate_self_signed_cert(auto_cert, auto_key)
                log.info("generated self-signed TLS cert: %s", auto_cert)
            ssl_ctx = _create_server_ssl_context(auto_cert, auto_key)
            log.info("TLS enabled with auto-generated cert")
    server = await asyncio.start_server(relay.handle, host, port, ssl=ssl_ctx)
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets or [])
    log.info("relay listening on %s (database: %s)", addrs, db_path)
    if admin_auth:
        log.info("admin auth enabled — use CLI commands to manage peers")

    mapping = None
    if upnp and host in ("0.0.0.0", ""):
        from shared.upnp import setup_port_mapping
        mapping = setup_port_mapping(port, description="Labhair-liom Relay")
        if mapping:
            ext_ip = mapping.external_ip or "?"
            log.info("UPnP: external %s:%d -> %s:%d", ext_ip, port, mapping.lan_ip, port)

    # Start CLI reader if admin_auth is enabled
    cli_task = None
    if admin_auth:
        cli_task = asyncio.ensure_future(_admin_cli(relay))

    try:
        async with server:
            await server.serve_forever()
    finally:
        if cli_task:
            cli_task.cancel()
        await db.close()
        if mapping:
            mapping.cleanup()


async def _admin_cli(relay: Relay) -> None:
    """Read admin commands from stdin while relay is running."""
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    print("\n[admin] Commands: auth <uid> <name> | unauth <uid> | kick <uid> | list | help | quit")

    while True:
        try:
            line = await reader.readline()
            if not line:
                break
            line = line.decode().strip()
            if not line:
                continue

            parts = line.split(None, 2)
            cmd = parts[0].lower()

            if cmd == "help":
                print("  auth <user_id> <display>  — Force-authenticate a peer")
                print("  unauth <user_id>          — Force-unauthenticate a peer")
                print("  kick <user_id>            — Disconnect a peer")
                print("  list                      — Show connected peers")
                print("  quit                      — Stop the relay")

            elif cmd == "auth":
                if len(parts) < 3:
                    print("Usage: auth <user_id> <display>")
                    continue
                try:
                    uid = int(parts[1])
                except ValueError:
                    print("user_id must be an integer")
                    continue
                result = await relay.force_authenticate(uid, parts[2])
                print(f"  {'OK' if result['success'] else 'FAIL'}: {result}")

            elif cmd == "unauth":
                if len(parts) < 2:
                    print("Usage: unauth <user_id>")
                    continue
                try:
                    uid = int(parts[1])
                except ValueError:
                    print("user_id must be an integer")
                    continue
                result = await relay.force_unauthenticate(uid)
                print(f"  {'OK' if result['success'] else 'FAIL'}: {result}")

            elif cmd == "kick":
                if len(parts) < 2:
                    print("Usage: kick <user_id>")
                    continue
                try:
                    uid = int(parts[1])
                except ValueError:
                    print("user_id must be an integer")
                    continue
                result = await relay.kick_peer(uid)
                print(f"  {'OK' if result['success'] else 'FAIL'}: {result}")

            elif cmd == "list":
                peers = relay.list_peers()
                if not peers:
                    print("  No connected peers")
                else:
                    for p in peers:
                        authed = "AUTH" if p['authenticated'] else "UNAUTH"
                        print(f"  [{authed}] uid={p['user_id']} display={p['display']} room={p['room']} ch={p['channel_id']} srv={p['server_id']}")

            elif cmd == "quit":
                print("Shutting down...")
                import os
                os._exit(0)

            else:
                print(f"Unknown command: {cmd}. Type 'help' for commands.")

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Error: {e}")


class RelayController:
    """Run a relay in a worker thread for the desktop control window."""

    def __init__(
        self,
        host: str,
        port: int,
        upnp: bool,
        tor: bool,
        tor_control_port: int,
        tor_control_host: str,
        status: Callable[[str], None],
        admin_auth: bool = False,
        db_path: str = "labhairliom.db",
        encrypt_db: bool = True,
        require_auth: bool = False,
        auto_auth: bool = False,
        tls: bool = False,
        certfile: str = "",
        keyfile: str = "",
    ) -> None:
        self.host = host
        self.port = port
        self.upnp = upnp
        self.tor = tor
        self.tor_control_port = tor_control_port
        self.tor_control_host = tor_control_host
        self.status = status
        self.admin_auth = admin_auth
        self.db_path = db_path
        self.encrypt_db = encrypt_db
        self.require_auth = require_auth
        self.auto_auth = auto_auth
        self.tls = tls
        self.certfile = certfile
        self.keyfile = keyfile
        self.relay = Relay()
        self.relay.admin_auth_enabled = admin_auth
        self.relay.require_auth = require_auth
        self.relay.auto_auth = auto_auth
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="labhairliom-relay", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def peer_count(self) -> int:
        return self.relay.peer_count

    def room_count(self) -> int:
        return self.relay.room_count

    def _run(self) -> None:
        asyncio.run(self._serve())

    async def _serve(self) -> None:
        mapping = None
        hidden_service = None
        server = None
        db = None
        started = False
        try:
            encryptor = None
            if self.encrypt_db:
                key_path = Path(self.db_path).parent / ".labhairliom_key"
                key = FieldEncryptor.load_or_create_key(key_path)
                encryptor = FieldEncryptor(key)
                log.info("database encryption enabled (key: %s)", key_path)
            db = Database(self.db_path, encryptor=encryptor)
            await db.connect()
            self.relay.db = db
            self.relay.auth_handler = AuthHandler(db)
            self.relay.server_manager = ServerManager(db)
            self.relay.channel_manager = ChannelManager(db)
            self.relay.role_manager = RoleManager(db)
            self.relay.message_manager = MessageManager(db)
            self.relay.dm_manager = DMManager(db)
            self.relay.friend_manager = FriendManager(db)
            self.relay.member_manager = MemberManager(db, self.relay.role_manager)
            self.relay.thread_manager = ThreadManager(db)
            log.info("database connected: %s", self.db_path)
            ssl_ctx = None
            if self.tls:
                if self.certfile and self.keyfile:
                    ssl_ctx = _create_server_ssl_context(self.certfile, self.keyfile)
                else:
                    cert_dir = Path(self.db_path).parent
                    auto_cert = str(cert_dir / ".labhairliom_cert.pem")
                    auto_key = str(cert_dir / ".labhairliom_key.pem")
                    if not Path(auto_cert).exists():
                        _generate_self_signed_cert(auto_cert, auto_key)
                    ssl_ctx = _create_server_ssl_context(auto_cert, auto_key)
                log.info("TLS enabled")
            server = await asyncio.start_server(self.relay.handle, self.host, self.port, ssl=ssl_ctx)
            started = True
            addrs = ", ".join(str(s.getsockname()) for s in server.sockets or [])
            log.info("relay listening on %s (database: %s)", addrs, self.db_path)
            self.status(f"Running — {addrs}")
            if self.upnp and self.host in ("0.0.0.0", ""):
                from shared.upnp import setup_port_mapping

                mapping = setup_port_mapping(self.port, description="Labhair-liom Relay")
                if mapping:
                    self.status(f"Running — {addrs}\nUPnP mapped: {mapping.external_ip or '?'}:{self.port}")
            if self.tor:
                hidden_service = _setup_hidden_service(
                    self.port, self.tor_control_port, self.tor_control_host
                )
                if hidden_service:
                    self.status(f"Running — {addrs}\nTor address: {hidden_service.onion}")
                else:
                    self.status(f"Running — {addrs}\nTor service unavailable; check the Tor ControlPort settings.")
            await asyncio.to_thread(self._stop.wait)
        except Exception as exc:
            log.exception("relay failed to start")
            self.status(f"Could not start relay: {exc}")
        finally:
            try:
                await self.relay.shutdown_gracefully()
            except Exception:
                pass
            if server:
                server.close()
                await server.wait_closed()
            if db:
                await db.close()
            if mapping:
                mapping.cleanup()
            if hidden_service:
                hidden_service.cleanup()
            if started:
                self.status("Stopped")


class RelayWindow:
    """Minimal desktop UI for hosting a relay without a terminal."""

    def __init__(
        self,
        host: str,
        port: int,
        upnp: bool,
        tor: bool = False,
        tor_control_port: int = 9051,
        tor_control_host: str = "127.0.0.1",
        admin_auth: bool = False,
        db_path: str = "labhairliom.db",
        encrypt_db: bool = True,
        require_auth: bool = False,
        auto_auth: bool = False,
        tls: bool = False,
        certfile: str = "",
        keyfile: str = "",
    ) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.root = tk.Tk()
        self.root.title("Labhair-liom Relay")
        self.events: queue.Queue[str] = queue.Queue()
        self.controller: RelayController | None = None
        self.admin_auth = admin_auth
        self.db_path = db_path
        self.encrypt_db = encrypt_db
        self.require_auth = require_auth
        self.auto_auth = auto_auth
        self.tls = tls
        self.certfile = certfile
        self.keyfile = keyfile

        frame = ttk.Frame(self.root, padding=18)
        frame.grid(sticky="nsew")
        ttk.Label(frame, text="Labhair-liom Relay", font=("TkDefaultFont", 16, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(frame, text="Routes encrypted traffic only — it cannot read messages.").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(2, 16)
        )

        self.host_var = tk.StringVar(value=host)
        self.port_var = tk.StringVar(value=str(port))
        self.db_var = tk.StringVar(value=db_path)
        self.encrypt_var = tk.BooleanVar(value=encrypt_db)
        self.upnp_var = tk.BooleanVar(value=upnp)
        self.tor_var = tk.BooleanVar(value=tor)
        self.tor_control_port = tor_control_port
        self.tor_control_host = tor_control_host
        ttk.Label(frame, text="Listen address").grid(row=2, column=0, sticky="w", pady=3)
        self.host_entry = ttk.Entry(frame, textvariable=self.host_var, width=23)
        self.host_entry.grid(row=2, column=1, sticky="ew", pady=3)
        ttk.Label(frame, text="Port").grid(row=3, column=0, sticky="w", pady=3)
        self.port_entry = ttk.Entry(frame, textvariable=self.port_var, width=23)
        self.port_entry.grid(row=3, column=1, sticky="ew", pady=3)
        ttk.Label(frame, text="Database").grid(row=4, column=0, sticky="w", pady=3)
        self.db_entry = ttk.Entry(frame, textvariable=self.db_var, width=23)
        self.db_entry.grid(row=4, column=1, sticky="ew", pady=3)
        ttk.Label(frame, text="SQLite path or postgresql:// URL", foreground="#888").grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(0, 3)
        )
        self.encrypt_check = ttk.Checkbutton(frame, text="Encrypt database (AES-256)", variable=self.encrypt_var)
        self.encrypt_check.grid(row=6, column=0, columnspan=2, sticky="w", pady=(2, 3))
        self.upnp_check = ttk.Checkbutton(frame, text="Map port using UPnP", variable=self.upnp_var)
        self.upnp_check.grid(row=7, column=0, columnspan=2, sticky="w", pady=(4, 3))
        self.tor_check = ttk.Checkbutton(frame, text="Host through Tor (.onion)", variable=self.tor_var)
        self.tor_check.grid(row=8, column=0, columnspan=2, sticky="w", pady=(4, 3))
        self.require_auth_var = tk.BooleanVar(value=require_auth)
        self.require_auth_check = ttk.Checkbutton(frame, text="Require authentication (kick unauthenticated after 30s)", variable=self.require_auth_var)
        self.require_auth_check.grid(row=9, column=0, columnspan=2, sticky="w", pady=(4, 3))
        self.auto_auth_var = tk.BooleanVar(value=auto_auth)
        self.auto_auth_check = ttk.Checkbutton(frame, text="Auto-authenticate new peers", variable=self.auto_auth_var)
        self.auto_auth_check.grid(row=10, column=0, columnspan=2, sticky="w", pady=(0, 14))

        self.state_var = tk.StringVar(value="Stopped")
        self.details_var = tk.StringVar(value="Ready to start")
        ttk.Label(frame, textvariable=self.state_var, foreground="#a61b1b", font=("TkDefaultFont", 11, "bold")).grid(
            row=11, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(frame, textvariable=self.details_var, justify="left", wraplength=340).grid(
            row=12, column=0, columnspan=2, sticky="w", pady=(2, 10)
        )
        self.stats_var = tk.StringVar(value="0 peers in 0 rooms")
        ttk.Label(frame, textvariable=self.stats_var).grid(row=13, column=0, sticky="w", pady=(0, 14))
        self.button = ttk.Button(frame, text="Start relay", command=self.toggle)
        self.button.grid(row=14, column=0, columnspan=2, sticky="ew")
        self.manage_btn = ttk.Button(frame, text="Manage connected users", command=self.open_user_list, state="disabled")
        self.manage_btn.grid(row=15, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.update_idletasks()
        self.root.geometry("")
        self.root.resizable(False, False)
        self.root.after(200, self.refresh)

    def toggle(self) -> None:
        if self.controller and self.controller.running:
            self.button.configure(state="disabled", text="Stopping…")
            self.details_var.set("Closing the listening socket and active connections…")
            self.controller.stop()
            return
        try:
            port = int(self.port_var.get())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            self.state_var.set("Invalid port")
            self.details_var.set("Enter a port number from 1 to 65535.")
            return
        host = self.host_var.get().strip() or "0.0.0.0"
        self.db_path = self.db_var.get().strip() or "labhairliom.db"
        self.controller = RelayController(
            host, port, self.upnp_var.get(), self.tor_var.get(),
            self.tor_control_port, self.tor_control_host, self.events.put,
            admin_auth=self.admin_auth, db_path=self.db_path,
            encrypt_db=self.encrypt_var.get(), require_auth=self.require_auth_var.get(),
            auto_auth=self.auto_auth_var.get(),
            tls=self.tls, certfile=self.certfile, keyfile=self.keyfile,
        )
        self.host_entry.configure(state="disabled")
        self.port_entry.configure(state="disabled")
        self.db_entry.configure(state="disabled")
        self.encrypt_check.configure(state="disabled")
        self.upnp_check.configure(state="disabled")
        self.tor_check.configure(state="disabled")
        self.require_auth_check.configure(state="disabled")
        self.auto_auth_check.configure(state="disabled")
        self.button.configure(state="disabled", text="Starting…")
        self.state_var.set("Starting")
        self.details_var.set("Opening the relay socket…")
        self.controller.start()

    def refresh(self) -> None:
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event.startswith("Running"):
                self.state_var.set("● Running")
                self.details_var.set(event.removeprefix("Running — "))
                self.button.configure(state="normal", text="Stop relay")
                self.manage_btn.configure(state="normal")
            elif event == "Stopped":
                self.state_var.set("Stopped")
                self.details_var.set("Relay is not accepting connections.")
                self.button.configure(state="normal", text="Start relay")
                self.manage_btn.configure(state="disabled")
                self.host_entry.configure(state="normal")
                self.port_entry.configure(state="normal")
                self.db_entry.configure(state="normal")
                self.encrypt_check.configure(state="normal")
                self.upnp_check.configure(state="normal")
                self.tor_check.configure(state="normal")
                self.require_auth_check.configure(state="normal")
                self.auto_auth_check.configure(state="normal")
            else:
                self.state_var.set("Start failed")
                self.details_var.set(event)
                self.button.configure(state="normal", text="Start relay")
                self.manage_btn.configure(state="disabled")
                self.host_entry.configure(state="normal")
                self.port_entry.configure(state="normal")
                self.db_entry.configure(state="normal")
                self.encrypt_check.configure(state="normal")
                self.upnp_check.configure(state="normal")
                self.tor_check.configure(state="normal")
                self.require_auth_check.configure(state="normal")
                self.auto_auth_check.configure(state="normal")
        if self.controller and self.controller.running:
            self.stats_var.set(f"{self.controller.peer_count()} peers in {self.controller.room_count()} rooms")
        else:
            self.stats_var.set("0 peers in 0 rooms")
        self.root.after(200, self.refresh)

    def close(self) -> None:
        if self.controller and self.controller.running:
            self.controller.stop()
            self.root.after(100, self.close)
            return
        self.root.destroy()

    def open_user_list(self) -> None:
        if not self.controller or not self.controller.running:
            return
        UserListWindow(self.root, self.controller.relay)

    def run(self) -> None:
        self.root.mainloop()


class UserListWindow:
    """Window showing connected peers with admin actions."""

    def __init__(self, parent, relay: Relay) -> None:
        import tkinter as tk
        from tkinter import ttk, messagebox

        self.relay = relay
        self.root = tk.Toplevel(parent)
        self.root.title("Connected Users")
        self.root.resizable(False, False)
        self.root.transient(parent)

        cols = ("display", "user_id", "status")
        self.tree = ttk.Treeview(self.root, columns=cols, show="headings", selectmode="browse", height=6)
        self.tree.heading("display", text="Display Name")
        self.tree.heading("user_id", text="User ID")
        self.tree.heading("status", text="Status")
        self.tree.column("display", width=180)
        self.tree.column("user_id", width=70)
        self.tree.column("status", width=90)
        self.tree.place(x=10, y=10, width=400, height=180)

        btn_frame = ttk.Frame(self.root)
        btn_frame.place(x=10, y=195, width=400, height=40)

        ttk.Button(btn_frame, text="Authenticate", command=self._auth_selected).pack(side="left", padx=(0, 4))
        ttk.Button(btn_frame, text="Kick", command=self._kick_selected).pack(side="left", padx=(0, 4))
        ttk.Button(btn_frame, text="Update Email", command=self._update_email).pack(side="left", padx=(0, 4))
        ttk.Button(btn_frame, text="Refresh", command=self._refresh).pack(side="right")

        self.root.geometry("420x250")
        self._refresh()

    def _refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for peer in self.relay.list_peers():
            status = "Authed" if peer["authenticated"] else "Waiting"
            self.tree.insert("", "end", values=(
                peer["display"] or "(none)", peer["user_id"] or "-", status
            ))

    def _selected_display(self) -> str | None:
        sel = self.tree.selection()
        if not sel:
            return None
        return self.tree.item(sel[0])["values"][0]

    def _run_async(self, coro_fn, callback=None):
        """Run an async function in a background thread."""
        import threading

        def _worker():
            result = asyncio.run(coro_fn())
            if callback and self.root.winfo_exists():
                self.root.after(0, lambda: callback(result))

        threading.Thread(target=_worker, daemon=True).start()

    def _auth_selected(self) -> None:
        import tkinter as tk
        from tkinter import simpledialog, messagebox

        display = self._selected_display()
        if not display:
            messagebox.showinfo("Authenticate", "Select a user first.", parent=self.root)
            return
        user_id = simpledialog.askinteger("Authenticate", f"Enter user ID for '{display}':", parent=self.root, minvalue=1)
        if not user_id:
            return

        async def do_auth():
            return await self.relay.force_authenticate(user_id, display)

        def on_done(result):
            if result["success"]:
                messagebox.showinfo("Authenticate", f"Authenticated '{display}' as user {user_id}.", parent=self.root)
            else:
                messagebox.showerror("Authenticate", result["error"], parent=self.root)
            self._refresh()

        self._run_async(do_auth, on_done)

    def _kick_selected(self) -> None:
        from tkinter import messagebox

        display = self._selected_display()
        if not display:
            messagebox.showinfo("Kick", "Select a user first.", parent=self.root)
            return
        if not messagebox.askyesno("Kick", f"Kick '{display}'?", parent=self.root):
            return

        async def do_kick():
            return await self.relay.kick_peer(display)

        def on_done(result):
            self._refresh()

        self._run_async(do_kick, on_done)

    def _update_email(self) -> None:
        import tkinter as tk
        from tkinter import simpledialog, messagebox

        display = self._selected_display()
        if not display:
            messagebox.showinfo("Update Email", "Select a user first.", parent=self.root)
            return

        sel = self.tree.selection()
        user_id_str = self.tree.item(sel[0])["values"][1]
        if user_id_str == "-":
            messagebox.showinfo("Update Email", "User not registered (no user ID).", parent=self.root)
            return
        user_id = int(user_id_str)

        new_email = simpledialog.askstring("Update Email", f"New email for '{display}':", parent=self.root)
        if not new_email:
            return

        async def do_update():
            return await self.relay.db.update_user_email(user_id, new_email)

        def on_done(ok):
            msg = "Email updated." if ok else "Failed to update email."
            messagebox.showinfo("Update Email", msg, parent=self.root)

        self._run_async(do_update, on_done)


class TorHiddenService:
    """An ephemeral onion service which is removed when the relay stops."""

    def __init__(self, controller: object, service_id: str) -> None:
        self.controller = controller
        self.service_id = service_id
        self.onion = service_id + ".onion"

    def cleanup(self) -> None:
        try:
            self.controller.remove_ephemeral_hidden_service(self.service_id)  # type: ignore[attr-defined]
        except Exception:
            log.warning("could not remove Tor hidden service %s", self.onion, exc_info=True)
        finally:
            try:
                self.controller.close()  # type: ignore[attr-defined]
            except Exception:
                pass


def _setup_hidden_service(port: int, control_port: int, control_host: str) -> TorHiddenService | None:
    """Create an ephemeral Tor hidden service via stem."""
    try:
        from stem.control import Controller
    except ImportError:
        print("[tor] stem library not installed. Install with: pip install stem", file=sys.stderr)
        print("[tor] Manual setup: add to /etc/tor/torrc:", file=sys.stderr)
        print(f"[tor]   HiddenServiceDir /var/lib/tor/chat-relay/", file=sys.stderr)
        print(f"[tor]   HiddenServicePort 80 127.0.0.1:{port}", file=sys.stderr)
        return None

    try:
        controller = Controller.from_port(address=control_host, port=control_port)
        controller.authenticate()
    except Exception as exc:
        print(f"[tor] cannot connect to Tor ControlPort ({control_host}:{control_port}): {exc}", file=sys.stderr)
        print("[tor] Ensure Tor is running with ControlPort enabled in torrc:", file=sys.stderr)
        print(f"[tor]   ControlPort {control_port}", file=sys.stderr)
        print(f"[tor]   CookieAuthentication 1", file=sys.stderr)
        return None

    try:
        response = controller.create_ephemeral_hidden_service(
            f"80:127.0.0.1:{port}",
            detached=True,
        )
        hidden_service = TorHiddenService(controller, response.service_id)
        log.info("tor hidden service: %s", hidden_service.onion)
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"  Tor hidden service active: {hidden_service.onion}", file=sys.stderr)
        print(f"  Clients can connect with: --tor --host {hidden_service.onion}", file=sys.stderr)
        print(f"{'='*60}\n", file=sys.stderr)
        return hidden_service
    except Exception as exc:
        print(f"[tor] failed to create hidden service: {exc}", file=sys.stderr)
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description="E2E LABHAIR_LIOM chat relay (untrusted)")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=9473)
    ap.add_argument("--no-upnp", dest="upnp", action="store_false", help="disable UPnP port mapping")
    ap.add_argument("--tor", action="store_true", help="create a Tor hidden service")
    ap.add_argument("--tor-control-port", type=int, default=9051, help="Tor ControlPort (default: 9051)")
    ap.add_argument("--tor-control-host", default="127.0.0.1", help="Tor ControlPort host")
    ap.add_argument("--admin-auth", action="store_true", help="enable admin CLI to manually authenticate/unauthenticate users")
    ap.add_argument("--db", default="labhairliom.db", help="path to SQLite database file (default: labhairliom.db)")
    ap.add_argument("--db-url", default=None, help="database connection URL (e.g. postgresql://user:pass@host/dbname)")
    ap.add_argument("--encrypt-db", action="store_true", default=True, help="encrypt sensitive fields in the database (AES-256-GCM) [default: on]")
    ap.add_argument("--no-encrypt-db", dest="encrypt_db", action="store_false", help="disable database field encryption")
    ap.add_argument("--require-auth", action="store_true", help="kick unauthenticated peers after 30 seconds")
    ap.add_argument("--auto-auth", action="store_true", help="automatically authenticate new peers without operator approval")
    ap.add_argument("--gui", action="store_true", help="open the relay start/stop control window")
    ap.add_argument("--no-gui", action="store_true", help="run in the terminal (also disables the GUI in the packaged app)")
    ap.add_argument("--tls", action="store_true", help="enable TLS encryption (auto-generates self-signed cert if no cert/key provided)")
    ap.add_argument("--certfile", default="", help="path to TLS certificate file (PEM)")
    ap.add_argument("--keyfile", default="", help="path to TLS private key file (PEM)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # A packaged relay is normally launched by double-clicking it, so show the
    # controls by default there.  Source/CLI invocations remain script-friendly.
    use_gui = (args.gui or getattr(sys, "frozen", False)) and not args.no_gui
    db_path = args.db_url or args.db
    if use_gui:
        try:
            RelayWindow(
                args.host, args.port, args.upnp, args.tor,
                args.tor_control_port, args.tor_control_host,
                admin_auth=args.admin_auth, db_path=db_path,
                encrypt_db=args.encrypt_db, require_auth=args.require_auth,
                auto_auth=args.auto_auth,
                tls=args.tls, certfile=args.certfile, keyfile=args.keyfile,
            ).run()
        except Exception as exc:
            print(f"Could not open relay UI: {exc}", file=sys.stderr)
            if args.gui:
                return
        return

    if args.tor:
        _setup_hidden_service(args.port, args.tor_control_port, args.tor_control_host)

    try:
        asyncio.run(main_async(args.host, args.port, upnp=args.upnp, admin_auth=args.admin_auth,
                               db_path=db_path, encrypt_db=args.encrypt_db,
                               require_auth=args.require_auth, auto_auth=args.auto_auth,
                               tls=args.tls, certfile=args.certfile, keyfile=args.keyfile))
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
