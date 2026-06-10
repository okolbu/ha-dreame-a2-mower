import dataclasses
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

from custom_components.dreame_a2_mower import _settings_writes as sw


@dataclasses.dataclass
class _S:
    settings_mowing_height: float = 5.5


def _entity():
    coord = SimpleNamespace()
    coord.data = _S()
    coord.write_map_general_setting = AsyncMock(return_value=True)
    coord.write_map_general_ai_bit = AsyncMock(return_value=True)
    ent = SimpleNamespace(
        coordinator=coord, entity_id="number.x",
        async_write_ha_state=lambda: None,
        hass=SimpleNamespace(services=SimpleNamespace(async_call=AsyncMock())),
    )
    return ent, coord


@pytest.mark.asyncio
async def test_pre_helper_calls_dual_write_and_optimistic():
    ent, coord = _entity()
    await sw.pre_settings_optimistic_write(
        ent, state_field="settings_mowing_height", new_value=6.0,
        map_id=1, pre_index=4, pre_value=60,
        settings_field="mowingHeight", settings_value=6.0,
    )
    assert coord.data.settings_mowing_height == 6.0
    coord.write_map_general_setting.assert_awaited_once_with(
        map_id=1, pre_index=4, pre_value=60,
        settings_field="mowingHeight", settings_value=6.0,
    )


@pytest.mark.asyncio
async def test_pre_helper_reverts_on_failure():
    ent, coord = _entity()
    coord.write_map_general_setting = AsyncMock(return_value=False)
    await sw.pre_settings_optimistic_write(
        ent, state_field="settings_mowing_height", new_value=6.0,
        map_id=1, pre_index=4, pre_value=60,
        settings_field="mowingHeight", settings_value=6.0,
    )
    assert coord.data.settings_mowing_height == 5.5  # reverted
    ent.hass.services.async_call.assert_awaited()


