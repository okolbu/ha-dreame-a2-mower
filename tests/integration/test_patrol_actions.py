import pytest
from custom_components.dreame_a2_mower.mower.actions import (
    MowerAction, ACTION_TABLE, _point_patrol_payload, _edge_patrol_payload,
)


def test_point_patrol_payload():
    assert _point_patrol_payload({"point_ids": [3, 4, 5]}) == {"point": [3, 4, 5]}
    with pytest.raises(ValueError):
        _point_patrol_payload({"point_ids": []})


def test_edge_patrol_payload():
    assert _edge_patrol_payload({"contour_ids": [[1, 0]]}) == {"edge": [[1, 0]]}
    with pytest.raises(ValueError):
        _edge_patrol_payload({"contour_ids": []})


def test_action_table_entries():
    assert ACTION_TABLE[MowerAction.START_POINT_PATROL]["routed_o"] == 107
    assert ACTION_TABLE[MowerAction.START_POINT_PATROL]["payload_fn"] is _point_patrol_payload
    assert ACTION_TABLE[MowerAction.START_EDGE_PATROL]["routed_o"] == 108
    assert ACTION_TABLE[MowerAction.START_EDGE_PATROL]["payload_fn"] is _edge_patrol_payload
