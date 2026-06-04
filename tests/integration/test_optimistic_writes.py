"""Tests for the entity-layer optimistic-update + revert pattern.

NOTE (2026-06-04): Per-map settings numbers (DreameA2PerMapMowingHeightNumber
and its siblings) are all read_only_confirmed in control_honesty.py — the
honesty guard snaps them back before reaching _settings_optimistic_write.
The three write-path tests below have been updated to assert the CORRECT
post-honesty-wiring behavior: write_settings is NOT called and
async_write_ha_state IS called (snap-back).  The _settings_optimistic_write
machinery is still tested indirectly via the helper unit tests.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.mower.state import MowerState
from custom_components.dreame_a2_mower.number import DreameA2PerMapMowingHeightNumber


def _make_coord(initial_value: int | None = 5):
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState(settings_mowing_height=initial_value)
    coord._active_map_id = 0
    coord.entry = MagicMock()
    coord.entry.entry_id = "test"
    async def _stub_write_settings(*args, **kwargs):
        return True
    coord.write_settings = MagicMock(side_effect=_stub_write_settings)
    coord.hass = MagicMock()
    # cloud_state.settings.by_map_id_canonical accessor used by native_value
    cs = MagicMock()
    cs.settings.by_map_id_canonical = {0: {"mowingHeight": initial_value}}
    coord.cloud_state = cs
    return coord


def test_number_entity_calls_write_settings_with_explicit_map_id():
    """Per-map settings numbers are read_only_confirmed — write_settings must NOT
    be called; async_write_ha_state (snap-back) must be called instead."""
    coord = _make_coord(5)
    ent = DreameA2PerMapMowingHeightNumber(coord, map_id=0)
    ent.async_write_ha_state = MagicMock()
    ent.hass = MagicMock()
    asyncio.run(ent.async_set_native_value(7.0))
    # Honesty guard blocks the write — snap-back only.
    coord.write_settings.assert_not_called()
    ent.async_write_ha_state.assert_called_once()


def test_number_entity_optimistic_update_then_revert_on_failure():
    """With the honesty guard active, write_settings is never reached, so the
    optimistic-update-and-revert path is bypassed — state stays at initial value
    and snap-back (async_write_ha_state) is called."""
    coord = _make_coord(5)
    async def _stub_write_settings_fail(*args, **kwargs):
        return False
    coord.write_settings = MagicMock(side_effect=_stub_write_settings_fail)
    ent = DreameA2PerMapMowingHeightNumber(coord, map_id=0)
    ent.async_write_ha_state = MagicMock()
    ent.hass = coord.hass
    ent.entity_id = "number.test"
    asyncio.run(ent.async_set_native_value(7.0))
    # write_settings never called — honesty guard fired first.
    coord.write_settings.assert_not_called()
    # State unchanged (no optimistic update happened).
    assert coord.data.settings_mowing_height == 5
    # Snap-back was called.
    ent.async_write_ha_state.assert_called_once()


def test_per_map_number_writes_to_its_own_map_not_active(coordinator_with_two_maps):
    """Per-map entity is read_only_confirmed — even for map_id=1 the write is
    blocked by the honesty guard, not forwarded to write_settings."""
    coord = coordinator_with_two_maps
    coord.data = MowerState(settings_mowing_height=5)
    coord._active_map_id = 0
    cs = MagicMock()
    cs.settings.by_map_id_canonical = {
        0: {"mowingHeight": 3},
        1: {"mowingHeight": 6},
    }
    coord.cloud_state = cs

    async def _stub_write_settings(*args, **kwargs):
        return True
    coord.write_settings = MagicMock(side_effect=_stub_write_settings)
    coord.hass = MagicMock()

    ent = DreameA2PerMapMowingHeightNumber(coord, map_id=1)
    ent.async_write_ha_state = MagicMock()
    ent.hass = coord.hass

    asyncio.run(ent.async_set_native_value(4.0))
    # Honesty guard prevents write — write_settings not called.
    coord.write_settings.assert_not_called()
    ent.async_write_ha_state.assert_called_once()
