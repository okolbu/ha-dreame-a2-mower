from types import SimpleNamespace
from custom_components.dreame_a2_mower._camera_map import DreameA2MapCamera
from custom_components.dreame_a2_mower.map_decoder import (
    ExclusionZone,
    SpotZone,
    MaintenancePoint,
)


def _bare_cam():
    """Minimal DreameA2MapCamera instance (no coordinator state needed)."""
    cam = DreameA2MapCamera.__new__(DreameA2MapCamera)
    cam.coordinator = SimpleNamespace(
        _active_map_id=0,
        cloud_state=None,
    )
    return cam


def test_editable_objects_attribute_shape():
    m = SimpleNamespace(exclusion_zones=(
        ExclusionZone(points=((0.0, 0.0),), subtype=None, obj_id=101, points_m=((9.65, -0.13), (4.12, 5.01))),
        ExclusionZone(points=((1.0, 1.0),), subtype="ignore", obj_id=102, points_m=((1.0, 2.0), (3.0, 4.0))),
        ExclusionZone(points=((2.0, 2.0),), subtype=None, obj_id=None, points_m=()),  # no id -> skip
    ))
    objs = _bare_cam()._editable_objects_from_map(m)
    ids = {(o["id"], o["kind"], o["op"]) for o in objs}
    assert (101, "nogo", 215) in ids
    assert (102, "ignore", 234) in ids
    assert all(o["id"] is not None for o in objs)
    assert len(objs) == 2


def test_editable_objects_spot_and_maintenance():
    """Spots (o=214) + maintenance points (o=224) surface as edit descriptors."""
    m = SimpleNamespace(
        exclusion_zones=(),
        spot_zones=(
            SpotZone(
                spot_id=7, name="Spot 7",
                points=((1000.0, 1000.0),),
                area_m2=4.0,
                points_m=((1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)),
            ),
            SpotZone(spot_id=None, name="x", points=(), area_m2=0.0, points_m=()),  # skip
        ),
        maintenance_points=(
            MaintenancePoint(point_id=42, x_mm=2500.0, y_mm=-1300.0),
        ),
    )
    objs = _bare_cam()._editable_objects_from_map(m)
    by_kind = {o["kind"]: o for o in objs}

    # Exactly one spot + one maintenance (None-id spot skipped).
    assert len(objs) == 2
    assert set(by_kind) == {"spot", "maintenance"}

    spot = by_kind["spot"]
    assert spot["id"] == 7
    assert spot["op"] == 214
    assert spot["type"] == 1
    assert spot["points_m"] == [[1.0, 1.0], [3.0, 1.0], [3.0, 3.0], [1.0, 3.0]]

    maint = by_kind["maintenance"]
    assert maint["id"] == 42
    assert maint["op"] == 224
    assert maint["type"] == 3
    # Single-point object: point_m (metres), NOT points_m.
    assert maint["point_m"] == [2.5, -1.3]
    assert "points_m" not in maint
