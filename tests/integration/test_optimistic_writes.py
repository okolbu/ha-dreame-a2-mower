"""Tests for the entity-layer optimistic-update + revert pattern.

NOTE (2026-06-10, Task 10): Per-map settings numbers (DreameA2PerMapMowingHeightNumber
and its siblings) are now device_writable.  They route through
_pre_settings_optimistic_write which calls coordinator.write_map_general_setting.
The three write-path tests below assert this new writable behavior.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.mower.state import MowerState
from custom_components.dreame_a2_mower.number import DreameA2PerMapMowingHeightNumber


def _make_coord(initial_value: int | None = 5):
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState(settings_mowing_height=initial_value)
    coord._active_map_id = 0
    coord.entry = MagicMock()
    coord.entry.entry_id = "test"
    coord.write_map_general_setting = AsyncMock(return_value=True)
    coord.hass = MagicMock()
    # cloud_state.settings.by_map_id_canonical accessor used by native_value
    cs = MagicMock()
    cs.settings.by_map_id_canonical = {0: {"mowingHeight": initial_value}}
    coord.cloud_state = cs
    return coord


def test_number_entity_calls_write_settings_with_explicit_map_id():
    """Per-map settings numbers are now device_writable — write_map_general_setting
    MUST be called; async_write_ha_state (optimistic update) is also called."""
    coord = _make_coord(5)
    ent = DreameA2PerMapMowingHeightNumber(coord, map_id=0)
    ent.async_write_ha_state = MagicMock()
    ent.hass = MagicMock()
    asyncio.run(ent.async_set_native_value(7.0))
    coord.write_map_general_setting.assert_called_once()


def test_number_entity_optimistic_update_then_revert_on_failure():
    """With write_map_general_setting failing, the optimistic value is reverted."""
    coord = _make_coord(5)
    coord.write_map_general_setting = AsyncMock(return_value=False)
    ent = DreameA2PerMapMowingHeightNumber(coord, map_id=0)
    ent.async_write_ha_state = MagicMock()
    # hass.services.async_call is awaited on the revert path — must be AsyncMock
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    ent.hass = hass
    ent.entity_id = "number.test"
    asyncio.run(ent.async_set_native_value(7.0))
    # write was attempted
    coord.write_map_general_setting.assert_called_once()
    # State reverted to original after failure
    assert coord.data.settings_mowing_height == 5
    # async_write_ha_state called at least twice: once optimistic, once revert
    assert ent.async_write_ha_state.call_count >= 2


def test_per_map_number_writes_to_its_own_map_not_active(coordinator_with_two_maps):
    """Per-map entity for map_id=1 passes map_id=1 to write_map_general_setting,
    regardless of coord._active_map_id=0."""
    coord = coordinator_with_two_maps
    coord.data = MowerState(settings_mowing_height=5)
    coord._active_map_id = 0
    cs = MagicMock()
    cs.settings.by_map_id_canonical = {
        0: {"mowingHeight": 3},
        1: {"mowingHeight": 6},
    }
    coord.cloud_state = cs
    coord.write_map_general_setting = AsyncMock(return_value=True)
    coord.hass = MagicMock()

    ent = DreameA2PerMapMowingHeightNumber(coord, map_id=1)
    ent.async_write_ha_state = MagicMock()
    ent.hass = coord.hass

    asyncio.run(ent.async_set_native_value(4.0))
    # write_map_general_setting was called with map_id=1
    coord.write_map_general_setting.assert_called_once()
    call_kwargs = coord.write_map_general_setting.call_args.kwargs
    assert call_kwargs.get("map_id") == 1
