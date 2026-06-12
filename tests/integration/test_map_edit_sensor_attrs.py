"""Per-map sensor attrs: renamable_zones + deletable_objects (map-edit)."""
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.sensor_map import DreameA2MapSegmentCountSensor
from custom_components.dreame_a2_mower.map_decoder import MowingZone, ExclusionZone


def _coord_with_map(map_obj):
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    coord.cloud_state.maps_by_id = {0: map_obj}
    return coord


def test_segment_sensor_exposes_rename_and_delete_targets():
    m = MagicMock()
    m.mowing_zones = (
        MowingZone(zone_id=1, name="Zone1", path=((0.0, 0.0),), area_m2=5.0),
    )
    m.exclusion_zones = (
        ExclusionZone(points=((0.0, 0.0),), subtype=None, obj_id=101),
        ExclusionZone(points=((1.0, 1.0),), subtype="ignore", obj_id=102),
        ExclusionZone(points=((2.0, 2.0),), subtype=None, obj_id=None),  # no id -> skip
    )
    s = DreameA2MapSegmentCountSensor(_coord_with_map(m), map_id=0)
    attrs = s.extra_state_attributes
    # Mowing zones are rename-only (delete via o=218 is unverified for zones).
    assert {"region": 1, "name": "Zone1"} in attrs["renamable_zones"]
    cats = {(o["id"], o["category"]) for o in attrs["deletable_objects"]}
    assert (1, 0) not in cats      # mowing zone NOT a delete target
    assert (101, 0) in cats        # no-go
    assert (102, 4) in cats        # ignore-obstacle
    assert all(o["id"] is not None for o in attrs["deletable_objects"])
    # only the two id-bearing exclusions; id-less + mowing zones excluded
    assert 2 == len(attrs["deletable_objects"])


def test_segment_sensor_attrs_empty_when_map_absent():
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    coord.cloud_state.maps_by_id = {}
    s = DreameA2MapSegmentCountSensor(coord, map_id=0)
    assert s.extra_state_attributes == {}
