"""Re-export shim — global select entities relocated to ``entities/select/global_.py``.

Packaged under ``entities/`` (Phase 3c, 2026-06-14). Preserves the old import
path; new code should import from ``.entities.select.global_`` directly.
"""
from __future__ import annotations

from .entities.select.global_ import *  # noqa: F401,F403
