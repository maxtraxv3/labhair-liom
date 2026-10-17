#!/usr/bin/env python3
"""Build Windows .exe files using PyInstaller.

Usage (on Windows):
    pip install pyinstaller
    python build.py

Produces:
    dist/labhairliom-relay.exe   — relay server (console)
    dist/labhairliom-client.exe  — GUI client (no console)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(cmd: list[str], **kwargs) -> None:
    print(f"  {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT), **kwargs)
    if result.returncode != 0:
        print(f"FAILED (exit {result.returncode})", file=sys.stderr)
        sys.exit(result.returncode)


def build_relay() -> None:
    print("\n=== Building labhairliom-relay.exe ===")
    run([
        sys.executable, "-m", "PyInstaller",
        "--clean", "--noconfirm",
        "--onefile",
        "--name", "labhairliom-relay",
        "--console",
        "--hidden-import", "shared",
        "--hidden-import", "shared.protocol",
        "--hidden-import", "shared.crypto",
        "--hidden-import", "shared.upnp",
        "--hidden-import", "shared.database",
        "--hidden-import", "shared.auth",
        "--hidden-import", "server.thread_manager",
        "--hidden-import", "aiosqlite",
        "--hidden-import", "bcrypt",
        "--hidden-import", "miniupnpc",
        "--exclude-module", "PIL",
        "--exclude-module", "cv2",
        "--exclude-module", "numpy",
        "--exclude-module", "sounddevice",
        "--exclude-module", "mss",
        str(ROOT / "server" / "relay.py"),
    ])
    print("  -> dist/labhairliom-relay.exe")


def build_client() -> None:
    print("\n=== Building labhairliom-client.exe ===")
    run([
        sys.executable, "-m", "PyInstaller",
        "--clean", "--noconfirm",
        "--onefile",
        "--name", "labhairliom-client",
        "--windowed",
        "--hidden-import", "client",
        "--hidden-import", "client.gui",
        "--hidden-import", "client.main",
        "--hidden-import", "client.audio_io",
        "--hidden-import", "client.video_io",
        "--hidden-import", "client.screencap",
        "--hidden-import", "client.web_viewer",
        "--hidden-import", "shared",
        "--hidden-import", "shared.protocol",
        "--hidden-import", "shared.crypto",
        "--hidden-import", "shared.labhair_liom",
        "--hidden-import", "shared.adpcm",
        "--hidden-import", "shared.image_share",
        "--hidden-import", "shared.file_share",
        "--hidden-import", "shared.upnp",
        "--hidden-import", "shared.database",
        "--hidden-import", "shared.auth",
        "--hidden-import", "server.thread_manager",
        "--hidden-import", "aiosqlite",
        "--hidden-import", "bcrypt",
        "--hidden-import", "miniupnpc",
        "--hidden-import", "sounddevice",
        "--hidden-import", "numpy",
        "--hidden-import", "cv2",
        "--hidden-import", "PIL",
        "--hidden-import", "mss",
        str(ROOT / "client" / "main.py"),
    ])
    print("  -> dist/labhairliom-client.exe")


if __name__ == "__main__":
    if sys.platform == "win32":
        build_relay()
        build_client()
        print("\nDone! Executables are in dist/")
    else:
        print("This script is designed to run on Windows.")
        print("Use GitHub Actions or a Windows VM for cross-platform builds.")
        print("\nFor local Linux testing, you can still run the .spec files:")
        print("  pyinstaller labhairliom-relay.spec")
        print("  pyinstaller labhairliom-client.spec")
