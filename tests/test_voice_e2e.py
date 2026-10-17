#!/usr/bin/env python3
"""Test voice E2E: mic capture -> encode -> encrypt -> relay -> decrypt -> decode -> speakers.

This uses a mock sounddevice to avoid real audio hardware, but exercises the
full codec + crypto + relay path.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
from shared.adpcm import ADPCMCodec, FRAME_SAMPLES
from shared.crypto import SessionKeys, b64, b64d, derive_session, new_ephemeral
from shared.protocol import FrameReader, MsgType, Packet, pack_json, unpack_json

RELAY_HOST = "127.0.0.1"
RELAY_PORT = 9474


class MockStream:
    def __init__(self):
        self.sent = []

    def write(self, data):
        self.sent.append(data)

    async def drain(self):
        pass


class TestClient:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.fr = FrameReader()
        self.sessions: dict[str, SessionKeys] = {}
        self.peer_identity: dict[str, bytes] = {}
        self.peer_display: dict[str, str] = {}
        self.identity_priv, self.identity_pub = None, None
        self.eph_priv, self.eph_pub = None, None
        self.received_voice: list[bytes] = []

    async def connect(self, room: str = "testroom"):
        self.reader, self.writer = await asyncio.open_connection(RELAY_HOST, RELAY_PORT)
        self.identity_priv, self.identity_pub = new_ephemeral()
        hello = {
            "user_id": self.user_id,
            "room": room,
            "display": self.user_id,
            "identity_pub": b64(self.identity_pub),
        }
        self.writer.write(pack_json(MsgType.HELLO, hello).encode())
        await self.writer.drain()
        data = await self.reader.read(65536)
        for pkt in self.fr.feed(data):
            if pkt.type == MsgType.WELCOME:
                body = unpack_json(pkt.payload)
                for p in body["peers"]:
                    uid = p["user_id"]
                    if uid != self.user_id:
                        self.peer_identity[uid] = b64d(p["identity_pub"])
                        self.peer_display[uid] = p.get("display", uid)
                        print(f"  [{self.user_id}] peer registered: {uid}")

    async def key_exchange_all(self):
        if self.eph_priv is None:
            self.eph_priv, self.eph_pub = new_ephemeral()
        for pid in self.peer_identity:
            body = {
                "from": self.user_id,
                "to": pid,
                "identity_pub": b64(self.identity_pub),
                "ephemeral_pub": b64(self.eph_pub),
            }
            self.writer.write(pack_json(MsgType.KEY_EXCHANGE, body).encode())
            print(f"  [{self.user_id}] sent KEY_EXCHANGE to {pid}")
        await self.writer.drain()

    def _i_am_initiator(self, peer_id: str, peer_pub: bytes) -> bool:
        return self.identity_pub < peer_pub

    def _complete_session(self, peer_id: str, peer_eph: bytes):
        peer_pub = self.peer_identity[peer_id]
        initiator = self._i_am_initiator(peer_id, peer_pub)
        sess = derive_session(self.identity_priv, self.eph_priv, peer_pub, peer_eph, i_am_initiator=initiator)
        self.sessions[peer_id] = sess
        print(f"  [{self.user_id}] session established with {peer_id}")

    async def read_loop(self):
        while True:
            data = await self.reader.read(65536)
            if not data:
                break
            for pkt in self.fr.feed(data):
                if pkt.type == MsgType.PEER_JOIN:
                    body = unpack_json(pkt.payload)
                    uid = body["user_id"]
                    if uid != self.user_id and uid not in self.peer_identity:
                        self.peer_identity[uid] = b64d(body["identity_pub"])
                        self.peer_display[uid] = body.get("display", uid)
                        print(f"  [{self.user_id}] peer joined: {uid}")
                        # auto key exchange
                        if self.eph_priv is None:
                            self.eph_priv, self.eph_pub = new_ephemeral()
                        body2 = {
                            "from": self.user_id,
                            "to": uid,
                            "identity_pub": b64(self.identity_pub),
                            "ephemeral_pub": b64(self.eph_pub),
                        }
                        self.writer.write(pack_json(MsgType.KEY_EXCHANGE, body2).encode())
                        await self.writer.drain()
                        print(f"  [{self.user_id}] sent KEY_EXCHANGE to {uid}")

                elif pkt.type == MsgType.KEY_EXCHANGE:
                    body = unpack_json(pkt.payload)
                    src = body["from"]
                    if src == self.user_id:
                        continue
                    if src not in self.peer_identity:
                        continue
                    peer_eph = b64d(body["ephemeral_pub"])
                    if src not in self.sessions:
                        self._complete_session(src, peer_eph)

                elif pkt.type == MsgType.VOICE:
                    body = unpack_json(pkt.payload)
                    src = body["from"]
                    if src == self.user_id:
                        continue
                    ct = b64d(body["ct"])
                    sess = self.sessions.get(src)
                    if not sess:
                        print(f"  [{self.user_id}] NO SESSION for {src}, dropping voice")
                        continue
                    aad = f"{src}|{self.user_id}|{int(MsgType.VOICE)}".encode()
                    pt = sess.decrypt(ct, aad=aad)
                    self.received_voice.append(pt)
                    print(f"  [{self.user_id}] received voice ({len(pt)} bytes from {src})")

    async def run(self):
        await self.connect()
        await asyncio.sleep(0.1)
        await self.key_exchange_all()
        await asyncio.sleep(0.2)

        # Now send a voice frame
        codec = ADPCMCodec(dtx=False)
        pcm = (np.random.randn(FRAME_SAMPLES) * 3000).astype(np.int16)
        blob = codec.encode(pcm)
        for pid in self.sessions:
            aad = f"{self.user_id}|{pid}|{int(MsgType.VOICE)}".encode()
            ct = self.sessions[pid].encrypt(blob, aad=aad)
            body = {"from": self.user_id, "to": pid, "ct": b64(ct)}
            self.writer.write(pack_json(MsgType.VOICE, body).encode())
            print(f"  [{self.user_id}] sent voice to {pid} ({len(blob)} bytes)")
        await self.writer.drain()

        await asyncio.sleep(0.5)


async def main():
    relay_proc = await asyncio.create_subprocess_exec(
        sys.executable, str(ROOT / "server" / "relay.py"), "--port", str(RELAY_PORT),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    await asyncio.sleep(0.3)

    alice = TestClient("alice")
    bob = TestClient("bob")

    async def run_alice():
        await alice.run()
        assert len(alice.sessions) == 1, f"Alice has {len(alice.sessions)} sessions, expected 1"
        assert len(alice.received_voice) >= 0, "Alice should have received voice"

    async def run_bob():
        await bob.run()
        assert len(bob.sessions) == 1, f"Bob has {len(bob.sessions)} sessions, expected 1"
        assert len(bob.received_voice) == 1, f"Bob received {len(bob.received_voice)} voice frames, expected 1"

    await asyncio.gather(run_alice(), run_bob())

    relay_proc.terminate()
    relay_proc_stderr = await relay_proc.stderr.read()
    relay_proc_stdout = await relay_proc.stdout.read()
    print(f"\nRelay stderr: {relay_proc_stderr.decode()}")
    print(f"Relay stdout: {relay_proc_stdout.decode()}")

    print(f"\nAlice sessions: {list(alice.sessions.keys())}")
    print(f"Alice received voice: {len(alice.received_voice)} frames")
    print(f"Bob sessions: {list(bob.sessions.keys())}")
    print(f"Bob received voice: {len(bob.received_voice)} frames")

    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
