"""Re-export shim — the shared select base relocated to ``entities/select/base.py``.

Packaged under ``entities/`` (Phase 3c, 2026-06-14). Preserves the old import
path; new code should import from ``.entities.select.base`` directly.
"""
from __future__ import annotations

from .entities.select.base import *  # noqa: F401,F403
