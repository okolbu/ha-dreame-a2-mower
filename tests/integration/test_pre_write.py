from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest

from custom_components.dreame_a2_mower.coordinator._writes import _WritesMixin

PRE = [0, 0, 0, 0, 55, 1, 8, 1, 0, 1, 1, 2, 1, 20, 10, 7, 1, 2, 0]


def _coord():
    c = _WritesMixin()
    c._cloud = SimpleNamespace(
        get_pre=MagicMock(return_value=list(PRE)),
        set_pre=MagicMock(return_value=True),
    )
    async def _exec(fn, *a):  # emulate hass.async_add_executor_job
        return fn(*a)
    c.hass = SimpleNamespace(async_add_executor_job=AsyncMock(side_effect=_exec))
    c.write_settings = AsyncMock(return_value=True)
    return c


@pytest.mark.asyncio
async def test_write_map_general_setting_dual_writes():
    c = _coord()
    ok = await c.write_map_general_setting(
        map_id=1, pre_index=4, pre_value=60,
        settings_field="mowingHeight", settings_value=6.0,
    )
    assert ok is True
    c._cloud.get_pre.assert_called_once_with(1, 0)
    arr = c._cloud.set_pre.call_args[0][0]
    assert arr[0] == 0 and arr[1] == 1 and arr[2] == 0 and arr[4] == 60
    c.write_settings.assert_awaited_once_with(map_id=1, field="mowingHeight", value=6.0)


@pytest.mark.asyncio
async def test_pre_failure_skips_settings():
    c = _coord()
    c._cloud.set_pre = MagicMock(return_value=False)
    ok = await c.write_map_general_setting(
        map_id=1, pre_index=4, pre_value=60,
        settings_field="mowingHeight", settings_value=6.0,
    )
    assert ok is False
    c.write_settings.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_base_aborts():
    c = _coord()
    c._cloud.get_pre = MagicMock(return_value=None)
    ok = await c.write_map_general_setting(
        map_id=1, pre_index=4, pre_value=60,
        settings_field="mowingHeight", settings_value=6.0,
    )
    assert ok is False
    c._cloud.set_pre.assert_not_called()
    c.write_settings.assert_not_awaited()


@pytest.mark.asyncio
async def test_edgemaster_pre_only():
    c = _coord()
    ok = await c.write_map_general_setting(map_id=0, pre_index=10, pre_value=1)
    assert ok is True
    arr = c._cloud.set_pre.call_args[0][0]
    assert arr[10] == 1 and arr[1] == 0
    c.write_settings.assert_not_awaited()


@pytest.mark.asyncio
async def test_ai_bit_dual_write():
    c = _coord()
    ok = await c.write_map_general_ai_bit(map_id=0, bit=0, on=False, settings_value=6)
    assert ok is True
    arr = c._cloud.set_pre.call_args[0][0]
    assert arr[15] == 6
    c.write_settings.assert_awaited_once_with(map_id=0, field="obstacleAvoidanceAi", value=6)
