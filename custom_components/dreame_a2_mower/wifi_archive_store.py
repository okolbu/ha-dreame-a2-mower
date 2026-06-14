"""Re-export shim — WiFi archive store relocated to ``wifi/archive_store.py``.

Packaged under ``wifi/`` (Phase 3c, 2026-06-14). This re-export preserves the
old import path (``from .wifi_archive_store import WifiArchiveStore``) for the
~10 coordinator importers + the test suite. New code should import from
``.wifi.archive_store`` directly.
"""
from __future__ import annotations

from .wifi.archive_store import (  # noqa: F401
    WifiArchiveEntry,
    WifiArchiveStore,
)

__all__ = [
    "WifiArchiveEntry",
    "WifiArchiveStore",
]
