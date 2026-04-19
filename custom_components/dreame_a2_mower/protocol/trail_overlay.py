"""Stateful path-overlay layer for the camera PNG.

The camera serves a static PNG for the lawn + exclusion + dock base.
The mower's historical trail is *not* in that image — Lovelace map
cards like ``xiaomi-vacuum-map-card`` don't render the ``path``
attribute, and re-rendering the full map on every ``s1p4`` arrival
would be wasteful (5 s cadence × ~200 ms re-render).

Design: three in-memory surfaces, incrementally maintained.

- **Base layer** — the map PNG as the renderer already produces it.
  Refreshed rarely.
- **Trail layer** — an RGBA image the same size. We ``ImageDraw.line``
  one segment onto it per ``s1p4`` arrival (≈1 ms) or repaint the
  whole thing once on replay.
- **Composed cache** — the final PNG bytes. Recomputed only when
  either layer's version counter bumps, so camera fetches at 4 Hz
  don't trigger more work than the underlying data actually changed.

Coordinate convention: path points / obstacle polygons / dock position
arrive in **metres** in the mower / charger-relative frame (same shape
as :class:`live_map.LiveMapState`). Calibration points (from the base
renderer) are ``{mower:{x,y}, map:{x,y}}`` tuples — mower coords are
**mm**, map coords are **pixels**. We scale × 1000 internally.
"""

from __future__ import annotations

import io
from typing import Iterable, Sequence

from PIL import Image, ImageDraw


TRAIL_COLOR = (220, 50, 50, 220)
TRAIL_WIDTH_PX = 4
DOCK_RADIUS_PX = 14
DOCK_COLOR = (50, 180, 50, 255)
DOCK_OUTLINE = (255, 255, 255, 255)
OBSTACLE_COLOR = (255, 140, 0, 150)
OBSTACLE_OUTLINE = (160, 60, 0, 220)


def _affine_from_calibration(
    calibration_points: Sequence[dict],
) -> tuple[float, float, float, float, float, float]:
    if not isinstance(calibration_points, (list, tuple)) or len(calibration_points) < 3:
        raise ValueError("need at least three calibration points")
    rows = []
    for cp in calibration_points[:3]:
        try:
            rows.append((
                float(cp["mower"]["x"]),
                float(cp["mower"]["y"]),
                float(cp["map"]["x"]),
                float(cp["map"]["y"]),
            ))
        except (TypeError, KeyError, ValueError) as ex:
            raise ValueError(f"malformed calibration point: {cp!r} ({ex})") from ex
    (x0, y0, u0, v0), (x1, y1, u1, v1), (x2, y2, u2, v2) = rows
    det = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    if abs(det) < 1e-9:
        raise ValueError("calibration points are colinear — cannot invert")
    a = ((u1 - u0) * (y2 - y0) - (u2 - u0) * (y1 - y0)) / det
    b = ((x1 - x0) * (u2 - u0) - (x2 - x0) * (u1 - u0)) / det
    c = ((v1 - v0) * (y2 - y0) - (v2 - v0) * (y1 - y0)) / det
    d = ((x1 - x0) * (v2 - v0) - (x2 - x0) * (v1 - v0)) / det
    tx = u0 - a * x0 - b * y0
    ty = v0 - c * x0 - d * y0
    return a, b, c, d, tx, ty


