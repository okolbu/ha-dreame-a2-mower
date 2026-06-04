"""Integration tests for control-honesty markers on the switch platform.

Verifies:
- A read-only CFG switch (dnd) shows padlock icon, read_only=True, and
  calling async_turn_on does NOT call coordinator.write_setting but DOES
  call async_write_ha_state (snap-back).
- A writable CFG switch (child_lock) has read_only=False and
  async_turn_on DOES call coordinator.write_setting.
- An AI recognition bit-switch (Humans) has read_only=True and padlock icon.
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
)

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
# read-only CFG switch: dnd
# ---------------------------------------------------------------------------

def test_dnd_switch_is_read_only():
    coord = _make_coord(dnd_enabled=True)
    ent = DreameA2Switch(coord, _desc("dnd"))
    assert ent.read_only is True


def test_dnd_switch_has_padlock_icon():
    coord = _make_coord(dnd_enabled=True)
    ent = DreameA2Switch(coord, _desc("dnd"))
    assert ent.icon == "mdi:lock-outline"


def test_dnd_switch_extra_attrs_mark_read_only():
    coord = _make_coord(dnd_enabled=True)
    ent = DreameA2Switch(coord, _desc("dnd"))
    attrs = ent.extra_state_attributes
    assert attrs["read_only"] is True


def test_dnd_turn_on_does_not_call_write_setting_and_snaps_back():
    """async_turn_on on a read-only switch must NOT call coordinator.write_setting."""
    coord = _make_coord(dnd_enabled=False)
    coord.write_setting = AsyncMock(return_value=True)  # spy
    ent = DreameA2Switch(coord, _desc("dnd"))
    ent.async_write_ha_state = MagicMock()

    asyncio.run(ent.async_turn_on())

    coord.write_setting.assert_not_called()
    ent.async_write_ha_state.assert_called_once()  # snap-back fired


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
# AI recognition bit-switch: Humans  (read_only_confirmed)
# ---------------------------------------------------------------------------

def test_ai_recognition_humans_is_read_only():
    coord = _make_coord(
        settings_by_map={_MAP_ID: {"obstacleAvoidanceAi": 0b001}},
    )
    ent = DreameA2AiRecognitionHumansSwitch(coord, map_id=_MAP_ID)
    assert ent.read_only is True


def test_ai_recognition_humans_has_padlock_icon():
    coord = _make_coord(
        settings_by_map={_MAP_ID: {"obstacleAvoidanceAi": 0b001}},
    )
    ent = DreameA2AiRecognitionHumansSwitch(coord, map_id=_MAP_ID)
    assert ent.icon == "mdi:lock-outline"


def test_ai_recognition_humans_turn_on_does_not_write_and_snaps_back():
    """AI recognition toggle must snap-back without calling write_settings."""
    coord = _make_coord(
        settings_by_map={_MAP_ID: {"obstacleAvoidanceAi": 0b000}},
    )
    coord.write_settings = AsyncMock(return_value=True)  # spy
    ent = DreameA2AiRecognitionHumansSwitch(coord, map_id=_MAP_ID)
    ent.async_write_ha_state = MagicMock()

    asyncio.run(ent.async_turn_on())

    coord.write_settings.assert_not_called()
    ent.async_write_ha_state.assert_called_once()  # snap-back fired
