"""Re-export shim — map-sensor entities relocated to ``entities/sensor/map.py``.

Packaged under ``entities/`` (Phase 3c, 2026-06-14). Preserves the old import
path; new code should import from ``.entities.sensor.map`` directly.
"""
from __future__ import annotations

from .entities.sensor.map import *  # noqa: F401,F403
