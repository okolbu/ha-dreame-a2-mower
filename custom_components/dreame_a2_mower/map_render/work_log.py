"""Work-log renderer: archived session base + trail + obstacles.

Exports: render_work_log.

This module owns the archived-session trail renderer (`_render_archived_trail`,
moved here from the deleted `trail.py` in the live-map rehaul). The live map no
longer renders a trail server-side — the map card draws it client-side from the
coordinator's published position stream — so the trail-drawing code now lives
only on the archived/work-log path, with the live mower-icon kwargs dropped (a
completed session has no live position).
"""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw

from .._png import encode_png
from ._geometry import _DEFAULT_PALETTE, _OBSTACLE_FILL, _OBSTACLE_OUTLINE
from .base_map import render_base_map

if TYPE_CHECKING:
    from ..live_map.trail import Leg
    from ..map_decoder import MapData

_LOGGER = logging.getLogger(__name__)

#: Trail line width in pixels. v1.0.0a17: bumped from 2 to 3 so the
#: path is more visible against the lawn green.
_TRAIL_LINE_WIDTH: int = 3


def render_work_log(
    map_data: MapData,
    *,
    legs: list[Leg] | None = None,
    local_legs: list[Leg] | None = None,
    cloud_segments: list[Leg] | None = None,
    mowing_legs: list[Leg] | None = None,
    traversal_legs: list[Leg] | None = None,
    legs_timeline: list[dict] | None = None,
    obstacle_polygons_m: list[list[tuple[float, float]]] | None = None,
    palette: dict | None = None,
    lawn_mode: str = "dark",
    trail_width_px: int | None = None,
) -> bytes:
    """Render an archived session: base + archived trail + archived obstacles.

    NO mower icon (the session is over, no live position), NO M_PATH
    (work logs are about ONE specific session, not cumulative history).

    Args:
        map_data: Decoded MapData for the map the session ran against.
        legs: Legacy single trail list (back-compat). Treated as
            ``cloud_segments`` when ``local_legs`` and ``cloud_segments``
            are both absent. Prefer passing the two split kwargs explicitly.
        local_legs: Full s1p4 telemetry trail (includes traversal arcs).
            When supplied alongside ``cloud_segments``, the splitter
            classifies each point as mowing (green) or traversal (grey).
        cloud_segments: Cloud-curated mowing-only trail segments from
            session_summary.track_segments.
        legs_timeline: Ordered list of leg dicts, each with keys ``role``
            (``"mowing"`` | ``"traversal"``), ``start_ts``, ``end_ts``, and
            ``pts`` (list of ``(x_m, y_m)`` tuples).  When supplied, the
            renderer paints directly from this timeline, bypassing all
            splitter logic.  Derived at render time from the archive's
            per-point ``track`` via ``session_card.derive_render_legs``.
        obstacle_polygons_m: Archived obstacles in cloud-frame metres.
        palette: Optional palette override.
        lawn_mode: Base lawn background mode. Defaults to ``"dark"`` because
            work logs render a completed mow session context.
        trail_width_px: Trail stroke width in pixels. None → use the module
            default (_TRAIL_LINE_WIDTH).

    Returns:
        Raw PNG bytes.
    """
    return _render_archived_trail(
        map_data,
        legs,
        local_legs=local_legs,
        cloud_segments=cloud_segments,
        mowing_legs=mowing_legs,
        traversal_legs=traversal_legs,
        legs_timeline=legs_timeline,
        palette=palette,
        lawn_mode=lawn_mode,
        obstacle_polygons_m=obstacle_polygons_m,
        trail_width_px=trail_width_px,
    )


