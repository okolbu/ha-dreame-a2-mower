"""Unit tests for map_render.extract_projection."""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.dreame_a2_mower.map_render import extract_projection


def test_extract_projection_returns_expected_keys():
    map_data = SimpleNamespace(
        bx1=100.0, by1=200.0,
        bx2=12345.6, by2=7890.1, pixel_size_mm=50.0,
        width_px=637, height_px=717,
        dock_xy=(500.0, 1500.0),
    )
    proj = extract_projection(map_data)
    assert proj == {
        "bx1_mm": 100.0,
        "by1_mm": 200.0,
        "bx2_mm": 12345.6,
        "by2_mm": 7890.1,
        "pixel_size_mm": 50.0,
        "width_px": 637,
        "height_px": 717,
        "dock_xy_mm": [500.0, 1500.0],
    }
    # Guard against accidental key additions / drops.
    assert len(proj) == 8


def test_extract_projection_omits_dock_when_none():
    """dock_xy_mm only present when MapData has a dock position."""
    map_data = SimpleNamespace(
        bx1=0.0, by1=0.0, bx2=10000.0, by2=10000.0,
        pixel_size_mm=50.0, width_px=200, height_px=200,
        dock_xy=None,
    )
    proj = extract_projection(map_data)
    assert "dock_xy_mm" not in proj
    assert len(proj) == 7


def test_extract_projection_none_returns_none():
    """Sessions may be picked before MapData is fetched. Don't crash."""
    assert extract_projection(None) is None


# ---------------------------------------------------------------------------
# build_projection — the T2-17 render-side derivation owner. Rotates the raw
# zone corners, expands the bbox over them, and derives reflect/dock/canvas.
# ---------------------------------------------------------------------------


def test_build_projection_derives_canvas_from_raw_map():
    from custom_components.dreame_a2_mower.map_render import build_projection
    from custom_components.dreame_a2_mower.protocol.map import parse_cloud_map

    # A rotated exclusion pushes the bbox beyond the raw boundary.
    cloud = {
        "boundary": {"x1": 0, "y1": 0, "x2": 10000, "y2": 10000},
        "mowingAreas": {"value": []},
        "forbiddenAreas": {"value": [[101, {
            "path": [{"x": -2000, "y": 0}, {"x": 0, "y": 0}, {"x": 0, "y": 2000}],
            "angle": 0, "shapeType": 2,
        }]]},
        "notObsAreas": {"value": []}, "spotAreas": {"value": []},
        "contours": {"value": []}, "cleanPoints": {"value": []},
    }
    md = parse_cloud_map(cloud)
    assert md is not None
    proj = build_projection(md)
    assert proj is not None
    # build_projection is idempotent with the decoder's cached canvas.
    assert (proj.bx1, proj.by1, proj.bx2, proj.by2) == (md.bx1, md.by1, md.bx2, md.by2)
    assert (proj.width_px, proj.height_px) == (md.width_px, md.height_px)
    assert proj.cloud_x_reflect == md.cloud_x_reflect
    assert proj.cloud_y_reflect == md.cloud_y_reflect
    assert proj.dock_xy == md.dock_xy
    # The exclusion at x=-2000 expanded the bbox below the raw boundary x1=0.
    assert proj.bx1 <= -2000.0


def test_build_projection_none_returns_none():
    from custom_components.dreame_a2_mower.map_render import build_projection

    assert build_projection(None) is None
