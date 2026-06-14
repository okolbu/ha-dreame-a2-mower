"""Backward-compat shim — the implementation moved into the map_render package.

`infer_mow_direction`, `next_direction`, the pattern-mode constants, and
`MIN_SEGMENT_M` now live in `map_render/direction.py` (P3a frame untangle,
2026-06-14). This re-export keeps the old import paths
(`from ._render_direction import ...`) working for tests and the external
consumer `coordinator/_lidar_oss.py`; the bodies are unchanged.
"""
from __future__ import annotations

from .map_render.direction import (
    MIN_SEGMENT_M,
    MOWING_PATTERN_CHEQUER,
    MOWING_PATTERN_CRISSCROSS,
    MOWING_PATTERN_STRIPED,
    infer_mow_direction,
    next_direction,
)

__all__ = [
    "MIN_SEGMENT_M",
    "MOWING_PATTERN_CHEQUER",
    "MOWING_PATTERN_CRISSCROSS",
    "MOWING_PATTERN_STRIPED",
    "infer_mow_direction",
    "next_direction",
]
