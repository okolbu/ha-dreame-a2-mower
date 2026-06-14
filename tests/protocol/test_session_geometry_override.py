"""Tests for apply_session_geometry — session-time no-go/spot override.

Verifies the points land in the same post-rotation cloud-frame mm
``parse_cloud_map`` now uses for exclusion/spot points (metres ×1000, NO
reflection — the render presentation step applies the midline reflection),
and that the canvas/projection is untouched (so trail alignment is preserved).

P3a transform-move (2026-06-14): pre-move these stored the midline-reflected
renderer-frame value (``x_reflect - x_mm``); the reflection now happens at
render time, so the stored points are raw cloud-frame mm. End-to-end render
is unchanged.
"""
from __future__ import annotations

from custom_components.dreame_a2_mower.map_decoder import (
    apply_session_geometry,
    parse_cloud_map,
)


def _base_map():
    md = parse_cloud_map(
        {"boundary": {"x1": 0, "y1": 0, "x2": 10000, "y2": 10000},
         "mowingAreas": {}, "totalArea": 100}
    )
    assert md is not None
    # x_reflect = bx1+bx2 = 10000, y_reflect = 10000
    assert md.cloud_x_reflect == 10000 and md.cloud_y_reflect == 10000
    return md


def test_exclusion_in_cloud_frame_mm():
    base = _base_map()
    # exclusion polygon in METRES (charger-relative, trail frame)
    excl = [[(1.0, 2.0), (1.5, 2.0), (1.5, 2.5), (1.0, 2.5)]]
    out = apply_session_geometry(base, exclusion_polys_m=excl, spot_polys_m=[])
    assert len(out.exclusion_zones) == 1
    pts = out.exclusion_zones[0].points
    # metres → post-rotation cloud-frame mm (×1000); render reflects.
    assert pts[0] == (1000.0, 2000.0)
    assert pts[1] == (1500.0, 2000.0)
    assert pts[2] == (1500.0, 2500.0)


def test_canvas_and_projection_unchanged():
    base = _base_map()
    out = apply_session_geometry(
        base,
        exclusion_polys_m=[[(1.0, 1.0), (2.0, 1.0), (2.0, 2.0)]],
        spot_polys_m=[],
    )
    # boundary box + reflections + pixel grid are untouched (trail still aligns)
    assert (out.bx1, out.by1, out.bx2, out.by2) == (base.bx1, base.by1, base.bx2, base.by2)
    assert out.cloud_x_reflect == base.cloud_x_reflect
    assert out.width_px == base.width_px and out.height_px == base.height_px


def test_degenerate_dropped_and_spots_in_cloud_frame_mm():
    base = _base_map()
    out = apply_session_geometry(
        base,
        exclusion_polys_m=[[(1.0, 1.0), (2.0, 1.0)]],  # <3 pts → dropped
        spot_polys_m=[[(3.0, 3.0), (4.0, 3.0), (4.0, 4.0), (3.0, 4.0)]],
    )
    assert out.exclusion_zones == ()
    assert len(out.spot_zones) == 1
    # metres → post-rotation cloud-frame mm (×1000); render reflects.
    assert out.spot_zones[0].points[0] == (3000.0, 3000.0)


def test_empty_inputs_clear_zones():
    base = _base_map()
    out = apply_session_geometry(base, exclusion_polys_m=[], spot_polys_m=[])
    assert out.exclusion_zones == ()
    assert out.spot_zones == ()
