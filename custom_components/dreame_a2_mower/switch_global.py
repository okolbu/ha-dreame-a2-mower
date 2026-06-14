"""Re-export shim — global switch entities relocated to ``entities/switch/global_.py``.

Packaged under ``entities/`` (Phase 3c, 2026-06-14). Preserves the old import
path; new code should import from ``.entities.switch.global_`` directly.
"""
from __future__ import annotations

from .entities.switch.global_ import *  # noqa: F401,F403
