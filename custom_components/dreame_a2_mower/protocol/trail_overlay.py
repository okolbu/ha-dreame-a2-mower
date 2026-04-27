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

import base64
import io
from typing import Iterable, Sequence

from PIL import Image, ImageDraw

# Lazy-loaded shared cache for the decoded mower top-down icon. The
# base renderer (DreameMowerMapRenderer.render_mower) uses the same
# asset; loading once at module level avoids repeated base64 decode
# + PIL image instantiation per camera fetch.
_MOWER_ICON_CACHE: dict[int, Image.Image] = {}


def _get_mower_icon(target_size_px: int) -> Image.Image:
    """Return a cached, square-resized RGBA Image of the mower icon.

    Decodes `MAP_ROBOT_LIDAR_IMAGE_DREAME_DARK` once at first call and
    keeps a per-size cache so the trail overlay can paste it on every
    compose without a fresh resize-and-decode per call."""
    if target_size_px not in _MOWER_ICON_CACHE:
        from ..dreame.resources import MAP_ROBOT_LIDAR_IMAGE_DREAME_DARK
        raw = Image.open(
            io.BytesIO(base64.b64decode(MAP_ROBOT_LIDAR_IMAGE_DREAME_DARK))
        ).convert("RGBA")
        _MOWER_ICON_CACHE[target_size_px] = raw.resize(
            (target_size_px, target_size_px),
            resample=Image.Resampling.LANCZOS,
        )
    return _MOWER_ICON_CACHE[target_size_px]


