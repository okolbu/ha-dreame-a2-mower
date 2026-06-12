from types import SimpleNamespace
from custom_components.dreame_a2_mower._camera_map import DreameA2MapCamera
from custom_components.dreame_a2_mower.map_decoder import ExclusionZone


def test_editable_objects_attribute_shape():
    m = SimpleNamespace(exclusion_zones=(
        ExclusionZone(points=((0.0, 0.0),), subtype=None, obj_id=101, points_m=((9.65, -0.13), (4.12, 5.01))),
        ExclusionZone(points=((1.0, 1.0),), subtype="ignore", obj_id=102, points_m=((1.0, 2.0), (3.0, 4.0))),
        ExclusionZone(points=((2.0, 2.0),), subtype=None, obj_id=None, points_m=()),  # no id -> skip
    ))
    objs = DreameA2MapCamera._editable_objects_from_map(m)
    ids = {(o["id"], o["kind"], o["op"]) for o in objs}
    assert (101, "nogo", 215) in ids
    assert (102, "ignore", 234) in ids
    assert all(o["id"] is not None for o in objs)
    assert len(objs) == 2
