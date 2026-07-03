"""The metre-frame edit polygon (formerly ``ExclusionZone.points_m``) is now a
DERIVATION (``rotate_zone_points(points, -angle)/1000``) at the render/edit
boundary — the stored ``points``/``points_m`` twin was removed in P3 (T2-17).
This pins the collector's RAW-frame output + the derivation identity.
"""
from custom_components.dreame_a2_mower.map_decoder import _collect_exclusion_entries
from custom_components.dreame_a2_mower.protocol.map.geom import rotate_zone_points


def test_collect_returns_raw_points():
    # path in mm; the collector stores the corners VERBATIM (no rotation baked).
    wrapper = {"value": [[101, {"path": [{"x": 9650, "y": -130}, {"x": 4120, "y": -130},
                                          {"x": 4120, "y": 5010}, {"x": 9650, "y": 5010}], "angle": 0}]]}
    out = _collect_exclusion_entries(wrapper, None)
    obj_id, raw_points, subtype, shape_type, raw_angle = out[0]
    assert obj_id == 101
    assert raw_points[0] == (9650.0, -130.0) and raw_points[2] == (4120.0, 5010.0)


def test_points_m_derivation_meters():
    # angle 0 -> rotate is identity -> points_m == raw/1000.
    raw = ((9650.0, -130.0), (4120.0, -130.0), (4120.0, 5010.0), (9650.0, 5010.0))
    rotated = rotate_zone_points(raw, 0.0, None)
    points_m = [(x / 1000.0, y / 1000.0) for (x, y) in rotated]
    assert points_m[0] == (9.65, -0.13) and points_m[2] == (4.12, 5.01)
