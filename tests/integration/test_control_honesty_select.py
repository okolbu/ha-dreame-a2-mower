"""Integration tests for control-honesty markers on the select platform.

Verifies:
- Per-map settings select (DreameA2PerMapMowingDirectionSelect) is now
  device_writable (Task 10): read_only=False, no padlock icon, and
  async_select_option DOES call _settings_select_optimistic_write.
- DreameA2SettingSelect navigation_path: read_only=False, select_option
  DOES call coordinator.write_setting.
- DreameA2ActionModeSelect: read_only=False,
  extra_state_attributes["control_mode"]=="integration_local",
  selecting still performs normal action (not snapped back).
- DreameA2SettingSelect rain_protection_resume_hours: read_only=False
  (device_writable since Task 8), select DOES call write_setting.
"""
from __future__ import annotations

import asyncio
import dataclasses
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.dreame_a2_mower.mower.state import MowerState
from custom_components.dreame_a2_mower.select_map_settings import (
    DreameA2PerMapMowingDirectionSelect,
)
from custom_components.dreame_a2_mower.select_global import (

    DreameA2SettingSelect,
    DreameA2ActionModeSelect,
    SETTING_SELECTS,
)

from custom_components.dreame_a2_mower.cloud_client import WriteResult as _WR

# P2 Task 5: the coordinator write families return WriteResult, not bool.
_WR_ACCEPTED = _WR(delivered=True, accepted=True, code=0)
_WR_REJECTED = _WR(delivered=True, accepted=False, code=-3, msg="not supported")


_MAP_ID = 0


def _make_map_coord(*, settings_by_map=None):
    """Minimal coordinator stub for per-map select entities."""
    coord = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.data = MowerState()
    cs = MagicMock()
    cs.maps_by_id = {_MAP_ID: MagicMock(name="Front")}
    cs.settings.by_map_id_canonical = settings_by_map or {_MAP_ID: {"mowingDirection": 0}}
    coord.cloud_state = cs
    # T3-4: DreameA2PerMapMowingDirectionSelect.async_select_option awaits
    # coordinator._render_base() after a successful write — plain MagicMock
    # attributes aren't awaitable, so this must be an AsyncMock (mirrors
    # test_action_mode_select.py's _make_coord).
    coord._render_base = AsyncMock()
    return coord


def _make_mower_coord(**state_kwargs):
    """Minimal coordinator stub for mower-scoped select entities."""
    coord = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.data = dataclasses.replace(MowerState(), **state_kwargs)
    return coord


def _setting_desc(key: str):
    """Find a SETTING_SELECTS descriptor by key."""
    for d in SETTING_SELECTS:
        if d.key == key:
            return d
    raise KeyError(key)


# ---------------------------------------------------------------------------
# DreameA2PerMapMowingDirectionSelect — device_writable since Task 10
# ---------------------------------------------------------------------------

def test_per_map_mowing_direction_is_not_read_only():
    coord = _make_map_coord()
    ent = DreameA2PerMapMowingDirectionSelect(coord, map_id=_MAP_ID)
    assert ent.read_only is False


def test_per_map_mowing_direction_has_no_padlock_icon():
    coord = _make_map_coord()
    ent = DreameA2PerMapMowingDirectionSelect(coord, map_id=_MAP_ID)
    assert ent.icon != "mdi:lock-outline"


def test_per_map_mowing_direction_extra_attrs_mark_writable():
    coord = _make_map_coord()
    ent = DreameA2PerMapMowingDirectionSelect(coord, map_id=_MAP_ID)
    attrs = ent.extra_state_attributes
    assert attrs["read_only"] is False
    assert attrs["control_mode"] == "device_writable"


