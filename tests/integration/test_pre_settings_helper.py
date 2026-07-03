import dataclasses
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

from custom_components.dreame_a2_mower import _settings_writes as sw

from homeassistant.exceptions import HomeAssistantError

from custom_components.dreame_a2_mower.cloud_client import WriteResult as _WR

# P2 Task 5: the coordinator write families return WriteResult, not bool.
_WR_ACCEPTED = _WR(delivered=True, accepted=True, code=0)
_WR_REJECTED = _WR(delivered=True, accepted=False, code=-3, msg="not supported")



@dataclasses.dataclass
class _S:
    settings_mowing_height: float = 5.5


class _ListenerCoord(SimpleNamespace):
    """SimpleNamespace coordinator double that actually wires
    async_set_updated_data -> .data + registered listeners, mirroring real
    DataUpdateCoordinator semantics (T3-5). Plain SimpleNamespace has no such
    method at all, so a bare SimpleNamespace() would AttributeError the
    moment the helper calls coord.async_set_updated_data(...)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._listeners: list = []

    def async_add_listener(self, callback):
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback)

    def async_set_updated_data(self, new_data):
        self.data = new_data
        for cb in list(self._listeners):
            cb()


def _entity():
    coord = _ListenerCoord()
    coord.data = _S()
    coord.write_map_general_setting = AsyncMock(return_value=_WR_ACCEPTED)
    coord.write_map_general_ai_bit = AsyncMock(return_value=_WR_ACCEPTED)
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
    coord.write_map_general_setting = AsyncMock(return_value=_WR_REJECTED)
    # P2 Task 5: the rejection is also RAISED (after revert + notification).
    with pytest.raises(HomeAssistantError):
        await sw.pre_settings_optimistic_write(
            ent, state_field="settings_mowing_height", new_value=6.0,
            map_id=1, pre_index=4, pre_value=60,
            settings_field="mowingHeight", settings_value=6.0,
        )
    assert coord.data.settings_mowing_height == 5.5  # reverted
    ent.hass.services.async_call.assert_awaited()


# ---------------------------------------------------------------------------
# T3-5: sibling-entity-sees-optimistic-value — a second entity mirroring the
# same MowerState field (registered as a coordinator listener, exactly like a
# real CoordinatorEntity's async_added_to_hass -> async_add_listener) must be
# notified of BOTH the optimistic apply and the revert-on-failure. Before the
# fix, both helpers assigned coord.data directly and called only
# entity.async_write_ha_state() (the WRITING entity) — a registered sibling
# listener never fired, so it kept showing the stale value for up to the next
# unrelated broadcast (~2 min).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pre_helper_notifies_sibling_listener_on_accept():
    ent, coord = _entity()
    sibling_seen: list[float] = []
    coord.async_add_listener(lambda: sibling_seen.append(coord.data.settings_mowing_height))

    await sw.pre_settings_optimistic_write(
        ent, state_field="settings_mowing_height", new_value=6.0,
        map_id=1, pre_index=4, pre_value=60,
        settings_field="mowingHeight", settings_value=6.0,
    )
    assert sibling_seen == [6.0]


@pytest.mark.asyncio
async def test_pre_helper_notifies_sibling_listener_on_revert():
    ent, coord = _entity()
    coord.write_map_general_setting = AsyncMock(return_value=_WR_REJECTED)
    sibling_seen: list[float] = []
    coord.async_add_listener(lambda: sibling_seen.append(coord.data.settings_mowing_height))

    with pytest.raises(HomeAssistantError):
        await sw.pre_settings_optimistic_write(
            ent, state_field="settings_mowing_height", new_value=6.0,
            map_id=1, pre_index=4, pre_value=60,
            settings_field="mowingHeight", settings_value=6.0,
        )
    # Sibling saw the optimistic apply (6.0), then the revert (5.5).
    assert sibling_seen == [6.0, 5.5]


@pytest.mark.asyncio
async def test_settings_helper_notifies_sibling_listener_on_accept():
    ent, coord = _entity()
    coord.write_settings = AsyncMock(return_value=_WR_ACCEPTED)
    sibling_seen: list[float] = []
    coord.async_add_listener(lambda: sibling_seen.append(coord.data.settings_mowing_height))

    await sw.settings_optimistic_write(
        ent, field="mowingHeight", new_value=6.0,
        state_field="settings_mowing_height", map_id=1,
    )
    assert sibling_seen == [6.0]


@pytest.mark.asyncio
async def test_settings_helper_notifies_sibling_listener_on_revert():
    ent, coord = _entity()
    coord.write_settings = AsyncMock(return_value=_WR_REJECTED)
    sibling_seen: list[float] = []
    coord.async_add_listener(lambda: sibling_seen.append(coord.data.settings_mowing_height))

    with pytest.raises(HomeAssistantError):
        await sw.settings_optimistic_write(
            ent, field="mowingHeight", new_value=6.0,
            state_field="settings_mowing_height", map_id=1,
        )
    assert sibling_seen == [6.0, 5.5]


