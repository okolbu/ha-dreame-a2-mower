"""Re-export shim — camera-map entities relocated to ``camera/map.py``.

The camera entity layer was packaged under ``camera/`` (Phase 3c, 2026-06-14).
This 1-line re-export preserves the old import path
(``from ._camera_map import DreameA2MapCamera``) for the deep test imports
(``test_card_contract``, ``test_editable_objects_attr``). New code should import
from ``.camera.map`` directly.
"""
from __future__ import annotations

from .camera.map import (  # noqa: F401
    MAP_ATTR_SCHEMA_VERSION,
    DreameA2MapCamera,
    DreameA2PerMapCamera,
    DreameA2WorkLogCamera,
)

__all__ = [
    "MAP_ATTR_SCHEMA_VERSION",
    "DreameA2MapCamera",
    "DreameA2PerMapCamera",
    "DreameA2WorkLogCamera",
]