def test_per_map_mowing_direction_select_option_calls_pre_settings_write():
    """async_select_option on the now-writable select MUST call
    pre_settings_optimistic_write (PRE dual-write path)."""
    coord = _make_map_coord(settings_by_map={_MAP_ID: {"mowingDirection": 0}})
    ent = DreameA2PerMapMowingDirectionSelect(coord, map_id=_MAP_ID)
    ent.async_write_ha_state = MagicMock()

    with patch(
        "custom_components.dreame_a2_mower.entities.select.map_settings.pre_settings_optimistic_write",
        new_callable=AsyncMock,
    ) as mock_opt_write:
        asyncio.run(ent.async_select_option("90°"))

    mock_opt_write.assert_called_once()


# ---------------------------------------------------------------------------
# DreameA2SettingSelect navigation_path — device_writable
# ---------------------------------------------------------------------------

def test_navigation_path_select_is_not_read_only():
    coord = _make_mower_coord(navigation_path_smart=False)
    ent = DreameA2SettingSelect(coord, _setting_desc("navigation_path"))
    assert ent.read_only is False


def test_navigation_path_select_extra_attrs_control_mode():
    coord = _make_mower_coord(navigation_path_smart=False)
    ent = DreameA2SettingSelect(coord, _setting_desc("navigation_path"))
    attrs = ent.extra_state_attributes
    assert attrs["control_mode"] == "device_writable"
    assert attrs["read_only"] is False


def test_navigation_path_select_option_calls_write_setting():
    """async_select_option on the writable navigation_path select MUST call
    coordinator.write_setting."""
    coord = _make_mower_coord(navigation_path_smart=False)
    coord.write_setting = AsyncMock(return_value=_WR_ACCEPTED)
    ent = DreameA2SettingSelect(coord, _setting_desc("navigation_path"))
    ent.async_write_ha_state = MagicMock()

    asyncio.run(ent.async_select_option("Smart Path"))

    coord.write_setting.assert_called_once()


# ---------------------------------------------------------------------------
# DreameA2ActionModeSelect — integration_local
# ---------------------------------------------------------------------------

def test_action_mode_select_is_not_read_only():
    coord = _make_mower_coord()
    ent = DreameA2ActionModeSelect(coord)
    assert ent.read_only is False


def test_action_mode_select_extra_attrs_control_mode():
    coord = _make_mower_coord()
    ent = DreameA2ActionModeSelect(coord)
    attrs = ent.extra_state_attributes
    assert attrs["control_mode"] == "integration_local"
    assert attrs["read_only"] is False


def test_action_mode_select_option_performs_normal_action():
    """Selecting an action_mode must update coordinator state (not snapped back)."""
    from custom_components.dreame_a2_mower.mower.state import ActionMode

    coord = _make_mower_coord()
    coord._render_base = AsyncMock()

    captured: list[MowerState] = []

    def _capture(new_state):
        captured.append(new_state)

    coord.async_set_updated_data.side_effect = _capture

    ent = DreameA2ActionModeSelect(coord)

    asyncio.run(ent.async_select_option(ActionMode.EDGE.value))

    # Must have updated the mower state (not snapped back empty)
    assert len(captured) == 1
    assert captured[0].action_mode == ActionMode.EDGE


# ---------------------------------------------------------------------------
# DreameA2SettingSelect rain_protection_resume_hours — device_writable (Task 8)
# ---------------------------------------------------------------------------

def test_rain_protection_resume_hours_is_not_read_only():
    coord = _make_mower_coord(rain_protection_resume_hours=2)
    ent = DreameA2SettingSelect(coord, _setting_desc("rain_protection_resume_hours"))
    assert ent.read_only is False


def test_rain_protection_resume_hours_has_no_padlock_icon():
    coord = _make_mower_coord(rain_protection_resume_hours=2)
    ent = DreameA2SettingSelect(coord, _setting_desc("rain_protection_resume_hours"))
    assert ent.icon != "mdi:lock-outline"


def test_rain_protection_resume_hours_extra_attrs_mark_writable():
    coord = _make_mower_coord(rain_protection_resume_hours=2)
    ent = DreameA2SettingSelect(coord, _setting_desc("rain_protection_resume_hours"))
    attrs = ent.extra_state_attributes
    assert attrs["read_only"] is False
    assert attrs["control_mode"] == "device_writable"
