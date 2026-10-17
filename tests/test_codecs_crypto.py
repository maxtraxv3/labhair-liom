#!/usr/bin/env python3
"""Smoke tests for crypto, ADPCM, Labhair-liom, and framing."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.adpcm import ADPCMCodec, ADPCMFrame, FRAME_SAMPLES as ADPCM_FRAME_SAMPLES, WIRE_TAG
from shared.labhair_liom import LabhairLiomDecoder, LabhairLiomEncoder, LabhairLiomFrame
from shared.crypto import derive_session, generate_identity, new_ephemeral
from shared.protocol import FrameReader, MsgType, Packet, pack_json


def test_frame_reader() -> None:
    p1 = pack_json(MsgType.CHAT, {"a": 1})
    p2 = Packet(MsgType.VOICE, b"\x00\x01\x02")
    blob = p1.encode() + p2.encode()
    # split arbitrarily
    fr = FrameReader()
    mid = len(blob) // 3
    out = fr.feed(blob[:mid]) + fr.feed(blob[mid:])
    assert len(out) == 2
    assert out[0].type == MsgType.CHAT
    assert out[1].payload == b"\x00\x01\x02"
    print("OK frame_reader")


def test_e2e_crypto() -> None:
    id_a, pub_a = generate_identity()
    id_b, pub_b = generate_identity()
    eph_a, epub_a = new_ephemeral()
    eph_b, epub_b = new_ephemeral()

    # A is initiator if pub_a < pub_b
    a_init = pub_a < pub_b
    sess_a = derive_session(id_a, eph_a, pub_b, epub_b, i_am_initiator=a_init)
    sess_b = derive_session(id_b, eph_b, pub_a, epub_a, i_am_initiator=not a_init)

    aad = b"test-aad"
    ct = sess_a.encrypt(b"hello e2e", aad=aad)
    pt = sess_b.decrypt(ct, aad=aad)
    assert pt == b"hello e2e"

    ct2 = sess_b.encrypt(b"reply", aad=aad)
    assert sess_a.decrypt(ct2, aad=aad) == b"reply"
    print("OK e2e_crypto")


def test_adpcm_roundtrip() -> None:
    enc = ADPCMCodec(dtx=False)
    dec = ADPCMCodec(dtx=False)

    # 440 Hz tone at 8 kHz
    t = np.arange(ADPCM_FRAME_SAMPLES) / 8000.0
    pcm = (0.4 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)

    blob = enc.encode(pcm)
    assert blob is not None
    fr = ADPCMFrame.unpack(blob)
    assert not fr.dtx
    assert len(fr.data) == 80  # BYTES_PER_FRAME
    assert WIRE_TAG == "ADPCM/ima-v1"

    out = dec.decode(blob)
    assert out.dtype == np.int16
    assert len(out) == ADPCM_FRAME_SAMPLES
    # decoded should track the original tone
    assert float(np.max(np.abs(out))) > 100
    print("OK adpcm_roundtrip")


def test_adpcm_dtx() -> None:
    enc = ADPCMCodec(dtx=True)
    dec = ADPCMCodec(dtx=False)

    # silence → DTX should suppress frames
    silent = np.zeros(ADPCM_FRAME_SAMPLES, dtype=np.int16)
    blob1 = enc.encode(silent)
    assert blob1 is not None  # first silent frame sends SID
    fr1 = ADPCMFrame.unpack(blob1)
    assert fr1.dtx

    blob2 = enc.encode(silent)
    assert blob2 is None  # subsequent silence → suppressed

    # SID frame decodes to zeros without crashing
    out = dec.decode(blob1)
    assert len(out) == ADPCM_FRAME_SAMPLES
    assert float(np.max(np.abs(out))) == 0.0
    print("OK adpcm_dtx")


def test_adpcm_short_long_frames() -> None:
    codec = ADPCMCodec(dtx=False)

    # short frame (padding)
    short = np.array([1000, -1000], dtype=np.int16)
    blob = codec.encode(short)
    assert blob is not None
    out = codec.decode(blob)
    assert len(out) == ADPCM_FRAME_SAMPLES

    # long frame (truncation)
    long = np.tile(np.array([500, -500], dtype=np.int16), ADPCM_FRAME_SAMPLES)
    blob = codec.encode(long)
    assert blob is not None
    out = codec.decode(blob)
    assert len(out) == ADPCM_FRAME_SAMPLES
    print("OK adpcm_short_long_frames")


def test_labhairliom_roundtrip() -> None:
    from shared.labhair_liom import FLAG_CAMERA, FLAG_SCREEN

    enc = LabhairLiomEncoder(width=40, height=12, fps=5, flags=FLAG_CAMERA)
    img = np.linspace(0, 255, 40 * 12, dtype=np.uint8).reshape(12, 40)
    blob = enc.encode_gray(img)
    fr = LabhairLiomFrame.decode(blob)
    assert fr.width == 40 and fr.height == 12
    assert len(fr.rows) == 12
    assert all(len(r) == 40 for r in fr.rows)
    assert fr.source == "camera"
    assert fr.flags & FLAG_CAMERA
    fr2 = LabhairLiomDecoder().decode(blob)
    assert fr2.rows == fr.rows

    enc_s = LabhairLiomEncoder(width=60, height=20, fps=4, flags=FLAG_SCREEN)
    blob_s = enc_s.encode_gray(img)
    fr_s = LabhairLiomFrame.decode(blob_s)
    assert fr_s.source == "screen"
    assert fr_s.flags & FLAG_SCREEN
    print("OK labhairliom_roundtrip")


if __name__ == "__main__":
    test_frame_reader()
    test_e2e_crypto()
    test_adpcm_roundtrip()
    test_adpcm_dtx()
    test_adpcm_short_long_frames()
    test_labhairliom_roundtrip()
    print("\nAll smoke tests passed.")
