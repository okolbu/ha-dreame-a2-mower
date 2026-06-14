"""Backward-compat shim — the implementation moved into the map_render package.

`compute_stripe_overlay` now lives in `map_render/stripes.py` (P3a frame
untangle, 2026-06-14). This re-export keeps the old import path
(`from ._render_stripes import compute_stripe_overlay`) working for tests and
any external consumer; the function body is unchanged.
"""
from __future__ import annotations

from .map_render.stripes import compute_stripe_overlay

__all__ = ["compute_stripe_overlay"]
