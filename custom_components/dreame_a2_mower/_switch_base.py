"""Re-export shim — the shared switch base relocated to ``entities/switch/base.py``.

Packaged under ``entities/`` (Phase 3c, 2026-06-14). Preserves the old import
path; new code should import from ``.entities.switch.base`` directly.
"""
from __future__ import annotations

from .entities.switch.base import *  # noqa: F401,F403
