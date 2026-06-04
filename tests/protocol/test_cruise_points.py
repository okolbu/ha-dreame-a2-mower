"""cruisePoints (patrol points, type=8) parsing."""
from custom_components.dreame_a2_mower.map_decoder import (
    PatrolPoint, _parse_cruise_points,
)

_CLOUD = {
    "cruisePoints": {"dataType": "Map", "value": [
        [3, {"id": 3, "type": 8, "shapeType": 5, "path": [{"x": -3050, "y": -5480}], "time": 60, "etime": 60}],
        [4, {"id": 4, "type": 8, "shapeType": 5, "path": [{"x": -1980, "y": 6340}], "time": 60, "etime": 60}],
    ]}
}


def test_parse_cruise_points_basic():
    pts = _parse_cruise_points(_CLOUD)
    assert pts == [
        PatrolPoint(point_id=3, x_mm=-3050.0, y_mm=-5480.0),
        PatrolPoint(point_id=4, x_mm=-1980.0, y_mm=6340.0),
    ]


def test_parse_cruise_points_empty():
    assert _parse_cruise_points({"cruisePoints": {"dataType": "Map", "value": []}}) == []
    assert _parse_cruise_points({}) == []


def test_parse_cruise_points_skips_pathless():
    bad = {"cruisePoints": {"value": [[9, {"id": 9, "type": 8}]]}}  # no path
    assert _parse_cruise_points(bad) == []


def test_mapdata_carries_patrol_points_field():
    from custom_components.dreame_a2_mower.map_decoder import MapData
    assert "patrol_points" in MapData.__dataclass_fields__
