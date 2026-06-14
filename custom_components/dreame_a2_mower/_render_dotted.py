"""Backward-compat shim — the implementation moved into the map_render package.

`draw_dotted_polygon` now lives in `map_render/dotted.py` (P3a frame untangle,
2026-06-14). This re-export keeps the old import path
(`from ._render_dotted import draw_dotted_polygon`) working; the body is
unchanged.
"""
from __future__ import annotations

from .map_render.dotted import draw_dotted_polygon

__all__ = ["draw_dotted_polygon"]
