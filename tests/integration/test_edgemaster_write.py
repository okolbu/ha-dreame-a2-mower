"""Task 9: edgemaster PRE-only write.

DreameA2MapEdgemasterSwitch reads the s6p2 PRE shadow and writes via
coordinator.write_map_general_setting(map_id=..., pre_index=10, pre_value=...)
with NO settings_field (edgemaster has no SETTINGS surface on g2408 firmware).
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.dreame_a2_mower import switch_map as sm
from custom_components.dreame_a2_mower.control_honesty import ControlMode


def _make(map_id=0, mode=ControlMode.DEVICE_WRITABLE):
    ent = object.__new__(sm.DreameA2MapEdgemasterSwitch)
    ent._map_id = map_id
    ent._control_mode = mode
    coord = SimpleNamespace(write_map_general_setting=AsyncMock(return_value=True))
    ent.coordinator = coord
    ent.entity_id = "switch.x"
    ent.async_write_ha_state = lambda: None
    ent.hass = SimpleNamespace(services=SimpleNamespace(async_call=AsyncMock()))
    return ent, coord


@pytest.mark.asyncio
async def test_edgemaster_turn_on_pre_only():
    ent, coord = _make()
    await ent.async_turn_on()
    coord.write_map_general_setting.assert_awaited_once_with(map_id=0, pre_index=10, pre_value=1)
    # PRE-only: no settings_field/settings_value kwargs


@pytest.mark.asyncio
async def test_edgemaster_turn_off_pre_only():
    ent, coord = _make()
    await ent.async_turn_off()
    coord.write_map_general_setting.assert_awaited_once_with(map_id=0, pre_index=10, pre_value=0)


@pytest.mark.asyncio
async def test_edgemaster_read_only_does_not_write():
    ent, coord = _make(mode=ControlMode.READ_ONLY_NOOP)
    # _reject_readonly_write needs async_write_ha_state; provided
    await ent.async_turn_on()
    coord.write_map_general_setting.assert_not_awaited()
