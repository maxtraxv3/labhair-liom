"""IMA/DVI ADPCM — free, ultra-low CPU voice/system audio.

Public domain algorithm (Interactive Multimedia Association ADPCM). No patents
block free use. Designed for lowest encode/decode cost:

  • 16 kHz mono
  • 4 bits/sample → 64 kbit/s while talking
  • 20 ms frames (320 samples → 160 payload bytes)
  • DTX / silence skip → near-zero bandwidth when quiet

Payload tag: ``audio/adpcm-ima; rate=16000`` (``ADPCM/ima-v1`` on the wire).

This is the default codec for mic voice and screen-share system sound.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

SAMPLE_RATE = 16000
FRAME_MS = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 320
BYTES_PER_FRAME = FRAME_SAMPLES // 2  # 4-bit → 160 bytes
BITRATE_KBPS = SAMPLE_RATE * 4 // 1000  # 64 kb/s active
PAYLOAD_MIME = "audio/adpcm-ima; rate=16000"
WIRE_TAG = "ADPCM/ima-v1"

# IMA step / index tables (public domain)
_STEP = np.array(
    [
        7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41,
        45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190,
        209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724,
        796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272,
        2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132,
        7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500,
        20350, 22385, 24623, 27086, 29794, 32767,
    ],
    dtype=np.int32,
)
_INDEX = np.array([-1, -1, -1, -1, 2, 4, 6, 8], dtype=np.int32)

# DTX: energy threshold on int16 PCM (after abs mean)
SILENCE_THRESH = 180
# Keep sending ~2 SID frames/sec while silent so receivers know we're alive
SID_INTERVAL = 25  # frames @ 20 ms ≈ 0.5 s


@dataclass
class _State:
    pred: int = 0
    index: int = 0


def _encode_sample(sample: int, st: _State) -> int:
    step = int(_STEP[st.index])
    diff = sample - st.pred
    code = 0
    if diff < 0:
        code = 8
        diff = -diff
    if diff >= step:
        code |= 4
        diff -= step
    step >>= 1
    if diff >= step:
        code |= 2
        diff -= step
    step >>= 1
    if diff >= step:
        code |= 1

    # reconstruct predictor
    step = int(_STEP[st.index])
    diffq = step >> 3
    if code & 4:
        diffq += step
    if code & 2:
        diffq += step >> 1
    if code & 1:
        diffq += step >> 2
    if code & 8:
        st.pred -= diffq
    else:
        st.pred += diffq
    st.pred = max(-32768, min(32767, st.pred))
    st.index = int(np.clip(st.index + int(_INDEX[code & 7]), 0, 88))
    return code & 0xF


def _decode_sample(code: int, st: _State) -> int:
    step = int(_STEP[st.index])
    diffq = step >> 3
    if code & 4:
        diffq += step
    if code & 2:
        diffq += step >> 1
    if code & 1:
        diffq += step >> 2
    if code & 8:
        st.pred -= diffq
    else:
        st.pred += diffq
    st.pred = max(-32768, min(32767, st.pred))
    st.index = int(np.clip(st.index + int(_INDEX[code & 7]), 0, 88))
    return st.pred


@dataclass
class ADPCMFrame:
    """One 20 ms IMA-ADPCM frame (or DTX SID)."""

    seq: int
    dtx: bool
    data: bytes  # empty if dtx
    pred: int = 0
    index: int = 0

    def pack(self) -> bytes:
        # magic(2) ver(1) flags(1) seq(4) pred(2) index(1) pad(1) + payload
        flags = 0x01 if self.dtx else 0x00
        header = struct.pack(
            "!2sBBIhBB",
            b"AD",
            1,
            flags,
            self.seq & 0xFFFFFFFF,
            int(self.pred),
            int(self.index) & 0xFF,
            0,
        )
        if self.dtx:
            return header
        return header + self.data

    @classmethod
    def unpack(cls, blob: bytes) -> ADPCMFrame:
        if len(blob) < 12:
            raise ValueError("ADPCM frame too short")
        magic, ver, flags, seq, pred, index, _pad = struct.unpack("!2sBBIhBB", blob[:12])
        if magic != b"AD" or ver != 1:
            raise ValueError("not ADPCM/ima-v1")
        dtx = bool(flags & 0x01)
        data = b"" if dtx else blob[12 : 12 + BYTES_PER_FRAME]
        return cls(seq=seq, dtx=dtx, data=data, pred=pred, index=index)


class ADPCMCodec:
    """Stateful IMA-ADPCM encoder/decoder with optional DTX."""

    def __init__(self, dtx: bool = True) -> None:
        self.dtx_enabled = dtx
        self._seq = 0
        self._enc = _State()
        self._dec = _State()
        self._silent_run = 0

    @property
    def bitrate(self) -> int:
        return BITRATE_KBPS

    def encode(self, pcm16: np.ndarray) -> bytes | None:
        """Encode one frame. Returns None if DTX drops the frame (no send)."""
        if len(pcm16) != FRAME_SAMPLES:
            if len(pcm16) < FRAME_SAMPLES:
                pcm16 = np.pad(pcm16.astype(np.int16), (0, FRAME_SAMPLES - len(pcm16)))
            else:
                pcm16 = pcm16[:FRAME_SAMPLES]
        pcm16 = pcm16.astype(np.int16)

        energy = float(np.mean(np.abs(pcm16.astype(np.int32))))
        if self.dtx_enabled and energy < SILENCE_THRESH:
            self._silent_run += 1
            # Rare SID to resync predictor; otherwise drop (save bandwidth)
            if self._silent_run == 1 or self._silent_run % SID_INTERVAL == 0:
                fr = ADPCMFrame(
                    seq=self._seq,
                    dtx=True,
                    data=b"",
                    pred=self._enc.pred,
                    index=self._enc.index,
                )
                self._seq = (self._seq + 1) & 0xFFFFFFFF
                return fr.pack()
            self._seq = (self._seq + 1) & 0xFFFFFFFF
            return None
        self._silent_run = 0

        out = bytearray(BYTES_PER_FRAME)
        pred_snap, idx_snap = self._enc.pred, self._enc.index
        for i in range(0, FRAME_SAMPLES, 2):
            n0 = _encode_sample(int(pcm16[i]), self._enc)
            n1 = _encode_sample(int(pcm16[i + 1]), self._enc) if i + 1 < FRAME_SAMPLES else 0
            out[i // 2] = (n0 & 0xF) | ((n1 & 0xF) << 4)
        fr = ADPCMFrame(
            seq=self._seq,
            dtx=False,
            data=bytes(out),
            pred=pred_snap,
            index=idx_snap,
        )
        self._seq = (self._seq + 1) & 0xFFFFFFFF
        return fr.pack()

    def decode(self, blob: bytes) -> np.ndarray:
        fr = ADPCMFrame.unpack(blob)
        if fr.dtx or not fr.data:
            # comfort noise from predictor
            self._dec.pred = fr.pred
            self._dec.index = fr.index
            # soft fade to near-silence
            return np.zeros(FRAME_SAMPLES, dtype=np.int16)

        # Optional hard resync from encoder snapshot (robust to loss)
        self._dec.pred = fr.pred
        self._dec.index = fr.index

        pcm = np.zeros(FRAME_SAMPLES, dtype=np.int16)
        n = min(len(fr.data), BYTES_PER_FRAME)
        for i in range(n):
            b = fr.data[i]
            pcm[i * 2] = _decode_sample(b & 0xF, self._dec)
            if i * 2 + 1 < FRAME_SAMPLES:
                pcm[i * 2 + 1] = _decode_sample((b >> 4) & 0xF, self._dec)
        return pcm


def downsample_16k_to_8k(pcm16: np.ndarray) -> np.ndarray:
    """Cheap 2:1 average downsample (very low CPU)."""
    x = pcm16.astype(np.int32)
    if len(x) % 2:
        x = x[:-1]
    return ((x[0::2] + x[1::2]) // 2).astype(np.int16)


def upsample_8k_to_16k(pcm8: np.ndarray) -> np.ndarray:
    """Linear upsample 8→16 kHz for mixing with 16 k paths if needed."""
    if len(pcm8) == 0:
        return pcm8
    x = pcm8.astype(np.int32)
    out = np.empty(len(x) * 2, dtype=np.int16)
    out[0::2] = pcm8
    out[1::2] = ((x + np.roll(x, -1)) // 2).astype(np.int16)
    out[-1] = pcm8[-1]
    return out