class TrailLayer:
    """Incremental trail + dock + obstacle overlay, composited on demand.

    Same instance serves live and replay use cases. Live appends one
    point per tick (``extend_live``); replay repopulates the whole
    layer in one call (``reset_to_session``).

    Lifecycle:
        layer = TrailLayer(base_size=(2660, 2916), calibration=[...])
        layer.extend_live([1.0, 2.0])              # per s1p4 tick
        layer.set_dock([0.0, 0.0])                 # once on map rebuild
        layer.set_obstacles([[...], [...]])        # once per replay / new session
        png = layer.compose(base_png_bytes)        # per camera fetch
    """

    def __init__(
        self,
        base_size: tuple[int, int],
        calibration: Sequence[dict],
        trail_color: tuple[int, int, int, int] = TRAIL_COLOR,
        trail_width_px: int = TRAIL_WIDTH_PX,
        x_reflect_mm: float | None = None,
        y_reflect_mm: float | None = None,
    ) -> None:
        """``x_reflect_mm`` / ``y_reflect_mm`` — when supplied, reflect
        each input mower-mm coordinate through the given value before
        applying the calibration affine. Use this for the g2408's
        cloud-built map where the lawn mask drawn by the renderer
        lives in an X+Y-flipped frame relative to the calibration's
        naive `(x - bx1)/grid` transform. Set to `bx1 + bx2` / `by1 + by2`
        respectively to align the trail with the lawn.
        """
        self._size = base_size
        self._aff = _affine_from_calibration(calibration)
        self._x_reflect_mm = x_reflect_mm
        self._y_reflect_mm = y_reflect_mm
        self._trail_color = trail_color
        self._trail_width = trail_width_px
        self._trail = Image.new("RGBA", base_size, (0, 0, 0, 0))
        self._draw = ImageDraw.Draw(self._trail, "RGBA")
        self._last_point: tuple[float, float] | None = None
        self._dock: tuple[float, float] | None = None
        self._obstacle_polys: list[list[tuple[float, float]]] = []
        # Version bumped on every mutation; used by callers to cache
        # composed PNG bytes.
        self.version: int = 0

    # ------------------- live path -------------------

    def extend_live(self, point_m: Sequence[float]) -> None:
        """Draw a segment from the previous live point to ``point_m``.

        Call this once per ``s1p4`` arrival. The first call after a
        reset / new session only remembers the point without drawing
        (there's no previous point to connect to).
        """
        if point_m is None or len(point_m) < 2:
            return
        px = self._m_to_px(float(point_m[0]), float(point_m[1]))
        if self._last_point is not None:
            self._draw.line(
                [self._last_point, px],
                fill=self._trail_color,
                width=self._trail_width,
                joint="curve",
            )
            self.version += 1
        self._last_point = px

    # ------------------- replay -------------------

    def reset(self) -> None:
        """Clear the trail + dock + obstacles; bump version."""
        self._trail = Image.new("RGBA", self._size, (0, 0, 0, 0))
        self._draw = ImageDraw.Draw(self._trail, "RGBA")
        self._last_point = None
        self._obstacle_polys = []
        self._dock = None
        self.version += 1

    def reset_to_session(
        self,
        completed_track: Iterable[Iterable[Sequence[float]]] | None = None,
        path: Iterable[Sequence[float]] | None = None,
        obstacle_polygons: Iterable[Iterable[Sequence[float]]] | None = None,
        dock_position: Sequence[float] | None = None,
    ) -> None:
        """Repaint the layer from a complete session snapshot (replay)."""
        self.reset()
        if completed_track:
            for seg in completed_track:
                pts = [self._m_to_px(p[0], p[1]) for p in seg if len(p) >= 2]
                if len(pts) >= 2:
                    self._draw.line(
                        pts, fill=self._trail_color, width=self._trail_width, joint="curve"
                    )
        if path:
            pts = [self._m_to_px(p[0], p[1]) for p in path if len(p) >= 2]
            if len(pts) >= 2:
                self._draw.line(
                    pts, fill=self._trail_color, width=self._trail_width, joint="curve"
                )
            if pts:
                self._last_point = pts[-1]
        if obstacle_polygons:
            self.set_obstacles(obstacle_polygons)
        if dock_position is not None:
            self.set_dock(dock_position)
        self.version += 1

    # ------------------- static layers -------------------

    def set_dock(self, dock_m: Sequence[float] | None) -> None:
        if not dock_m or len(dock_m) < 2:
            self._dock = None
        else:
            self._dock = self._m_to_px(float(dock_m[0]), float(dock_m[1]))
        self.version += 1

    def set_obstacles(
        self, polygons: Iterable[Iterable[Sequence[float]]] | None
    ) -> None:
        self._obstacle_polys = []
        if polygons:
            for poly in polygons:
                pts = [self._m_to_px(p[0], p[1]) for p in poly if len(p) >= 2]
                if len(pts) >= 3:
                    self._obstacle_polys.append(pts)
        self.version += 1

    # ------------------- compose -------------------

    def compose(self, base_png: bytes) -> bytes:
        """Composite base + trail + obstacles + dock into a PNG."""
        base = Image.open(io.BytesIO(base_png)).convert("RGBA")
        if base.size != self._size:
            # Base came out a different size than we sized the trail for
            # (e.g. the renderer applied a different crop). Resize the
            # trail to match so the compose still works, even though the
            # geometry will be slightly off until the next reset.
            self._trail = self._trail.resize(base.size, Image.Resampling.BILINEAR)
            self._size = base.size

        # Single alpha-composite per layer — `paste` with mask would
        # dim the colours a second time (trail alpha gets multiplied
        # by overlay alpha), so we start from the trail image directly
        # and draw obstacles + dock onto IT, then compose once.
        overlay = self._trail.copy()
        draw = ImageDraw.Draw(overlay, "RGBA")

        for poly in self._obstacle_polys:
            draw.polygon(poly, fill=OBSTACLE_COLOR, outline=OBSTACLE_OUTLINE)

        if self._dock is not None:
            cx, cy = self._dock
            r = DOCK_RADIUS_PX
            draw.ellipse(
                (cx - r, cy - r, cx + r, cy + r),
                fill=DOCK_COLOR,
                outline=DOCK_OUTLINE,
                width=2,
            )

        composed = Image.alpha_composite(base, overlay)
        buf = io.BytesIO()
        composed.convert("RGB").save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    # ------------------- helpers -------------------

    def _m_to_px(self, x_m: float, y_m: float) -> tuple[float, float]:
        a, b, c, d, tx, ty = self._aff
        mm_x = x_m * 1000.0
        mm_y = y_m * 1000.0
        if self._x_reflect_mm is not None:
            mm_x = self._x_reflect_mm - mm_x
        if self._y_reflect_mm is not None:
            mm_y = self._y_reflect_mm - mm_y
        return (a * mm_x + b * mm_y + tx, c * mm_x + d * mm_y + ty)
