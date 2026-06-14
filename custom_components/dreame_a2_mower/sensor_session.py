"""Re-export shim — session-sensor entities relocated to ``entities/sensor/session.py``.

Packaged under ``entities/`` (Phase 3c, 2026-06-14). Preserves the old import
path; new code should import from ``.entities.sensor.session`` directly.
"""
from __future__ import annotations

from .entities.sensor.session import *  # noqa: F401,F403
