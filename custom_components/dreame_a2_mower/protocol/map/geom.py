"""Geometry helpers for cloud-map JSON (MAP.*) parsing.

The Dreame cloud stores some zones as axis-aligned polygons plus a
separate ``angle`` field (degrees) describing rotation around the
polygon centroid. Rendering without applying the rotation yields the
canonical "axis-aligned rectangle that's supposed to be at 30°" bug.

These helpers are pure — no imports from the HA runtime — so they're
straightforward to cover with unit tests.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

from .shapes import DECORATIVE_SHAPE_TYPES
from .types import CHARGER_OFFSET_MM


def _rotate_path_around_centroid(
    path: Iterable[dict], angle_deg: float | None
) -> list[dict]:
    """Return a new list of ``{"x", "y"}`` dicts rotated around the
    polygon centroid by ``angle_deg``.

    Pass-throughs:
    - ``angle_deg`` is ``None`` or ``0`` → returns the points unchanged
      (avoids float drift from a pointless rotate).
    - Empty or malformed path → returns it as-is.

    Rotation sense is the same as the Dreame app's rendering: positive
    angle is counter-clockwise in the cloud's X/Y frame.
    """
    pts = [p for p in path if isinstance(p, dict) and "x" in p and "y" in p]
    if not pts:
        return list(path)
    if not angle_deg:
        # Return a clean copy so callers can mutate freely.
        return [{"x": p["x"], "y": p["y"]} for p in pts]

    xs = [float(p["x"]) for p in pts]
    ys = [float(p["y"]) for p in pts]
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)

    theta = math.radians(float(angle_deg))
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)

    out: list[dict] = []
    for x, y in zip(xs, ys):
        dx = x - cx
        dy = y - cy
        # Standard rotation about centroid.
        rx = cx + dx * cos_t - dy * sin_t
        ry = cy + dx * sin_t + dy * cos_t
        out.append({"x": rx, "y": ry})
    return out


def rotate_zone_points(
    points: Sequence[tuple[float, float]],
    angle: float | None,
    shape_type: int | None,
) -> tuple[tuple[float, float], ...]:
    """Apply the app's per-centroid rotation to a :class:`Zone`'s RAW corners.

    This is the presentation-step half of the decode->render transform for
    polygonal zones: the decoder now stores ``Zone.points`` verbatim (raw cloud
    mm), and BOTH the canvas bbox derivation and the render draw call rotate
    them here so the drawn corners match the app's rendering handedness.

    - DECORATIVE ``shape_type`` (heart/cloud/…): the 2 points are raw
      axis-aligned bbox corners the app tessellates client-side — returned
      UN-rotated (the render stamps a silhouette rotated by ``angle`` itself).
    - ``angle`` ``None`` or ``0``: returned unchanged (no float drift).
    - otherwise: rotated by ``-angle`` around the centroid (the cloud's angle
      convention is mirror-flipped vs the app; see §4.1 of the geometry doc) —
      byte-identical to ``_rotate_path_around_centroid(path, -angle)``.
    """
    if shape_type in DECORATIVE_SHAPE_TYPES:
        return tuple((float(x), float(y)) for (x, y) in points)
    if not angle:
        return tuple((float(x), float(y)) for (x, y) in points)
    rotated = _rotate_path_around_centroid(
        [{"x": x, "y": y} for (x, y) in points], -float(angle)
    )
    return tuple((float(p["x"]), float(p["y"])) for p in rotated)


def derive_canvas(
    bx1: float,
    by1: float,
    bx2: float,
    by2: float,
    rotated_corner_sets: Iterable[Sequence[tuple[float, float]]],
    *,
    grid_size_mm: int,
) -> dict:
    """Expand the raw lawn bbox over every rotated zone corner and derive the
    canvas params (pure cloud-frame geometry — no pixel/render dependency).

    Returns a dict with ``bx1``/``by1``/``bx2``/``by2`` (expanded),
    ``width_px``/``height_px``, ``cloud_x_reflect``/``cloud_y_reflect``,
    ``dock_xy`` and ``boundary_polygon``. The render's ``build_projection``
    recomputes the identical values from the raw :class:`MapData`. See the
    STRUCTURAL-TRAP note in CLAUDE.md § "Decode->render zone frame contract".
    """
    bx1_exp, by1_exp, bx2_exp, by2_exp = bx1, by1, bx2, by2
    for corners in rotated_corner_sets:
        for (x, y) in corners:
            x = float(x)
            y = float(y)
            bx1_exp = min(bx1_exp, x)
            by1_exp = min(by1_exp, y)
            bx2_exp = max(bx2_exp, x)
            by2_exp = max(by2_exp, y)

    width_px = max(1, int((bx2_exp - bx1_exp) / grid_size_mm) + 1)
    height_px = max(1, int((by2_exp - by1_exp) / grid_size_mm) + 1)

    dock_xy: tuple[float, float] | None
    if bx2_exp != bx1_exp or by2_exp != by1_exp:
        dock_xy = (float(CHARGER_OFFSET_MM), 0.0)
    else:
        dock_xy = None

    return {
        "bx1": bx1_exp,
        "by1": by1_exp,
        "bx2": bx2_exp,
        "by2": by2_exp,
        "width_px": width_px,
        "height_px": height_px,
        "cloud_x_reflect": float(bx1_exp + bx2_exp),
        "cloud_y_reflect": float(by1_exp + by2_exp),
        "dock_xy": dock_xy,
        "boundary_polygon": (
            (bx1_exp, by1_exp),
            (bx2_exp, by1_exp),
            (bx2_exp, by2_exp),
            (bx1_exp, by2_exp),
        ),
    }
