"""Re-export shim — WiFi heatmap PNG renderer relocated to ``wifi/map_render.py``.

Packaged under ``wifi/`` (Phase 3c, 2026-06-14). Preserves the old import path;
new code should import from ``.wifi.map_render`` directly.

Explicit re-export list (NOT ``import *``): ``_rssi_to_rgb`` is underscore-prefixed
(``*`` would not carry it) and ``test_wifi_gradient_contract`` imports it by name.
"""
from __future__ import annotations

from .wifi.map_render import (  # noqa: F401
    CELL_PX,
    render_wifi_map_png,
    _rssi_to_rgb,
)

__all__ = [
    "CELL_PX",
    "render_wifi_map_png",
    "_rssi_to_rgb",
]
