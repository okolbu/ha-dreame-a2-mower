"""Decode + render tests for shapeType-aware exclusions.

Covers the live-map render fix that honors the cloud ``shapeType`` field:
- DECODE: a decorative shape (heart, shapeType 13) decodes UN-rotated (2 raw
  bbox corners) with the raw angle carried; a real LINE (shapeType 1) decodes
  to 2 points with shape_type 1.
- RENDER: a 2-point LINE draws pixels; a decorative heart stamps pixels.
"""
from __future__ import annotations

import dataclasses
import io

from PIL import Image

from custom_components.dreame_a2_mower.map_decoder import (
    ExclusionZone,
    MapData,
    MowingZone,
    _collect_exclusion_entries,
)
from custom_components.dreame_a2_mower.map_render import render_base_map


# ---------------------------------------------------------------------------
# DECODE
# ---------------------------------------------------------------------------


def test_decode_decorative_heart_unrotated_carries_angle():
    """shapeType 13 (heart): 2 path points kept as raw bbox corners (un-rotated),
    angle 90.29 carried, shape_type set."""
    wrapper = {
        "value": [
            [
                401,
                {
                    "path": [{"x": -9000, "y": -2000}, {"x": -4000, "y": 3000}],
                    "angle": 90.29,
                    "shapeType": 13,
                },
            ]
        ]
    }
    out = _collect_exclusion_entries(wrapper, None)
    assert len(out) == 1
    obj_id, raw_points, subtype, shape_type, raw_angle = out[0]
    assert obj_id == 401
    assert shape_type == 13
    assert raw_angle == 90.29
    # Raw bbox corners stored verbatim (angle NOT applied at decode).
    assert list(raw_points) == [(-9000.0, -2000.0), (-4000.0, 3000.0)]


def test_decode_line_shapetype_one_two_points():
    """shapeType 1 (line): 2-point path, shape_type 1."""
    wrapper = {
        "value": [
            [
                103,
                {
                    "path": [{"x": -3000, "y": 8000}, {"x": 6000, "y": 11000}],
                    "angle": 0,
                    "shapeType": 1,
                },
            ]
        ]
    }
    out = _collect_exclusion_entries(wrapper, None)
    obj_id, raw_points, subtype, shape_type, raw_angle = out[0]
    assert obj_id == 103
    assert shape_type == 1
    assert len(raw_points) == 2


def test_decode_non_decorative_stored_raw_render_rotates():
    """A non-decorative rotated rect (shapeType 2, angle 90) is stored RAW; the
    centroid rotation is applied by the render transform, not at decode (P3
    single-frame contract)."""
    from custom_components.dreame_a2_mower.protocol.map.geom import rotate_zone_points

    wrapper = {
        "value": [
            [
                101,
                {
                    "path": [
                        {"x": 0, "y": 0},
                        {"x": 1000, "y": 0},
                        {"x": 1000, "y": 1000},
                        {"x": 0, "y": 1000},
                    ],
                    "angle": 90,
                    "shapeType": 2,
                },
            ]
        ]
    }
    out = _collect_exclusion_entries(wrapper, None)
    _oid, raw_points, _sub, shape_type, raw_angle = out[0]
    assert shape_type == 2
    # Stored raw (angle NOT baked): first corner is the input (0, 0).
    assert raw_points[0] == (0.0, 0.0)
    # Render transform rotates it off (0, 0).
    rendered = rotate_zone_points(raw_points, raw_angle, shape_type)
    assert rendered[0] != (0.0, 0.0)


# ---------------------------------------------------------------------------
# RENDER
# ---------------------------------------------------------------------------


def _base_map(exclusions: tuple[ExclusionZone, ...]) -> MapData:
    """A 10m x 10m lawn with the given exclusion zones."""
    return MapData(
        md5="test-shapes",
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
            (0.0, 0.0), (10000.0, 0.0), (10000.0, 10000.0), (0.0, 10000.0),
        ),
        mowing_zones=(
            MowingZone(
                zone_id=1,
                name="lawn",
                path=(
                    (0.0, 0.0), (10000.0, 0.0),
                    (10000.0, 10000.0), (0.0, 10000.0),
                ),
                area_m2=100.0,
            ),
        ),
        exclusion_zones=exclusions,
        spot_zones=(),
        contour_paths=(),
        available_contour_ids=(),
        maintenance_points=(),
        patrol_points=(),
        dock_xy=None,
        total_area_m2=100.0,
        nav_paths=(),
    )


def _pixels(png: bytes) -> bytes:
    return Image.open(io.BytesIO(png)).convert("RGBA").tobytes()


def test_render_line_exclusion_draws_pixels():
    """A 2-point LINE (shapeType 1) contributes pixels vs. an empty-exclusion
    render of the same lawn."""
    line = ExclusionZone(
        points=((3000.0, 3000.0), (7000.0, 7000.0)),
        subtype=None,
        obj_id=103,
        shape_type=1,
    )
    with_line = _pixels(render_base_map(_base_map((line,))))
    without = _pixels(render_base_map(_base_map(())))
    assert with_line != without


def test_render_decorative_heart_stamps_pixels():
    """A decorative heart (shapeType 13) stamps a silhouette — pixels differ
    from the empty-exclusion render."""
    heart = ExclusionZone(
        points=((3000.0, 3000.0), (7000.0, 7000.0)),
        subtype=None,
        obj_id=401,
        shape_type=13,
        angle=90.29,
    )
    with_heart = _pixels(render_base_map(_base_map((heart,))))
    without = _pixels(render_base_map(_base_map(())))
    assert with_heart != without


def test_shape_mask_returns_none_for_unknown_type():
    """``_shape_mask`` returns None for a shapeType with no silhouette asset,
    which drives the render's bbox-rectangle fallback."""
    from custom_components.dreame_a2_mower.map_render.base_map import _shape_mask

    assert _shape_mask(99) is None
    # And a real decorative type decodes to an L-mode image.
    heart = _shape_mask(13)
    assert heart is not None and heart.mode == "L"
