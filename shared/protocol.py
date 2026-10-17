"""Wire protocol for the untrusted relay.

All application payloads (chat, voice, video) are opaque ciphertext to the
server. Only routing metadata is plaintext.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Any


class MsgType(IntEnum):
    # Original types
    HELLO = 0x01
    WELCOME = 0x02
    PEER_JOIN = 0x03
    PEER_LEAVE = 0x04
    KEY_EXCHANGE = 0x10
    CHAT = 0x20
    VOICE = 0x30
    VIDEO = 0x40
    IMAGE = 0x45
    FILE = 0x46
    CONTROL = 0x50
    ERROR = 0x7F

    # Authentication
    REGISTER = 0x80
    LOGIN = 0x81
    LOGOUT = 0x82
    AUTH_SUCCESS = 0x83
    AUTH_ERROR = 0x84

    # Servers
    SERVER_CREATE = 0x90
    SERVER_JOIN = 0x91
    SERVER_LEAVE = 0x92
    SERVER_LIST = 0x93
    SERVER_INFO = 0x94
    SERVER_UPDATE = 0x95
    SERVER_DELETE = 0x96

    # Channels
    CHANNEL_CREATE = 0xA0
    CHANNEL_DELETE = 0xA1
    CHANNEL_LIST = 0xA2
    CHANNEL_INFO = 0xA3
    CHANNEL_JOIN = 0xA4
    CHANNEL_LEAVE = 0xA5
    CHANNEL_UPDATE = 0xA6

    # Messages
    MESSAGE_SEND = 0xB0
    MESSAGE_EDIT = 0xB1
    MESSAGE_DELETE = 0xB2
    MESSAGE_HISTORY = 0xB3
    MESSAGE_PIN = 0xB4
    MESSAGE_UNPIN = 0xB5
    MESSAGE_REACTION_ADD = 0xB6
    MESSAGE_REACTION_REMOVE = 0xB7

    # Members
    MEMBER_LIST = 0xC0
    MEMBER_JOIN = 0xC1
    MEMBER_LEAVE = 0xC2
    MEMBER_KICK = 0xC3
    MEMBER_BAN = 0xC4
    MEMBER_ROLE_ADD = 0xC5
    MEMBER_ROLE_REMOVE = 0xC6

    # Roles
    ROLE_CREATE = 0xD0
    ROLE_DELETE = 0xD1
    ROLE_UPDATE = 0xD2
    ROLE_LIST = 0xD3

    # Direct Messages
    DM_SEND = 0xE0
    DM_HISTORY = 0xE1
    DM_LIST = 0xE2
    DM_READ = 0xE3  # mark a conversation read
    DM_IGNORE = 0xE4  # block a user's DMs (stranger spam guard)

    # Friends
    FRIEND_ADD = 0xE8
    FRIEND_REMOVE = 0xE9
    FRIEND_LIST = 0xEA
    FRIEND_ACCEPT = 0xEB
    FRIEND_DECLINE = 0xEC
    FRIEND_REQUESTS = 0xED  # pending friend requests (incoming)

    # Threads
    THREAD_CREATE = 0xD8
    THREAD_JOIN = 0xD9
    THREAD_LEAVE = 0xDA
    THREAD_LIST = 0xDB
    THREAD_INFO = 0xDC
    THREAD_MESSAGE_SEND = 0xDD
    THREAD_MESSAGE_HISTORY = 0xDE
    THREAD_ARCHIVE = 0xDF

    # Search
    SEARCH_MESSAGES = 0xC8
    SEARCH_RESULTS = 0xC9

    # Server Invites
    INVITE_CREATE = 0x37
    INVITE_JOIN = 0x38
    INVITE_LIST = 0x39
    INVITE_DELETE = 0x3A

    # User Profiles
    PROFILE_GET = 0x3B
    PROFILE_UPDATE = 0x3C
    AVATAR_GET = 0x3D
    TYPING_START = 0x3E
    MSG_PIN = 0x3F
    MSG_UNPIN = 0x41
    MSG_PINNED_LIST = 0x42

    # Status
    STATUS_UPDATE = 0xF0
    PRESENCE_UPDATE = 0xF1
    SETTINGS_GET = 0xF2
    SETTINGS_UPDATE = 0xF3

    # Admin
    ADMIN_AUTH_REQUEST = 0xF8
    SERVER_NOTICE = 0xF9


HEADER = struct.Struct("!IB")  # length (payload only), type
MAX_PAYLOAD = 1 << 20  # 1 MiB


@dataclass
class Packet:
    type: MsgType
    payload: bytes

    def encode(self) -> bytes:
        if len(self.payload) > MAX_PAYLOAD:
            raise ValueError("payload too large")
        return HEADER.pack(len(self.payload), int(self.type)) + self.payload


def pack_json(msg_type: MsgType, obj: dict[str, Any]) -> Packet:
    return Packet(msg_type, json.dumps(obj, separators=(",", ":")).encode("utf-8"))


def unpack_json(payload: bytes) -> dict[str, Any]:
    return json.loads(payload.decode("utf-8"))


class FrameReader:
    """Incremental length-prefixed frame parser."""

    MAX_BUFFER = 2 * (1 << 20)  # 2 MiB max buffer before disconnect

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[Packet]:
        self._buf.extend(data)
        if len(self._buf) > self.MAX_BUFFER:
            raise ValueError(f"buffer overflow: {len(self._buf)} bytes")
        out: list[Packet] = []
        while True:
            if len(self._buf) < HEADER.size:
                break
            length, mtype = HEADER.unpack_from(self._buf, 0)
            if length > MAX_PAYLOAD:
                raise ValueError(f"frame too large: {length}")
            total = HEADER.size + length
            if len(self._buf) < total:
                break
            payload = bytes(self._buf[HEADER.size:total])
            del self._buf[:total]
            try:
                out.append(Packet(MsgType(mtype), payload))
            except ValueError as exc:
                raise ValueError(f"unknown message type {mtype}") from exc
        return out
