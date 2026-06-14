"""Re-export shim — WiFi camera entities relocated to ``camera/wifi.py``.

Packaged under ``camera/`` (Phase 3c, 2026-06-14). Preserves the old import
path; new code should import from ``.camera.wifi`` directly.
"""
from __future__ import annotations

from .camera.wifi import (  # noqa: F401
    DreameA2WifiPerMapCamera,
    DreameA2WifiSelectedCamera,
)

__all__ = [
    "DreameA2WifiPerMapCamera",
    "DreameA2WifiSelectedCamera",
]
