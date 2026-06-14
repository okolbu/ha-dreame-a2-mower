"""Live-map base renderer: render_base + pre-start preview branches.

Exports: render_base, STRIPE_WIDTH_MM.

The composited live render (``render_main_view`` + ``_composite_mower_icon``)
was removed in the live-map rehaul — the server renders only the BASE PNG
(``render_base``) and the map card draws the trail + mower icon client-side
from the published position stream.
"""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw

from .._png import encode_png
from ._geometry import _DEFAULT_PALETTE, _cloud_to_px, _renderer_to_px
from .base_map import render_base_map

if TYPE_CHECKING:
    from ..map_decoder import MapData

_LOGGER = logging.getLogger(__name__)

# Cosmetic stripe-width tunable — wider than the literal blade width to
# produce visually distinct bands in the pre-start preview.
STRIPE_WIDTH_MM: int = 400


def render_base(
    map_data: "MapData",
    *,
    background_mode,                      # BackgroundMode
    state: object | None = None,
    map_id: int = 0,
    palette: dict | None = None,
    obstacle_polygons_m: "list[list[tuple[float, float]]] | None" = None,
) -> bytes:
    """Render the live map's BASE PNG for the given background mode.

    No trail, no mower icon — those are drawn client-side by the map card.

    GREEN  -> dark-green active lawn (+ optional idle obstacle overlay).
    STRIPES-> dark lawn + next-mow stripe overlay (needs ``state`` + ``map_id``).
    EDGE   -> light lawn + dotted boundary.
    SPOT   -> light lawn + dotted spot rectangles.
    """
    from .direction import next_direction
    from .stripes import compute_stripe_overlay
    from .background import BackgroundMode

    if background_mode == BackgroundMode.STRIPES and state is not None:
        return _render_pre_start_with_stripes(
            map_data, state=state, map_id=int(map_id), palette=palette,
            next_direction_fn=next_direction,
            compute_stripe_overlay_fn=compute_stripe_overlay,
        )
    if background_mode == BackgroundMode.EDGE:
        return _render_pre_start_edge(map_data, palette=palette)
    if background_mode == BackgroundMode.SPOT:
        return _render_pre_start_spot(map_data, palette=palette)
    # GREEN (active) or STRIPES-without-state fallback: plain dark lawn,
    # optionally with the between-session obstacle overlay.
    return render_base_map(
        map_data, palette=palette, lawn_mode="dark",
        obstacles=obstacle_polygons_m,
    )


