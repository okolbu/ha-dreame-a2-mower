"""Re-export shim — the shared sensor base relocated to ``entities/sensor/base.py``.

Packaged under ``entities/`` (Phase 3c, 2026-06-14). Preserves the old import
path; new code should import from ``.entities.sensor.base`` directly.
"""
from __future__ import annotations

from .entities.sensor.base import *  # noqa: F401,F403