def _render_archived_trail(
    map_data: MapData,
    legs: list[Leg] | None = None,
    palette: dict | None = None,
    obstacle_polygons_m: list[list[tuple[float, float]]] | None = None,
    *,
    local_legs: list[Leg] | None = None,
    cloud_segments: list[Leg] | None = None,
    mowing_legs: list[Leg] | None = None,
    traversal_legs: list[Leg] | None = None,
    legs_timeline: list[dict] | None = None,
    lawn_mode: str = "dark",
    trail_width_px: int | None = None,
) -> bytes:
    """Render the base map with an archived trail overlay composited on top.

    Moved verbatim from the deleted ``trail.py``'s ``render_with_trail``,
    minus the live ``mower_position_m`` / ``mower_heading_deg`` icon kwargs
    (an archived session has no live position — the icon is now drawn
    client-side only on the live map).

    Calls :func:`render_base_map` first to get the base PNG, then re-opens
    it with Pillow and draws trail polylines using :class:`PIL.ImageDraw`.
    Pen-up gaps between legs are honoured.

    Trail rendering uses a two-pass split so mowing strokes paint in
    ``mow_trail_color`` (light green) and traversal segments paint in
    ``traversal_color`` (grey), drawn last so they stay on top.
    """
    # Resolve effective trail width. Caller supplies None for the module
    # default so callers that don't care never have to know the constant.
    line_width: int = trail_width_px if trail_width_px is not None else _TRAIL_LINE_WIDTH
    from ..live_map.trail import render_trail_overlay

    # -----------------------------------------------------------------------
    # legs_timeline branch — paints records in capture order.
    # Takes priority over all legacy branches (early return).
    # -----------------------------------------------------------------------
    if legs_timeline is not None:
        base_png = render_base_map(map_data, palette=palette, lawn_mode=lawn_mode)

        # Resolve effective palette.
        p: dict = dict(_DEFAULT_PALETTE)
        if palette:
            p.update(palette)

        # Short-circuit when there's nothing to draw.
        if not legs_timeline and not obstacle_polygons_m:
            return base_png

        # Flip back to unflipped coordinate frame for trail drawing.
        image = Image.open(io.BytesIO(base_png)).convert("RGBA")
        image = image.transpose(Image.FLIP_TOP_BOTTOM)
        draw = ImageDraw.Draw(image, "RGBA")

        mow_color: tuple = p.get("mow_trail_color", (178, 223, 138, 255))
        trav_color: tuple = p.get("traversal_color", (130, 130, 130, 220))

        drawn_legs = 0
        drawn_points = 0

        # One pass in record order — later records overwrite earlier ones.
        for rec in legs_timeline:
            pts = rec.get("pts", [])
            if len(pts) < 2:
                continue
            color = mow_color if rec.get("role") == "mowing" else trav_color
            leg_px = [
                (
                    (map_data.bx2 - x_m * 1000.0) / map_data.pixel_size_mm,
                    (map_data.by2 - y_m * 1000.0) / map_data.pixel_size_mm,
                )
                for x_m, y_m in pts
            ]
            draw.line(leg_px, fill=color, width=line_width)
            drawn_legs += 1
            drawn_points += len(leg_px)

        drawn_obstacles = 0
        if obstacle_polygons_m:
            from ..live_map.trail import render_obstacle_overlay

            pixel_polys = render_obstacle_overlay(
                polygons=obstacle_polygons_m,
                bx2=map_data.bx2,
                by2=map_data.by2,
                pixel_size_mm=map_data.pixel_size_mm,
            )
            for poly_px in pixel_polys:
                draw.polygon(poly_px, fill=_OBSTACLE_FILL, outline=_OBSTACLE_OUTLINE)
                drawn_obstacles += 1

        image = image.transpose(Image.FLIP_TOP_BOTTOM)
        png_bytes = encode_png(image)

        _LOGGER.debug(
            "_render_archived_trail(legs_timeline): drew %d legs / %d points / %d obstacles → %d-byte PNG",
            drawn_legs,
            drawn_points,
            drawn_obstacles,
            len(png_bytes),
        )
        return png_bytes

    # --- Resolve caller args ---
    # Preferred path (v1.0.17+): explicit mowing_legs/traversal_legs
    # already classified at capture time (no fuzzy matching needed).
    # `legs` positional is back-compat: treated as cloud_segments.
    have_explicit_split = mowing_legs is not None or traversal_legs is not None
    _local = local_legs or []
    _cloud = cloud_segments if cloud_segments is not None else (legs or [])

    # --- Start from the base-map PNG ---
    base_png = render_base_map(map_data, palette=palette, lawn_mode=lawn_mode)

    # Resolve effective palette so colour lookups don't repeat the merge.
    p = dict(_DEFAULT_PALETTE)
    if palette:
        p.update(palette)

    # If we have nothing to overlay, the base map is the final output.
    if (
        not have_explicit_split
        and not _local
        and not _cloud
        and not obstacle_polygons_m
    ):
        return base_png

    # --- Resolve mowing vs traversal lists ---
    if have_explicit_split:
        mowing_legs_resolved: list = list(mowing_legs or [])
        traversal_legs_resolved: list = list(traversal_legs or [])
    else:
        # No capture-time split available. Paint everything as mowing — the
        # fuzzy splitter was deleted along with TrailLayer in Task 11.
        mowing_legs_resolved = list(_local) if _local else list(_cloud)
        traversal_legs_resolved = []
    mowing_legs = mowing_legs_resolved
    traversal_legs = traversal_legs_resolved

    # Re-open the base PNG in RGBA. render_base_map already flipped it
    # vertically (v1.0.0a5) to match the app's orientation, but the
    # trail's pixel coords come from render_trail_overlay using the
    # unflipped (by2 - cy)/grid formula. Flip back, draw trail, flip
    # forward — so the trail lands on the correct side and the final
    # image keeps the app-matching orientation.
    image = Image.open(io.BytesIO(base_png)).convert("RGBA")
    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    draw = ImageDraw.Draw(image, "RGBA")

    drawn_legs = 0
    drawn_points = 0

    # --- Pass 1: mowing strokes in light-green ---
    mow_color = p.get("mow_trail_color", (178, 223, 138, 255))
    mow_pixel_legs = render_trail_overlay(
        legs=mowing_legs,
        bx2=map_data.bx2,
        by2=map_data.by2,
        pixel_size_mm=map_data.pixel_size_mm,
    )
    for leg_px in mow_pixel_legs:
        if len(leg_px) < 2:
            continue
        draw.line(leg_px, fill=mow_color, width=line_width)
        drawn_legs += 1
        drawn_points += len(leg_px)

    # --- Pass 2: traversal in grey — drawn LAST so it stays on top ---
    trav_color = p.get("traversal_color", (130, 130, 130, 220))
    trav_pixel_legs = render_trail_overlay(
        legs=traversal_legs,
        bx2=map_data.bx2,
        by2=map_data.by2,
        pixel_size_mm=map_data.pixel_size_mm,
    )
    for leg_px in trav_pixel_legs:
        if len(leg_px) < 2:
            continue
        draw.line(leg_px, fill=trav_color, width=line_width)
        drawn_legs += 1
        drawn_points += len(leg_px)

    drawn_obstacles = 0
    if obstacle_polygons_m:
        from ..live_map.trail import render_obstacle_overlay

        pixel_polys = render_obstacle_overlay(
            polygons=obstacle_polygons_m,
            bx2=map_data.bx2,
            by2=map_data.by2,
            pixel_size_mm=map_data.pixel_size_mm,
        )
        for poly_px in pixel_polys:
            draw.polygon(poly_px, fill=_OBSTACLE_FILL, outline=_OBSTACLE_OUTLINE)
            drawn_obstacles += 1

    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    png_bytes = encode_png(image)

    _LOGGER.debug(
        "_render_archived_trail: drew %d legs / %d points / %d obstacles → %d-byte PNG",
        drawn_legs,
        drawn_points,
        drawn_obstacles,
        len(png_bytes),
    )
    return png_bytes
