"""Labhair-liom — line-oriented ASCII video format for E2E chat.

Labhair-liom streams grayscale (or optional ANSI-color) frames as plain UTF-8
text lines so they can be rendered in any terminal without a pixel pipeline
on the receiver.

Wire format (UTF-8 text inside the encrypted VIDEO payload):

    LABHAIR-LIOM/1.0
    W:<cols> H:<rows> FPS:<n> SEQ:<u32> TS:<ms> FLAGS:<hex>
    <row 0>
    <row 1>
    ...
    <row H-1>
    .

Each data row is exactly W characters from the luminance ramp. The frame
terminates with a single '.' line.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

# Classic 70-char ramp (dark → bright); truncated variants work too
RAMP = np.array(list(" .'`^\",:;Il!i><~+_-?][}{1)(|\\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$"))
RAMP_SIMPLE = np.array(list(" .:-=+*#%@"))

# FLAGS bits in the Labhair-liom header
FLAG_CAMERA = 0x01
FLAG_SCREEN = 0x02
FLAG_REGION = 0x04  # screen region crop (not full monitor)


def source_from_flags(flags: int) -> str:
    if flags & FLAG_SCREEN:
        return "screen"
    if flags & FLAG_CAMERA:
        return "camera"
    return "video"


@dataclass
class LabhairLiomFrame:
    width: int
    height: int
    fps: int
    seq: int
    timestamp_ms: int
    flags: int
    rows: list[str]
    source: str = "video"
    img_b64: str = ""  # optional base64 JPEG for Canvas viewer

    def encode(self) -> bytes:
        header = (
            f"LABHAIR-LIOM/1.0\n"
            f"W:{self.width} H:{self.height} FPS:{self.fps} "
            f"SEQ:{self.seq} TS:{self.timestamp_ms} FLAGS:{self.flags:x} "
            f"SRC:{self.source}"
        )
        if self.img_b64:
            header += f" IMG:{self.img_b64}"
        header += "\n"
        body = "\n".join(self.rows)
        return (header + body + "\n.\n").encode("utf-8")

    @classmethod
    def decode(cls, data: bytes) -> LabhairLiomFrame:
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()
        if not lines or not lines[0].startswith("LABHAIR-LIOM/"):
            raise ValueError("not a Labhair-liom frame")
        if len(lines) < 2:
            raise ValueError("missing Labhair-liom header")
        meta = {}
        for tok in lines[1].split():
            if ":" in tok:
                k, v = tok.split(":", 1)
                meta[k] = v
        width = int(meta.get("W", "0"))
        height = int(meta.get("H", "0"))
        fps = int(meta.get("FPS", "10"))
        seq = int(meta.get("SEQ", "0"))
        ts = int(meta.get("TS", "0"))
        flags = int(meta.get("FLAGS", "0"), 16)
        source = meta.get("SRC") or source_from_flags(flags)
        img_b64 = meta.get("IMG", "")

        rows: list[str] = []
        for line in lines[2:]:
            if line == ".":
                break
            rows.append(line[:width].ljust(width) if width else line)
        if height and len(rows) < height:
            rows.extend([" " * width] * (height - len(rows)))
        elif height and len(rows) > height:
            rows = rows[:height]
        return cls(width, height, fps, seq, ts, flags, rows, source=source, img_b64=img_b64)

    def render(self) -> str:
        return "\n".join(self.rows)


class LabhairLiomEncoder:
    """Raster frame → Labhair-liom bytes."""

    def __init__(
        self,
        width: int = 80,
        height: int = 36,
        fps: int = 8,
        ramp: str | None = None,
        flags: int = 0,
        source: str | None = None,
    ) -> None:
        self.width = width
        self.height = height
        self.fps = fps
        self.flags = flags
        self.source = source or source_from_flags(flags)
        # denser ramp for screen share (UI text readability)
        if ramp:
            self.ramp = np.array(list(ramp))
        elif flags & FLAG_SCREEN:
            self.ramp = RAMP
        else:
            self.ramp = RAMP_SIMPLE
        self._seq = 0

    def _resize(self, arr: np.ndarray, w: int, h: int) -> np.ndarray:
        """Resize a 2D or 3D array to (h, w) using cv2 or Pillow fallback."""
        try:
            import cv2
            return cv2.resize(arr, (w, h), interpolation=cv2.INTER_AREA)
        except ImportError:
            from PIL import Image
            mode = "L" if arr.ndim == 2 else "RGB"
            img = Image.fromarray(arr, mode=mode)
            img = img.resize((w, h), Image.LANCZOS)
            return np.array(img)

    def encode_gray(self, gray: np.ndarray) -> bytes:
        """gray: HxW uint8 or float image (any size — will be resized)."""
        if gray.dtype != np.uint8:
            g = np.clip(gray, 0, 255).astype(np.uint8)
        else:
            g = gray
        if g.ndim == 3:
            g = np.mean(g[:, :, :3], axis=2).astype(np.uint8)
        resized = self._resize(g, self.width, self.height)
        # Contrast stretch with percentile clipping
        lo, hi = np.percentile(resized, [2, 98] if (self.flags & FLAG_SCREEN) else [5, 95])
        if hi <= lo:
            hi = lo + 1
        norm = np.clip((resized.astype(np.float32) - lo) / (hi - lo), 0, 1)
        # Gamma correction (0.45) brightens midtones for better ASCII contrast
        norm = np.power(norm, 0.45)
        idx = (norm * (len(self.ramp) - 1)).astype(np.int32)
        chars = self.ramp[idx]
        rows = ["".join(row.tolist()) for row in chars]
        fr = LabhairLiomFrame(
            width=self.width,
            height=self.height,
            fps=self.fps,
            seq=self._seq,
            timestamp_ms=int(time.time() * 1000) & 0xFFFFFFFF,
            flags=self.flags,
            rows=rows,
            source=self.source,
        )
        self._seq = (self._seq + 1) & 0xFFFFFFFF
        return fr.encode()

    def encode_color(self, frame: np.ndarray, use_blocks: bool = False, img_b64: str = "",
                     quantize_bits: int = 2, rows_out: list | None = None) -> bytes:
        """frame: HxWxC uint8 image (BGR from OpenCV, or RGB).

        When use_blocks=True, uses half-block characters (▀) with ANSI
        foreground+background colors to pack 2 vertical pixels per cell,
        effectively doubling vertical resolution for a pixel-art look.
        """
        # Ensure we have a 3-channel color image
        if frame.ndim == 2:
            rgb = np.stack([frame, frame, frame], axis=2)
            gray = frame
        else:
            # Detect BGR vs RGB by checking if we can import cv2
            try:
                import cv2
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            except ImportError:
                # No cv2 — assume RGB input (Android cameras give RGB)
                rgb = frame
                gray = np.mean(frame[:, :, :3], axis=2).astype(np.uint8)

        if use_blocks:
            virt_h = self.height * 2
            resized_rgb = self._resize(rgb, self.width, virt_h)
            resized_gray = self._resize(gray, self.width, virt_h)
        else:
            resized_rgb = self._resize(rgb, self.width, self.height)
            resized_gray = self._resize(gray, self.width, self.height)

        # Contrast stretch
        lo, hi = np.percentile(resized_gray, [2, 98] if (self.flags & FLAG_SCREEN) else [5, 95])
        if hi <= lo:
            hi = lo + 1
        norm = np.clip((resized_gray.astype(np.float32) - lo) / (hi - lo), 0, 1)
        # Gamma correction brightens midtones for better visual contrast
        norm = np.power(norm, 0.45)
        idx = (norm * (len(self.ramp) - 1)).astype(np.int32)
        chars = self.ramp[idx]

        # Also apply gamma to the RGB data so colors match the brighter mapping
        color_norm = np.clip((resized_gray.astype(np.float32) - lo) / (hi - lo), 0, 1)
        color_gamma = np.power(color_norm, 0.45)
        # Brighten RGB proportionally to the gamma correction
        ratio = np.where(color_norm > 0, color_gamma / np.maximum(color_norm, 1e-6), 1.0)
        ratio = np.clip(ratio, 0.8, 1.4)  # conservative boost to avoid clipping
        resized_rgb = np.clip(resized_rgb.astype(np.float32) * ratio[:,:,np.newaxis], 0, 255).astype(np.uint8)

        # Color quantization (upstream LABHAIR_LIOM technique): zero low bits so flat
        # color regions share one ANSI code across many cells — smaller payloads,
        # less string-building CPU. 64 levels/channel is visually lossless.
        if quantize_bits:
            resized_rgb = (resized_rgb >> quantize_bits) << quantize_bits

        rows = []
        reset = "\033[0m"
        if use_blocks:
            # Half-block mode: pack 2 vertical pixels into one ▀ character.
            # Top pixel → foreground, bottom pixel → background.
            # RLE: emit a new ANSI code only when the fg/bg pair changes (borrowed
            # from upstream LABHAIR_LIOM) — huge saving on UI screens with flat areas.
            for y in range(0, virt_h, 2):
                row: list[str] = []
                prev: tuple | None = None
                for x in range(self.width):
                    r1, g1, b1 = resized_rgb[y, x]
                    if y + 1 < virt_h:
                        r2, g2, b2 = resized_rgb[y + 1, x]
                    else:
                        r2 = g2 = b2 = 0
                    key = (r1, g1, b1, r2, g2, b2)
                    if key != prev:
                        row.append(f"\033[38;2;{r1};{g1};{b1};48;2;{r2};{g2};{b2}m")
                        prev = key
                    row.append("▀")
                row.append(reset)
                rows.append("".join(row))
        else:
            # Standard ASCII ramp mode with RLE color reuse
            for y in range(self.height):
                row: list[str] = []
                prev: tuple | None = None
                for x in range(self.width):
                    r, g, b = resized_rgb[y, x]
                    key = (r, g, b)
                    if key != prev:
                        row.append(f"\x1b[38;2;{r};{g};{b}m")
                        prev = key
                    row.append(chars[y, x])
                row.append(reset)
                rows.append("".join(row))

        if rows_out is not None:
            rows_out.append(tuple(rows))

        fr = LabhairLiomFrame(
            width=self.width,
            height=self.height,
            fps=self.fps,
            seq=self._seq,
            timestamp_ms=int(time.time() * 1000) & 0xFFFFFFFF,
            flags=self.flags,
            rows=rows,
            source=self.source,
            img_b64=img_b64,
        )
        self._seq = (self._seq + 1) & 0xFFFFFFFF
        return fr.encode()


class LabhairLiomDecoder:
    """Labhair-liom bytes → terminal string."""

    def decode(self, data: bytes) -> LabhairLiomFrame:
        return LabhairLiomFrame.decode(data)