TRAIL_COLOR = (70, 70, 70, 220)             # dark grey — matches app
# Blades-up transit / return-to-dock — vivid medium blue, distinct
# from the dark grey mowing strokes so diagonal relocation lines
# read at a glance as "moving but not cutting". Earlier muted
# (90, 115, 170, 180) was too close to TRAIL_COLOR's value to
# distinguish on a low-contrast lawn background (field report
# 2026-04-22). Matches phase ∈ {1, 3} segments per s1p4 byte[8].
TRANSIT_COLOR = (50, 130, 230, 220)
TRAIL_WIDTH_PX = 4
# Live mower-position marker painted on the overlay at the end of the
# trail. The base renderer also paints a mower icon but only updates
# when the camera entity re-runs `update()` (heavy, throttled), so a
# live icon on the overlay — which recomposes on every telemetry frame
# via `extend_live` → `version++` — is the cheapest way to get real-
# time movement. Was previously a saturated orange-red dot; the user
# requested a larger icon (matching the dock's top-down photograph)
# 2026-04-27 for visibility on a busy lawn map.
MOWER_MARKER_ICON_SIZE_PX = 32     # noticeable but doesn't dominate
MOWER_MARKER_OUTLINE_RADIUS_PX = 18  # white halo behind the icon for contrast
# Live-trail pen-up threshold — consecutive s1p4 samples more than this
# far apart (metres) are treated as a session boundary / dock visit
# rather than a connected segment. Mower mow speed is <0.5 m/s over 5 s
# telemetry; 5 m leaves comfortable margin before ghost-segment noise.
LIVE_GAP_PENUP_M = 5.0
DOCK_RADIUS_PX = 14
DOCK_COLOR = (50, 180, 50, 255)
DOCK_OUTLINE = (255, 255, 255, 255)
OBSTACLE_COLOR = (90, 140, 230, 170)         # blue — matches app
OBSTACLE_OUTLINE = (40, 80, 200, 230)


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
        # Metres version of `_last_point` for the pen-up jump test.
        self._last_point_m: tuple[float, float] | None = None
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

        Jumps larger than ``LIVE_GAP_PENUP_M`` metres are treated as a
        pen-up / new segment (the mower can't physically travel that
        far in one 5-second telemetry interval, so it's a dock visit,
        a GPS correction, or a telemetry drop — drawing a straight
        line across would produce a ghost segment).

        ``point_m`` may be a 2-element ``[x, y]`` (legacy / no phase)
        or a 3-element ``[x, y, phase]`` where phase is the s1p4
        byte[8]. When phase is 1 (TRANSIT) or 3 (RETURNING) the
        segment renders in TRANSIT_COLOR — visually distinct from
        normal mowing strokes so the diagonal relocation lines
        characteristic of irregular lawns can be seen without
        being mistaken for cut area.
        """
        if point_m is None or len(point_m) < 2:
            return
        new_x_m = float(point_m[0])
        new_y_m = float(point_m[1])
        phase = int(point_m[2]) if len(point_m) >= 3 else None
        px = self._m_to_px(new_x_m, new_y_m)
        if self._last_point is not None and self._last_point_m is not None:
            dx = new_x_m - self._last_point_m[0]
            dy = new_y_m - self._last_point_m[1]
            if (dx * dx + dy * dy) ** 0.5 <= LIVE_GAP_PENUP_M:
                # The 3rd element is now a derived "cutting" flag
                # (alpha.73): 1 = firmware area_mowed_m2 ticked
                # forward in this segment; 0 = it stayed constant
                # (blades-up transit). Use TRANSIT_COLOR when we
                # know cutting=0, otherwise default colour.
                color = (
                    TRANSIT_COLOR if phase == 0 else self._trail_color
                )
                self._draw.line(
                    [self._last_point, px],
                    fill=color,
                    width=self._trail_width,
                    joint="curve",
                )
                self.version += 1
        self._last_point = px
        self._last_point_m = (new_x_m, new_y_m)

    # ------------------- replay -------------------

    def reset(self) -> None:
        """Clear the trail + dock + obstacles; bump version."""
        self._trail = Image.new("RGBA", self._size, (0, 0, 0, 0))
        self._draw = ImageDraw.Draw(self._trail, "RGBA")
        self._last_point = None
        self._last_point_m = None
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
            # Group consecutive entries by colour (alpha.73): the
            # 3rd element is the derived cutting flag (1 = blades
            # down, 0 = blades up transit, None = unknown / legacy).
            # Each contiguous same-colour run becomes one
            # ImageDraw.line so curve smoothing is preserved within
            # the run; we carry the last point of the previous run
            # as the first point of the next so colour transitions
            # join visually without a gap.
            current_color = None
            current_pts: list[tuple[float, float]] = []
            last_pt: tuple[float, float] | None = None
            for entry in path:
                if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                    continue
                cutting = int(entry[2]) if len(entry) >= 3 else None
                color = TRANSIT_COLOR if cutting == 0 else self._trail_color
                px = self._m_to_px(entry[0], entry[1])
                if color != current_color:
                    if current_color is not None and len(current_pts) >= 2:
                        self._draw.line(
                            current_pts, fill=current_color,
                            width=self._trail_width, joint="curve",
                        )
                    current_pts = [last_pt] if last_pt is not None else []
                    current_color = color
                current_pts.append(px)
                last_pt = px
            if current_color is not None and len(current_pts) >= 2:
                self._draw.line(
                    current_pts, fill=current_color,
                    width=self._trail_width, joint="curve",
                )
            if last_pt is not None:
                self._last_point = last_pt
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

        # Live mower position: paste the mower icon at the last
        # telemetry point. Updates on every `extend_live` call, so
        # the icon follows the mower without waiting for the heavy
        # base-PNG re-render. The base renderer's mower icon may
        # lag wherever update() last painted it (typically dock)
        # until the camera's next throttled refresh — this overlay
        # icon is what actually shows the current position.
        # White halo behind for contrast against grass/trail.
        if self._last_point is not None:
            px, py = self._last_point
            halo_r = MOWER_MARKER_OUTLINE_RADIUS_PX
            draw.ellipse(
                [(px - halo_r, py - halo_r), (px + halo_r, py + halo_r)],
                fill=(255, 255, 255, 220),
            )
            icon = _get_mower_icon(MOWER_MARKER_ICON_SIZE_PX)
            half = MOWER_MARKER_ICON_SIZE_PX // 2
            overlay.paste(
                icon,
                (int(px) - half, int(py) - half),
                icon,
            )

        for poly in self._obstacle_polys:
            draw.polygon(poly, fill=OBSTACLE_COLOR, outline=OBSTACLE_OUTLINE)

        # Note: dock marker intentionally NOT drawn here. The upstream
        # DreameMowerMapRenderer already paints a charger icon at
        # `map_data.charger_position` (set in `_build_map_from_cloud_data`
        # to the reflected cloud-origin + physical-station offset).
        # Drawing another disc here caused a visible doubling with the
        # TrailLayer's version a few pixels off because the two sources
        # derive the coord differently — the upstream uses cloud (0,0)
        # + 800 mm reflect, while ours pulled from each session's
        # summary `dock` field which varies per recording. Kept
        # `self._dock` state + setter for API compatibility in case a
        # future consumer wants to draw a secondary marker.

        composed = Image.alpha_composite(base, overlay)
        # Preserve the alpha channel — "outside the lawn" pixels are
        # fully transparent in the upstream renderer's colour scheme,
        # and flattening to RGB here would fill them with black. Keep
        # the PNG in RGBA so the Lovelace card's page background shows
        # through the way the app does it.
        buf = io.BytesIO()
        composed.save(buf, format="PNG", optimize=True)
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
