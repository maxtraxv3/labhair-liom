# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Labhair-liom relay server."""

import os
ROOT = os.path.dirname(os.path.abspath(SPECPATH))

a = Analysis(
    [os.path.join(ROOT, "server", "relay.py")],
    pathex=[ROOT],
    datas=[],
    hiddenimports=[
        "shared",
        "shared.protocol",
        "shared.crypto",
        "shared.upnp",
        "shared.database",
        "shared.auth",
        "shared.encryption",
        "shared.settings",
        "server.auth_handler",
        "server.server_manager",
        "server.channel_manager",
        "server.role_manager",
        "server.message_manager",
        "server.dm_manager",
        "server.friend_manager",
        "server.member_manager",
        "server.thread_manager",
        "aiosqlite",
        "bcrypt",
        "asyncpg",
        "miniupnpc",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["PIL", "cv2", "numpy", "sounddevice", "mss"],
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="labhairliom-relay",
    debug=False,
    strip=False,
    upx=False,
    console=True,
    icon=None,
)
