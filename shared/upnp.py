"""UPnP IGD port mapping helper.

Uses miniupnpc to discover a NAT gateway and create temporary TCP port
mappings.  All operations are wrapped in try/except so failures are
non-fatal — the application works fine without UPnP, it just won't be
reachable from the internet automatically.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Optional

log = logging.getLogger(__name__)


class PortMapping:
    """Represents an active UPnP port mapping that cleans up on close."""

    def __init__(self, ext_port: int, int_port: int, description: str = "Labhair-liom") -> None:
        self.ext_port = ext_port
        self.int_port = int_port
        self.description = description
        self._upnp: Optional[object] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    @property
    def lan_ip(self) -> str:
        if self._upnp is not None:
            return self._upnp.lanaddr
        return _get_lan_ip()

    @property
    def external_ip(self) -> Optional[str]:
        if self._upnp is not None:
            try:
                return self._upnp.externalipaddress()
            except Exception:
                pass
        return None

    def cleanup(self) -> None:
        """Remove the port mapping and stop the refresh thread."""
        self._running = False
        if self._upnp is not None:
            try:
                self._upnp.deleteportmapping(self.ext_port, "TCP")
                log.info("UPnP port mapping %d/TCP removed", self.ext_port)
            except Exception as exc:
                log.debug("UPnP cleanup failed: %s", exc)
            self._upnp = None


def setup_port_mapping(
    ext_port: int,
    int_port: int | None = None,
    description: str = "Labhair-liom",
    refresh_interval: int = 1200,
) -> PortMapping | None:
    """Try to create a UPnP TCP port mapping.

    Returns a PortMapping on success (call .cleanup() when done), or
    None if UPnP is unavailable.  A background thread periodically
    refreshes the mapping so it doesn't expire.
    """
    if int_port is None:
        int_port = ext_port

    try:
        import miniupnpc
    except ImportError:
        log.debug("miniupnpc not installed, skipping UPnP")
        return None

    upnp = miniupnpc.UPnP()
    try:
        upnp.discoverdelay = 3000
        n = upnp.discover()
        if n <= 0:
            log.debug("no UPnP devices found")
            return None
        result = upnp.selectigd()
        if result != "OK":
            log.debug("UPnP selectigd failed: %s", result)
            return None
        upnp.addportmapping(ext_port, "TCP", upnp.lanaddr, int_port, description, "")
        log.info(
            "UPnP mapped external %d/TCP -> %s:%d (%s)",
            ext_port, upnp.lanaddr, int_port, description,
        )
    except Exception as exc:
        log.debug("UPnP setup failed: %s", exc)
        return None

    mapping = PortMapping(ext_port, int_port, description)
    mapping._upnp = upnp

    def _refresh_loop() -> None:
        while mapping._running:
            time.sleep(refresh_interval)
            if not mapping._running:
                break
            try:
                upnp.addportmapping(
                    ext_port, "TCP", upnp.lanaddr, int_port, description, "",
                )
                log.debug("UPnP mapping %d/TCP refreshed", ext_port)
            except Exception as exc:
                log.warning("UPnP refresh failed: %s", exc)
                break

    mapping._running = True
    mapping._thread = threading.Thread(target=_refresh_loop, daemon=True, name="upnp-refresh")
    mapping._thread.start()
    return mapping


def _get_lan_ip() -> str:
    """Best-effort LAN IP detection (no UPnP)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"
