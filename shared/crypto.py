"""End-to-end cryptography.

Identity: long-term X25519 keys (exported as raw 32-byte public keys).
Session: ephemeral X25519 ECDH + HKDF-SHA256 → ChaCha20-Poly1305 keys.

The relay never sees plaintext. Each peer pair derives independent TX/RX keys
so ciphertext is not reusable across directions.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def generate_identity() -> tuple[X25519PrivateKey, bytes]:
    priv = X25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return priv, pub


def load_public(raw: bytes) -> X25519PublicKey:
    if len(raw) != 32:
        raise ValueError("X25519 public key must be 32 bytes")
    return X25519PublicKey.from_public_bytes(raw)


def b64(data: bytes) -> str:
    import base64

    return base64.b64encode(data).decode("ascii")


def b64d(data: str) -> bytes:
    import base64

    return base64.b64decode(data.encode("ascii"))


@dataclass
class SessionKeys:
    """Directional AEAD keys for one peer pair."""

    send: ChaCha20Poly1305
    recv: ChaCha20Poly1305
    send_nonce_prefix: bytes  # 4 bytes
    recv_nonce_prefix: bytes  # 4 bytes
    _send_counter: int = 0
    _recv_seen: set[int] | None = None

    def __post_init__(self) -> None:
        if self._recv_seen is None:
            self._recv_seen = set()

    def encrypt(self, plaintext: bytes, aad: bytes = b"") -> bytes:
        """Return nonce_counter(8) || ciphertext||tag."""
        counter = self._send_counter
        self._send_counter += 1
        nonce = self.send_nonce_prefix + struct.pack("!Q", counter)[:8]
        # ChaCha20-Poly1305 needs 12-byte nonce: 4 prefix + 8 counter
        nonce12 = self.send_nonce_prefix + struct.pack("!Q", counter)
        ct = self.send.encrypt(nonce12, plaintext, aad)
        return struct.pack("!Q", counter) + ct

    def decrypt(self, blob: bytes, aad: bytes = b"") -> bytes:
        if len(blob) < 8 + 16:
            raise ValueError("ciphertext too short")
        counter = struct.unpack("!Q", blob[:8])[0]
        if counter in self._recv_seen:
            raise ValueError("replayed nonce")
        # Keep a bounded replay window
        self._recv_seen.add(counter)
        if len(self._recv_seen) > 4096:
            # drop lowest half
            ordered = sorted(self._recv_seen)
            self._recv_seen = set(ordered[len(ordered) // 2 :])
        nonce12 = self.recv_nonce_prefix + struct.pack("!Q", counter)
        return self.recv.decrypt(nonce12, blob[8:], aad)


def derive_session(
    my_identity: X25519PrivateKey,
    my_ephemeral: X25519PrivateKey,
    peer_identity_pub: bytes,
    peer_ephemeral_pub: bytes,
    i_am_initiator: bool,
) -> SessionKeys:
    """Triple-DH style key agreement (identity + ephemeral).

    shared = ECDH(eph, peer_eph) || ECDH(id, peer_eph) || ECDH(eph, peer_id)

    Both peers must feed the same ordered IKM into HKDF. ECDH is symmetric for
    matching key pairs, but the concatenation order of the three DH results
    must be identical on both sides — we order the two mixed terms by who is
    the initiator (lower identity public key).
    """
    peer_id = load_public(peer_identity_pub)
    peer_eph = load_public(peer_ephemeral_pub)

    my_id_bytes = my_identity.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    # DH(eph, peer_eph) — same on both sides
    dh_ee = my_ephemeral.exchange(peer_eph)
    # Mixed terms: initiator's identity with responder's ephemeral, and vice versa
    dh_me_peer_eph = my_identity.exchange(peer_eph)  # my_id × peer_eph
    dh_my_eph_peer_id = my_ephemeral.exchange(peer_id)  # my_eph × peer_id

    if i_am_initiator:
        # IKM = EE || (init_id × resp_eph) || (init_eph × resp_id)
        ikm = dh_ee + dh_me_peer_eph + dh_my_eph_peer_id
        id_lo, id_hi = my_id_bytes, peer_identity_pub
    else:
        # Mirror: EE || (init_id × resp_eph) || (init_eph × resp_id)
        # As responder: init_id × resp_eph = peer_id × my_eph = dh_my_eph_peer_id
        #               init_eph × resp_id = peer_eph × my_id = dh_me_peer_eph
        ikm = dh_ee + dh_my_eph_peer_id + dh_me_peer_eph
        id_lo, id_hi = peer_identity_pub, my_id_bytes

    info = b"e2e-labhairliom-chat/v1" + id_lo + id_hi

    material = HKDF(
        algorithm=hashes.SHA256(),
        length=64 + 8,
        salt=None,
        info=info,
    ).derive(ikm)

    # Shared material: key_a/prefix_a = initiator→responder, key_b = reverse
    key_a = material[0:32]
    key_b = material[32:64]
    prefix_a = material[64:68]
    prefix_b = material[68:72]

    if i_am_initiator:
        send_key, recv_key = key_a, key_b
        send_p, recv_p = prefix_a, prefix_b
    else:
        send_key, recv_key = key_b, key_a
        send_p, recv_p = prefix_b, prefix_a

    return SessionKeys(
        send=ChaCha20Poly1305(send_key),
        recv=ChaCha20Poly1305(recv_key),
        send_nonce_prefix=send_p,
        recv_nonce_prefix=recv_p,
    )


def new_ephemeral() -> tuple[X25519PrivateKey, bytes]:
    return generate_identity()


def random_token(n: int = 16) -> str:
    return b64(os.urandom(n)).rstrip("=")
