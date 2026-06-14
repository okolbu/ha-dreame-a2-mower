"""Re-export shim — per-map settings select entities relocated to ``entities/select/map_settings.py``.

Packaged under ``entities/`` (Phase 3c, 2026-06-14). Preserves the old import
path; new code should import from ``.entities.select.map_settings`` directly.
"""
from __future__ import annotations

from .entities.select.map_settings import *  # noqa: F401,F403
