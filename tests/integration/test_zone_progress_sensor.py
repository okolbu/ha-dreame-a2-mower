"""Parent-device per-zone mow-progress sensor (s2p56 zone_progress).

State "Mowing zone N of M" / "Idle"; attributes join zone ids to the active
map's MowingZone wire names. inventory § s2p56 (verified 2026-06-16)."""
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.mower.state import MowerState


def _zone(zone_id, name):
    z = MagicMock()
    z.zone_id = zone_id
    z.name = name
    return z


def _make_coord(zone_progress, named_zones, active_map_id=0):
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    coord._active_map_id = active_map_id
    m = MagicMock()
    m.mowing_zones = tuple(_zone(zid, nm) for zid, nm in named_zones.items())
    coord.cloud_state.maps_by_id = {active_map_id: m}
    coord.data = MowerState(zone_progress=zone_progress)
    return coord


def test_zone_progress_active_zone_state_and_attrs():
    from custom_components.dreame_a2_mower.sensor import DreameA2ZoneProgressSensor
    coord = _make_coord(
        zone_progress=((1, 2), (2, 0), (3, -1)),
        named_zones={1: "Front", 2: "Back", 3: "Side"},
    )
    s = DreameA2ZoneProgressSensor(coord)
    assert s.native_value == "Mowing zone 2 of 3"
    a = s.extra_state_attributes
    assert a["current_zone_id"] == 2
    assert a["current_zone_name"] == "Back"
    assert a["zones"] == [
        {"id": 1, "name": "Front", "status": "done"},
        {"id": 2, "name": "Back", "status": "active"},
        {"id": 3, "name": "Side", "status": "queued"},
    ]


def test_zone_progress_idle_when_empty():
    from custom_components.dreame_a2_mower.sensor import DreameA2ZoneProgressSensor
    coord = _make_coord(zone_progress=(), named_zones={1: "Front"})
    s = DreameA2ZoneProgressSensor(coord)
    assert s.native_value == "Idle"
    a = s.extra_state_attributes
    assert a["zones"] == []
    assert a["current_zone_id"] is None
    assert a["current_zone_name"] is None


def test_zone_progress_idle_when_no_active_zone():
    from custom_components.dreame_a2_mower.sensor import DreameA2ZoneProgressSensor
    # All done, none active → Idle.
    coord = _make_coord(
        zone_progress=((1, 2), (2, 2)), named_zones={1: "Front", 2: "Back"}
    )
    s = DreameA2ZoneProgressSensor(coord)
    assert s.native_value == "Idle"


def test_zone_progress_fallback_name_when_unnamed():
    from custom_components.dreame_a2_mower.sensor import DreameA2ZoneProgressSensor
    # zone id 9 not in the active map → synthetic "Zone 9".
    coord = _make_coord(zone_progress=((9, 0),), named_zones={1: "Front"})
    s = DreameA2ZoneProgressSensor(coord)
    a = s.extra_state_attributes
    assert a["zones"] == [{"id": 9, "name": "Zone 9", "status": "active"}]
    assert a["current_zone_name"] == "Zone 9"
