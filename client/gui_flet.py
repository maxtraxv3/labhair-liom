"""Flet GUI entry point for Labhair-liom.

Usage:
    python client/gui_flet.py [--host HOST] [--port PORT]

This replaces the tkinter GUI with a modern Flet/Flutter-based interface.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to path so "client" package is importable
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import flet as ft


def main():
    parser = argparse.ArgumentParser(description="Labhair-liom Flet GUI")
    parser.add_argument("--host", default="127.0.0.1", help="Relay host")
    parser.add_argument("--port", type=int, default=9473, help="Relay port")
    parser.add_argument("--room", default="lobby", help="Room name")
    parser.add_argument("--user", default="user", help="Display name")
    parser.add_argument("--tls", action="store_true", help="Connect via TLS")
    parser.add_argument("--no-verify", action="store_true", help="Skip TLS certificate verification")
    parser.add_argument("--gui", action="store_true", default=True, help="Use Flet GUI")
    args = parser.parse_args()

    def run_app(page: ft.Page):
        from client.main import ChatClient
        from client.flet_app.app import LabhairLiomApp

        client = ChatClient(
            host=args.host,
            port=args.port,
            room=args.room,
            user_id="",
            display=args.user,
            voice=False,
            video=False,
            screen=False,
            cam=0,
            monitor=0,
            ascii_w=120,
            ascii_h=40,
            ascii_fps=6,
            screen_w=1920,
            screen_h=1080,
            screen_fps=30,
            mode=5,
            pixel=False,
            tls=args.tls,
            tls_no_verify=args.no_verify,
        )

        LabhairLiomApp(page, client)

    ft.app(target=run_app)


if __name__ == "__main__":
    main()
