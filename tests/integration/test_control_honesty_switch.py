"""Integration tests for control-honesty markers on the switch platform.

Verifies:
- A CFG switch (dnd) now has read_only=False (device_writable) and
  calling async_turn_on DOES call coordinator.write_setting.
- A writable CFG switch (child_lock) has read_only=False and
  async_turn_on DOES call coordinator.write_setting.
- AI recognition bit-switch (Humans) is now device_writable (Task 10).
- DreameA2EdgeMowingAutoSwitch is now device_writable (Task 10).
- DreameA2MapEdgemasterSwitch is device_writable (Task 9/10).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from custom_components.dreame_a2_mower.cloud_state import (
    CloudState,
    ScheduleData,
    SettingsRoot,
)
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.mower.state import MowerState
from custom_components.dreame_a2_mower.observability import (
    FreshnessTracker,
    NovelObservationRegistry,
)
from custom_components.dreame_a2_mower.switch_global import SWITCHES
from custom_components.dreame_a2_mower.switch import (
    DreameA2Switch,
    DreameA2AiRecognitionHumansSwitch,
    DreameA2AiHumanDetectionSwitch,
    DreameA2EdgeMowingAutoSwitch,
    DreameA2MapEdgemasterSwitch,
)
from custom_components.dreame_a2_mower.control_honesty import _ControlHonestyMixin

_MAP_ID = 0


def _make_coord(*, settings_by_map=None, **state_kwargs):
    """Minimal coordinator stub using the same pattern as test_settings_switch_entities."""
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState(**state_kwargs)
    coord.live_map = LiveMapState()
    coord._prev_task_state = None
    coord._prev_in_dock = None
    coord.novel_registry = NovelObservationRegistry()
    coord.freshness = FreshnessTracker()
    coord._static_map_pngs_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._active_map_id = _MAP_ID
    coord._lifecycle_event = None
    coord._notification_event = None
    coord.entry = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.cloud_state = CloudState(
        cfg={},
        maps_by_id={},
        mow_paths_by_map_id={},
        settings=SettingsRoot(
            raw=[],
            by_map_id_canonical=settings_by_map or {},
        ),
        schedule=ScheduleData(version=0, slots=()),
        ai_human_enabled=None,
        forbidden_node_types_by_map={},
        ota_status=None,
        task_id=0,
        props={},
        mapl=None,
        mihis={},
        fetched_at_unix=0,
    )
    return coord


def _desc(key: str):
    """Find a switch descriptor by key."""
    for d in SWITCHES:
        if d.key == key:
            return d
    raise KeyError(key)


# ---------------------------------------------------------------------------
# now-writable CFG switch: dnd (promoted to device_writable in Task 8)
# ---------------------------------------------------------------------------

def test_dnd_switch_is_not_read_only():
    coord = _make_coord(dnd_enabled=True)
    ent = DreameA2Switch(coord, _desc("dnd"))
    assert ent.read_only is False


def test_dnd_switch_has_no_padlock_icon():
    coord = _make_coord(dnd_enabled=True)
    ent = DreameA2Switch(coord, _desc("dnd"))
    assert ent.icon != "mdi:lock-outline"


def test_dnd_switch_extra_attrs_mark_writable():
    coord = _make_coord(dnd_enabled=True)
    ent = DreameA2Switch(coord, _desc("dnd"))
    attrs = ent.extra_state_attributes
    assert attrs["read_only"] is False
    assert attrs["control_mode"] == "device_writable"


def test_dnd_turn_on_calls_write_setting():
    """async_turn_on on the now-writable dnd switch MUST call coordinator.write_setting.

    The dnd switch uses build_from_cfg_fn (RMW path) so the coordinator's
    cloud_state.cfg must carry a valid DND base value.
    """
    import dataclasses
    coord = _make_coord(dnd_enabled=False)
    # Seed the DND CFG base so the RMW path can proceed.
    # DND is read as list[3]: [enabled, start_min, end_min] (positional list format).
    coord.cloud_state = dataclasses.replace(
        coord.cloud_state,
        cfg={"DND": [0, 1200, 480]},
    )
    coord.write_setting = AsyncMock(return_value=True)  # spy
    ent = DreameA2Switch(coord, _desc("dnd"))
    ent.async_write_ha_state = MagicMock()

    asyncio.run(ent.async_turn_on())

    coord.write_setting.assert_called_once()


# ---------------------------------------------------------------------------
# writable CFG switch: child_lock
# ---------------------------------------------------------------------------

def test_child_lock_switch_is_not_read_only():
    coord = _make_coord(child_lock_enabled=False)
    ent = DreameA2Switch(coord, _desc("child_lock"))
    assert ent.read_only is False


def test_child_lock_switch_icon_is_not_padlock():
    coord = _make_coord(child_lock_enabled=False)
    ent = DreameA2Switch(coord, _desc("child_lock"))
    # Writable → should return the descriptor's icon (mdi:lock), not the padlock overlay
    assert ent.icon != "mdi:lock-outline"


def test_child_lock_turn_on_calls_write_setting():
    """async_turn_on on a writable switch MUST call coordinator.write_setting."""
    coord = _make_coord(child_lock_enabled=False)
    coord.write_setting = AsyncMock(return_value=True)
    ent = DreameA2Switch(coord, _desc("child_lock"))
    ent.async_write_ha_state = MagicMock()

    asyncio.run(ent.async_turn_on())

    coord.write_setting.assert_called_once()


# ---------------------------------------------------------------------------
# AI recognition bit-switch: Humans  (device_writable since Task 10)
# ---------------------------------------------------------------------------

def test_ai_recognition_humans_is_not_read_only():
    coord = _make_coord(
        settings_by_map={_MAP_ID: {"obstacleAvoidanceAi": 0b001}},
    )
    ent = DreameA2AiRecognitionHumansSwitch(coord, map_id=_MAP_ID)
    assert ent.read_only is False


def test_ai_recognition_humans_has_no_padlock_icon():
    coord = _make_coord(
        settings_by_map={_MAP_ID: {"obstacleAvoidanceAi": 0b001}},
    )
    ent = DreameA2AiRecognitionHumansSwitch(coord, map_id=_MAP_ID)
    assert ent.icon != "mdi:lock-outline"


def test_ai_recognition_humans_extra_attrs_mark_writable():
    coord = _make_coord(
        settings_by_map={_MAP_ID: {"obstacleAvoidanceAi": 0b001}},
    )
    ent = DreameA2AiRecognitionHumansSwitch(coord, map_id=_MAP_ID)
    attrs = ent.extra_state_attributes
    assert attrs["read_only"] is False
    assert attrs["control_mode"] == "device_writable"


# ---------------------------------------------------------------------------
# DreameA2AiHumanDetectionSwitch  (previously missed — read_only_pending)
# ---------------------------------------------------------------------------

def test_ai_human_detection_has_honesty_mixin():
    coord = _make_coord()
    ent = DreameA2AiHumanDetectionSwitch(coord)
    assert isinstance(ent, _ControlHonestyMixin)


def test_ai_human_detection_is_read_only():
    coord = _make_coord()
    ent = DreameA2AiHumanDetectionSwitch(coord)
    assert ent.read_only is True


def test_ai_human_detection_has_padlock_icon():
    coord = _make_coord()
    ent = DreameA2AiHumanDetectionSwitch(coord)
    assert ent.icon == "mdi:lock-outline"


def test_ai_human_detection_turn_on_does_not_call_write_ai_human_enabled():
    """read_only guard must fire BEFORE write_ai_human_enabled is called."""
    coord = _make_coord()
    coord.write_ai_human_enabled = AsyncMock(return_value=True)  # spy
    ent = DreameA2AiHumanDetectionSwitch(coord)
    ent.async_write_ha_state = MagicMock()

    asyncio.run(ent.async_turn_on())

    coord.write_ai_human_enabled.assert_not_called()
    ent.async_write_ha_state.assert_called_once()  # snap-back fired


def test_ai_human_detection_turn_off_does_not_call_write_ai_human_enabled():
    coord = _make_coord()
    coord.write_ai_human_enabled = AsyncMock(return_value=True)  # spy
    ent = DreameA2AiHumanDetectionSwitch(coord)
    ent.async_write_ha_state = MagicMock()

    asyncio.run(ent.async_turn_off())

    coord.write_ai_human_enabled.assert_not_called()
    ent.async_write_ha_state.assert_called_once()  # snap-back fired


# ---------------------------------------------------------------------------
# DreameA2EdgeMowingAutoSwitch  (device_writable since Task 10)
# ---------------------------------------------------------------------------

def test_edge_mowing_auto_has_honesty_mixin():
    coord = _make_coord(settings_by_map={_MAP_ID: {"edgeMowingAuto": 1}})
    ent = DreameA2EdgeMowingAutoSwitch(coord, map_id=_MAP_ID)
    assert isinstance(ent, _ControlHonestyMixin)


def test_edge_mowing_auto_is_not_read_only():
    coord = _make_coord(settings_by_map={_MAP_ID: {"edgeMowingAuto": 1}})
    ent = DreameA2EdgeMowingAutoSwitch(coord, map_id=_MAP_ID)
    assert ent.read_only is False


def test_edge_mowing_auto_has_no_padlock_icon():
    coord = _make_coord(settings_by_map={_MAP_ID: {"edgeMowingAuto": 1}})
    ent = DreameA2EdgeMowingAutoSwitch(coord, map_id=_MAP_ID)
    assert ent.icon != "mdi:lock-outline"


def test_edge_mowing_auto_extra_attrs_mark_writable():
    coord = _make_coord(settings_by_map={_MAP_ID: {"edgeMowingAuto": 1}})
    ent = DreameA2EdgeMowingAutoSwitch(coord, map_id=_MAP_ID)
    attrs = ent.extra_state_attributes
    assert attrs["read_only"] is False
    assert attrs["control_mode"] == "device_writable"


# ---------------------------------------------------------------------------
# DreameA2MapEdgemasterSwitch  (device_writable since Task 9)
# ---------------------------------------------------------------------------

def _make_coord_with_state_machine():
    """Coordinator stub that also has state_machine (needed by EdgeMaster)."""
    coord = _make_coord()
    sm = MagicMock()
    snap = MagicMock()
    snap.pre_shadow_by_map_id = {_MAP_ID: {"edgemaster": True}}
    sm.snapshot.return_value = snap
    coord.state_machine = sm
    return coord


def test_edgemaster_has_honesty_mixin():
    coord = _make_coord_with_state_machine()
    ent = DreameA2MapEdgemasterSwitch(coord, map_id=_MAP_ID)
    assert isinstance(ent, _ControlHonestyMixin)


def test_edgemaster_is_not_read_only():
    coord = _make_coord_with_state_machine()
    ent = DreameA2MapEdgemasterSwitch(coord, map_id=_MAP_ID)
    assert ent.read_only is False


def test_edgemaster_has_no_padlock_icon():
    coord = _make_coord_with_state_machine()
    ent = DreameA2MapEdgemasterSwitch(coord, map_id=_MAP_ID)
    # device_writable → no padlock; _attr_icon = "mdi:mower" should be returned
    assert ent.icon != "mdi:lock-outline"


def test_edgemaster_control_mode_is_device_writable():
    """EdgeMaster must report device_writable in extra_state_attributes."""
    from custom_components.dreame_a2_mower.control_honesty import ControlMode
    coord = _make_coord_with_state_machine()
    ent = DreameA2MapEdgemasterSwitch(coord, map_id=_MAP_ID)
    assert ent.control_mode == ControlMode.DEVICE_WRITABLE
    attrs = ent.extra_state_attributes
    assert attrs["read_only"] is False
    assert attrs["control_mode"] == "device_writable"
