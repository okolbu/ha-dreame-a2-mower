"""Re-export shim — per-map switch entities relocated to ``entities/switch/map.py``.

Packaged under ``entities/`` (Phase 3c, 2026-06-14). Preserves the old import
path; new code should import from ``.entities.switch.map`` directly.
"""
from __future__ import annotations

from .entities.switch.map import *  # noqa: F401,F403
