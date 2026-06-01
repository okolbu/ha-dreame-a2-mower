"""End-to-end: the archived-trail render draws mowing light-green / traversal grey.

The trail renderer moved into ``work_log._render_archived_trail`` (from the
deleted ``trail.py``) in the live-map rehaul; the live map no longer renders a
trail server-side. The public entry point is ``render_work_log``. The remaining
test guards the legacy ``legs=`` back-compat kwarg through that entry point.
"""
from __future__ import annotations

import io

from PIL import Image

from custom_components.dreame_a2_mower.map_decoder import MapData, MowingZone
from custom_components.dreame_a2_mower.map_render import (
    _DEFAULT_PALETTE,
    render_work_log,
)


def _tiny_map() -> MapData:
    """Build a 10m × 10m (10000mm × 10000mm) map with one mowing zone.

    Uses the same MapData field layout as other protocol tests.
    Coordinates are in cloud-frame mm.
    """
    return MapData(
        md5="test-traversal",
        width_px=200,
        height_px=200,
        pixel_size_mm=50.0,
        bx1=0.0,
        by1=0.0,
        bx2=10000.0,
        by2=10000.0,
        cloud_x_reflect=10000.0,
        cloud_y_reflect=10000.0,
        rotation_deg=0.0,
        boundary_polygon=(
            (0.0, 0.0),
            (10000.0, 0.0),
            (10000.0, 10000.0),
            (0.0, 10000.0),
        ),
        mowing_zones=(
            MowingZone(
                zone_id=0,
                name="lawn",
                path=(
                    (0.0, 0.0),
                    (10000.0, 0.0),
                    (10000.0, 10000.0),
                    (0.0, 10000.0),
                ),
                area_m2=100.0,
            ),
        ),
        exclusion_zones=(),
        spot_zones=(),
        contour_paths=(),
        available_contour_ids=(),
        maintenance_points=(),
        dock_xy=None,
        total_area_m2=100.0,
        nav_paths=(),
    )


def _collect_pixels(png_bytes: bytes) -> set:
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    return set(img.getdata())


# Legs are in metres (x_m, y_m) — same as live_map.legs and track_segments.
# Map is 10m × 10m (bx2=10000mm, by2=10000mm).


def test_legacy_legs_kwarg_still_works():
    """Back-compat: passing the old positional/legacy 'legs' kwarg still renders."""
    legs = [[(2.0, 5.0), (4.0, 5.0)]]
    png = render_work_log(_tiny_map(), legs=legs)
    assert isinstance(png, bytes)
    assert len(png) > 0
