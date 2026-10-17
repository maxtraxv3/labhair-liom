# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Labhair-liom GUI client."""

import os
ROOT = os.path.dirname(os.path.abspath(SPECPATH))

a = Analysis(
    [os.path.join(ROOT, "client", "main.py")],
    pathex=[ROOT],
    datas=[],
    hiddenimports=[
        "client",
        "client.gui",
        "client.main",
        "client.audio_io",
        "client.video_io",
        "client.screencap",
        "client.web_viewer",
        "shared",
        "shared.protocol",
        "shared.crypto",
        "shared.labhair_liom",
        "shared.adpcm",
        "shared.image_share",
        "shared.file_share",
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
        "sounddevice",
        "numpy",
        "cv2",
        "PIL",
        "mss",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="labhairliom-client",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,
)
