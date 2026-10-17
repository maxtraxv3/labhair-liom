"""Persistent user settings for Labhair-liom Chat client.

Stores preferences in a JSON file alongside the executable.
All settings have sensible defaults and are loaded on startup.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


_DEFAULTS: dict[str, Any] = {
    # Audio
    "input_device": None,        # int | None — mic device index
    "output_device": None,       # int | None — speaker device index
    "input_volume": 1.0,         # 0.0 – 2.0 mic amplification
    "output_volume": 1.0,        # 0.0 – 2.0 speaker volume

    # Video
    "camera_index": 0,           # int — camera device index
    "screen_monitor": 0,         # int — monitor index for screen share (0 = all)

    # Notifications
    "notification_sound": True,       # play a sound on new message
    "notification_volume": 0.5,       # 0.0 – 1.0 notification volume
    "notification_dm_sound": True,    # play a sound on new DM
    "notification_sound_file": "",    # custom sound file path (empty = default beep)

    # UI
    "show_notifications": True,       # show desktop/system notifications
    "sound_on_join": False,           # play sound when someone joins
    "sound_on_leave": False,          # play sound when someone leaves

    # Connection (last-used, auto-filled)
    "last_host": "",
    "last_port": 9473,
    "last_room": "demo",
    "last_username": "",
}


def _config_dir() -> Path:
    """Return the platform-appropriate config directory."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "labhairliom"


class Settings:
    """Client-side persistent settings backed by a JSON file."""

    def __init__(self, filename: str = "settings.json") -> None:
        self._dir = _config_dir()
        self._path = self._dir / filename
        self._data: dict[str, Any] = dict(_DEFAULTS)
        self.load()

    def load(self) -> None:
        """Load settings from disk, keeping defaults for missing keys."""
        try:
            if self._path.exists():
                with open(self._path, "r") as f:
                    stored = json.load(f)
                self._data.update(stored)
        except Exception:
            pass  # keep defaults on any error

    def save(self) -> None:
        """Persist current settings to disk."""
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w") as f:
                json.dump(self._data, f, indent=2)
        except Exception:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def reset(self) -> None:
        """Reset all settings to defaults."""
        self._data = dict(_DEFAULTS)

    # ── Typed accessors ────────────────────────────────────────────

    @property
    def input_device(self) -> int | None:
        v = self._data["input_device"]
        return int(v) if v is not None else None

    @input_device.setter
    def input_device(self, v: int | None) -> None:
        self._data["input_device"] = v

    @property
    def output_device(self) -> int | None:
        v = self._data["output_device"]
        return int(v) if v is not None else None

    @output_device.setter
    def output_device(self, v: int | None) -> None:
        self._data["output_device"] = v

    @property
    def camera_index(self) -> int:
        return int(self._data.get("camera_index", 0))

    @camera_index.setter
    def camera_index(self, v: int) -> None:
        self._data["camera_index"] = v

    @property
    def screen_monitor(self) -> int:
        return int(self._data.get("screen_monitor", 0))

    @screen_monitor.setter
    def screen_monitor(self, v: int) -> None:
        self._data["screen_monitor"] = v

    @property
    def notification_sound(self) -> bool:
        return bool(self._data["notification_sound"])

    @notification_sound.setter
    def notification_sound(self, v: bool) -> None:
        self._data["notification_sound"] = v

    @property
    def notification_dm_sound(self) -> bool:
        return bool(self._data["notification_dm_sound"])

    @notification_dm_sound.setter
    def notification_dm_sound(self, v: bool) -> None:
        self._data["notification_dm_sound"] = v

    @property
    def notification_volume(self) -> float:
        return max(0.0, min(1.0, float(self._data["notification_volume"])))

    @notification_volume.setter
    def notification_volume(self, v: float) -> None:
        self._data["notification_volume"] = max(0.0, min(1.0, float(v)))

    @property
    def input_volume(self) -> float:
        return max(0.0, min(2.0, float(self._data["input_volume"])))

    @input_volume.setter
    def input_volume(self, v: float) -> None:
        self._data["input_volume"] = max(0.0, min(2.0, float(v)))

    @property
    def output_volume(self) -> float:
        return max(0.0, min(2.0, float(self._data["output_volume"])))

    @output_volume.setter
    def output_volume(self, v: float) -> None:
        self._data["output_volume"] = max(0.0, min(2.0, float(v)))

    @property
    def notification_sound_file(self) -> str:
        return str(self._data.get("notification_sound_file", ""))

    @notification_sound_file.setter
    def notification_sound_file(self, v: str) -> None:
        self._data["notification_sound_file"] = v

    @property
    def show_notifications(self) -> bool:
        return bool(self._data.get("show_notifications", True))

    @show_notifications.setter
    def show_notifications(self, v: bool) -> None:
        self._data["show_notifications"] = v

    @property
    def sound_on_join(self) -> bool:
        return bool(self._data.get("sound_on_join", False))

    @sound_on_join.setter
    def sound_on_join(self, v: bool) -> None:
        self._data["sound_on_join"] = v

    @property
    def sound_on_leave(self) -> bool:
        return bool(self._data.get("sound_on_leave", False))

    @sound_on_leave.setter
    def sound_on_leave(self, v: bool) -> None:
        self._data["sound_on_leave"] = v

    @property
    def last_host(self) -> str:
        return str(self._data.get("last_host", ""))

    @last_host.setter
    def last_host(self, v: str) -> None:
        self._data["last_host"] = v

    @property
    def last_port(self) -> int:
        return int(self._data.get("last_port", 9473))

    @last_port.setter
    def last_port(self, v: int) -> None:
        self._data["last_port"] = v

    @property
    def last_room(self) -> str:
        return str(self._data.get("last_room", "demo"))

    @last_room.setter
    def last_room(self, v: str) -> None:
        self._data["last_room"] = v

    @property
    def last_username(self) -> str:
        return str(self._data.get("last_username", ""))

    @last_username.setter
    def last_username(self, v: str) -> None:
        self._data["last_username"] = v