def _render_pre_start_with_stripes(
    map_data: MapData,
    *,
    state: object,
    map_id: int,
    palette: dict | None,
    next_direction_fn,
    compute_stripe_overlay_fn,
) -> bytes:
    """Dark-green base + stripe overlay at the next-mow angle.

    Used by the STRIPES background mode in ``render_base``.

    The stripe overlay is composited INSIDE ``render_base_map`` at the correct
    z-order (right after mowing-zone fills, before any other zone shapes) by
    passing it as the ``stripe_overlay`` kwarg.  This fixes two bugs present
    in the original post-composition approach:

    1. **Orientation**: The overlay is in PRE-FLIP pixel coordinates, matching
       the canvas BEFORE ``render_base_map``'s final FLIP_TOP_BOTTOM.
       Post-compositing after the flip caused stripes to appear upside-down
       relative to the underlying lawn.
    2. **Z-order**: Compositing after ``render_base_map`` placed stripes on top
       of every zone shape (exclusion, ignore-obstacle, spot zones), hiding
       them.  Inserting at layer 2.5 ensures subsequent zone layers paint on
       top of the stripes.
    """
    if not map_data.mowing_zones:
        # No zone to stripe; fall back to plain dark base.
        return render_base_map(map_data, palette=palette, lawn_mode="dark")

    # Compute next-mow angle using per-map direction history + pattern mode.
    last_dir = getattr(state, "last_all_area_mow_direction_deg", {}).get(map_id)
    mode = getattr(state, "settings_mowing_direction_mode", None)
    angle = next_direction_fn(last_direction_deg=last_dir, mode=mode)

    # Project the first mowing-zone polygon from cloud-frame mm to PRE-FLIP
    # pixel coordinates.  These match the canvas at composite-time inside
    # render_base_map (the final FLIP_TOP_BOTTOM hasn't happened yet).
    zone = map_data.mowing_zones[0]
    poly_px = [
        _cloud_to_px(x, y, map_data.bx2, map_data.by2, map_data.pixel_size_mm)
        for x, y in zone.path
    ]

    # Resolve effective palette for colour lookup.
    p: dict = dict(_DEFAULT_PALETTE)
    if palette:
        p.update(palette)

    # Build the stripe overlay at canvas dimensions (pre-flip).
    width_px = int(map_data.width_px)
    height_px = int(map_data.height_px)
    stripe_width_px = STRIPE_WIDTH_MM / map_data.pixel_size_mm
    overlay = compute_stripe_overlay_fn(
        width=width_px,
        height=height_px,
        lawn_polygon_px=poly_px,
        angle_deg=angle,
        stripe_width_px=stripe_width_px,
        dark_color=p["dark_green"],
        light_color=p["zone_fills"][0],
    )

    # Pass the overlay into render_base_map to be composited at the correct
    # z-order (layer 2.5 — after mowing zones, before exclusion/spot/nav/dock).
    # The final FLIP_TOP_BOTTOM inside render_base_map handles orientation for
    # the overlay and all other layers uniformly.
    return render_base_map(
        map_data,
        palette=palette,
        lawn_mode="dark",
        stripe_overlay=overlay,
    )


def _render_pre_start_edge(map_data: MapData, *, palette: dict | None) -> bytes:
    """Light-green base + dotted darker-green lawn boundary.

    Idle preview for EDGE mode: shows the perimeter the mower will follow
    once start is pressed.  The dotted overlay is drawn POST-FLIP (after
    render_base_map's internal FLIP_TOP_BOTTOM) to keep orientation consistent
    with the base map.
    """
    from .dotted import draw_dotted_polygon

    base_png = render_base_map(map_data, palette=palette, lawn_mode="light")
    image = Image.open(io.BytesIO(base_png)).convert("RGBA")
    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    draw = ImageDraw.Draw(image, "RGBA")
    for zone in map_data.mowing_zones:
        pts_px = [
            _cloud_to_px(x, y, map_data.bx2, map_data.by2, map_data.pixel_size_mm)
            for x, y in zone.path
        ]
        draw_dotted_polygon(
            draw, pts_px,
            color=(40, 160, 40, 230), width=6,
            dash_on_px=12, dash_off_px=8,
        )
    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    return encode_png(image)


def _render_pre_start_spot(map_data: MapData, *, palette: dict | None) -> bytes:
    """Light-green base + dotted darker-green spot rectangles with interior fill.

    Idle preview for SPOT mode: shows each selectable spot zone as a filled
    dotted rectangle so the user can confirm which spots will be mowed.

    Spot zones are stored in *renderer* coords (post-midline-reflection) by the
    decoder, so we use ``_renderer_to_px`` (not ``_cloud_to_px``) to map them
    to pixel space.
    """
    from .dotted import draw_dotted_polygon

    base_png = render_base_map(map_data, palette=palette, lawn_mode="light")
    image = Image.open(io.BytesIO(base_png)).convert("RGBA")
    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    draw = ImageDraw.Draw(image, "RGBA")
    for sz in getattr(map_data, "spot_zones", ()):
        if len(sz.points) < 3:
            continue
        pts_px = [
            _renderer_to_px(x, y, map_data.bx1, map_data.by1, map_data.pixel_size_mm)
            for x, y in sz.points
        ]
        # Interior fill: darker green for "this spot is eligible to mow".
        draw.polygon(pts_px, fill=(0, 100, 0, 110))
        draw_dotted_polygon(
            draw, pts_px,
            color=(40, 160, 40, 230), width=6,
            dash_on_px=12, dash_off_px=8,
        )
    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    return encode_png(image)
