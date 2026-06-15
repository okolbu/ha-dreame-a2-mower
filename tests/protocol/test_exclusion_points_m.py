from custom_components.dreame_a2_mower.map_decoder import _collect_exclusion_entries, ExclusionZone


def test_exclusion_zone_has_points_m_default_empty():
    z = ExclusionZone(points=((0.0, 0.0),))
    assert z.points_m == ()


def test_collect_returns_points_m_in_meters():
    # path in mm; axis-aligned (angle 0) -> points_m == path/1000
    wrapper = {"value": [[101, {"path": [{"x": 9650, "y": -130}, {"x": 4120, "y": -130},
                                          {"x": 4120, "y": 5010}, {"x": 9650, "y": 5010}], "angle": 0}]]}
    out = _collect_exclusion_entries(wrapper, None)
    obj_id, rotated, subtype, points_m, shape_type, raw_angle = out[0]
    assert obj_id == 101
    assert points_m[0] == (9.65, -0.13) and points_m[2] == (4.12, 5.01)
