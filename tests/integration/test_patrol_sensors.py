from unittest.mock import MagicMock
from custom_components.dreame_a2_mower.entities.sensor.map import (
    DreameA2PatrolPointsSensor, DreameA2PatrolEdgesSensor,
)
from custom_components.dreame_a2_mower.map_decoder import PatrolPoint


def _coord_with_map(map_obj):
    coord = MagicMock()
    coord.cloud_state.maps_by_id = {0: map_obj}
    # Return a real empty dict so no cruise config is present; prevents MagicMock
    # auto-speculation from leaking into the cycles/auto_capture values.
    coord.cloud_state.cruise_config_by_map = {}
    return coord


def test_patrol_points_sensor_items():
    m = MagicMock()
    m.name = "Map 1"
    m.patrol_points = (PatrolPoint(3, -3050.0, -5480.0), PatrolPoint(4, -1980.0, 6340.0))
    s = DreameA2PatrolPointsSensor(_coord_with_map(m), map_id=0)
    assert s.native_value == 2
    items = s.extra_state_attributes["items"]
    # cycles defaults to 1 and auto_capture defaults to False (app's new-point defaults)
    # when no CRUISE.0 config is present for this point.
    assert items[0] == {"id": 3, "label": "Patrol point 3", "x_mm": -3050.0,
                        "y_mm": -5480.0, "cycles": 1, "auto_capture": False}


def test_patrol_edges_sensor_items_outer_only():
    m = MagicMock()
    m.name = "Map 1"
    m.available_contour_ids = ((1, 0), (1, 1), (2, 0))  # inner seam (1,1) excluded
    s = DreameA2PatrolEdgesSensor(_coord_with_map(m), map_id=0)
    assert s.native_value == 2
    items = s.extra_state_attributes["items"]
    assert items == [{"id": [1, 0], "label": "Edge 1"}, {"id": [2, 0], "label": "Edge 2"}]
