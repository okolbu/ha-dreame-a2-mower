from types import SimpleNamespace

from custom_components.dreame_a2_mower.cloud_state import CloudState


def _bare_cloud_state(**over):
    base = dict(
        cfg={}, maps_by_id={}, mow_paths_by_map_id={}, settings=None,
        schedule=None, ai_human_enabled=None, forbidden_node_types_by_map={},
        ota_status=None, task_id=0, props={}, mapl=None, mihis={},
        fetched_at_unix=0,
    )
    base.update(over)
    return CloudState(**base)


def test_cloud_state_has_cruise_config_default_empty():
    cs = _bare_cloud_state()
    assert cs.cruise_config_by_map == {}


def test_cloud_state_carries_cruise_config():
    cs = _bare_cloud_state(cruise_config_by_map={0: {3: {"cycles": 2, "auto_capture": True}}})
    assert cs.cruise_config_by_map[0][3]["cycles"] == 2


def _patrol_sensor(map_id, points, cruise_cfg):
    from custom_components.dreame_a2_mower.entities.sensor.map import DreameA2PatrolPointsSensor
    sensor = DreameA2PatrolPointsSensor.__new__(DreameA2PatrolPointsSensor)
    md = SimpleNamespace(patrol_points=points)
    sensor._map = lambda: md
    sensor.coordinator = SimpleNamespace(
        cloud_state=_bare_cloud_state(cruise_config_by_map=cruise_cfg)
    )
    sensor._map_id = map_id
    return sensor


def test_patrol_sensor_fills_cycles_and_auto_capture():
    pts = [SimpleNamespace(point_id=3, x_mm=-3050, y_mm=-5480)]
    s = _patrol_sensor(0, pts, {0: {3: {"cycles": 3, "auto_capture": True}}})
    item = s.extra_state_attributes["items"][0]
    assert item["cycles"] == 3 and item["auto_capture"] is True


def test_patrol_sensor_defaults_when_no_config():
    pts = [SimpleNamespace(point_id=4, x_mm=0, y_mm=0)]
    s = _patrol_sensor(0, pts, {})
    item = s.extra_state_attributes["items"][0]
    assert item["cycles"] == 1 and item["auto_capture"] is False


def test_editable_objects_patrol_carries_cycles_auto():
    from custom_components.dreame_a2_mower.camera.map import DreameA2MapCamera
    cam = DreameA2MapCamera.__new__(DreameA2MapCamera)
    md = SimpleNamespace(
        patrol_points=[SimpleNamespace(point_id=3, x_mm=-3050, y_mm=-5480)],
        exclusion_zones=(),
        spot_zones=(),
        maintenance_points=(),
    )
    cam.coordinator = SimpleNamespace(
        _active_map_id=0,
        cloud_state=_bare_cloud_state(
            maps_by_id={0: md},
            cruise_config_by_map={0: {3: {"cycles": 2, "auto_capture": True}}},
        ),
    )
    objs = cam._editable_objects_from_map(md)
    patrol = [o for o in objs if o.get("kind") == "patrol"][0]
    assert patrol["cycles"] == 2 and patrol["auto_capture"] is True
