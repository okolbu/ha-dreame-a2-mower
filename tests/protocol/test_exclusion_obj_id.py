from custom_components.dreame_a2_mower.map_decoder import _collect_exclusion_entries, ExclusionZone


def test_exclusion_entries_carry_obj_id():
    wrapper = {"value": [
        [101, {"path": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}]}],
    ]}
    out = _collect_exclusion_entries(wrapper, None)
    assert len(out) == 1
    obj_id, rotated, subtype = out[0]
    assert obj_id == 101 and subtype is None and len(rotated) == 3


def test_exclusion_entries_missing_id_is_none():
    wrapper = {"value": [
        {"path": [{"x": 0, "y": 0}, {"x": 1, "y": 0}]},  # dict form, no id
    ]}
    out = _collect_exclusion_entries(wrapper, "ignore")
    assert out[0][0] is None and out[0][2] == "ignore"


def test_exclusion_entries_negative_id_sentinel_is_none():
    # id:-1 is the create-payload sentinel; must not surface as a real target.
    wrapper = {"value": [[-1, {"path": [{"x": 0, "y": 0}, {"x": 1, "y": 0}]}]]}
    out = _collect_exclusion_entries(wrapper, None)
    assert out[0][0] is None


def test_exclusion_zone_has_obj_id_default_none():
    z = ExclusionZone(points=((0.0, 0.0),))
    assert z.obj_id is None
    z2 = ExclusionZone(points=((0.0, 0.0),), subtype="ignore", obj_id=102)
    assert z2.obj_id == 102
