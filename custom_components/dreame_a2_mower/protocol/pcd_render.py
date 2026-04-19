"""Top-down PNG renderer for LiDAR point clouds.

The firmware bakes a height-gradient into the ``rgb`` field (green at
ground, blue for walls, magenta/red for roof peaks), so a plain
top-down orthographic projection — colouring each pixel with the
highest-Z sample that landed there — produces a map that matches the
Dreame app's 3D view flattened to 2D.

Intentionally dependency-free beyond Pillow and NumPy (both already
required by the integration's map renderer).
"""

from __future__ import annotations

import io
from typing import Tuple

import numpy as np
from PIL import Image

from .pcd import PointCloud


def render_top_down(
    cloud: PointCloud,
    width: int = 512,
    height: int = 512,
    margin_px: int = 8,
    background: Tuple[int, int, int] = (0, 0, 0),
) -> bytes:
    """Render ``cloud`` as a top-down PNG and return the encoded bytes.

    Parameters
    ----------
    cloud
        Parsed point cloud. Must carry non-empty ``xyz`` and ``rgb``.
    width, height
        Output image dimensions in pixels.
    margin_px
        Padding around the cloud's bounding box. Keeps edge points off
        the literal edge.
    background
        RGB tuple painted on empty pixels (default black — matches the
        Dreame app's dark-themed 3D view).
    """
    xyz = cloud.xyz
    rgb = cloud.rgb
    if xyz.size == 0:
        return _encode_empty(width, height, background)

    x_min, x_max = float(xyz[:, 0].min()), float(xyz[:, 0].max())
    y_min, y_max = float(xyz[:, 1].min()), float(xyz[:, 1].max())

    span_x = max(x_max - x_min, 1e-6)
    span_y = max(y_max - y_min, 1e-6)

    usable_w = max(width - 2 * margin_px, 1)
    usable_h = max(height - 2 * margin_px, 1)
    # Aspect-preserving scale.
    scale = min(usable_w / span_x, usable_h / span_y)

    # Center the cloud in the canvas.
    content_w = span_x * scale
    content_h = span_y * scale
    offset_x = margin_px + (usable_w - content_w) * 0.5
    offset_y = margin_px + (usable_h - content_h) * 0.5

    px = ((xyz[:, 0] - x_min) * scale + offset_x).astype(np.int32)
    # Y pixels: image y grows downward; map world+Y to pixel-down so "north"
    # of the mower appears at the top of the image. The app uses the same
    # convention.
    py = ((y_max - xyz[:, 1]) * scale + offset_y).astype(np.int32)

    valid = (px >= 0) & (px < width) & (py >= 0) & (py < height)
    px = px[valid]
    py = py[valid]
    rgb_v = rgb[valid]
    z_v = xyz[:, 2][valid]

    # Paint order: draw points in ascending Z so the last-written pixel
    # at each location corresponds to the highest point (roof on top of
    # grass). Avoids a per-pixel depth buffer — sort is O(N log N) once.
    order = np.argsort(z_v, kind="stable")
    px = px[order]
    py = py[order]
    rgb_v = rgb_v[order]

    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    if background != (0, 0, 0):
        canvas[:] = background

    canvas[py, px] = rgb_v

    img = Image.fromarray(canvas, mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _encode_empty(width: int, height: int, background: Tuple[int, int, int]) -> bytes:
    img = Image.new("RGB", (width, height), background)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
