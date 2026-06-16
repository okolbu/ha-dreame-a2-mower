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
