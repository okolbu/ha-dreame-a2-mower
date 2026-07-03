"""Task B acceptance tests — write rejections surface as HA exceptions.

Covers the plan's §1.2-B acceptance criterion:
  - mow_zone SERVICE handler raises ServiceValidationError on a device-rejected
    (r=-3 / delivered-but-not-accepted) result, and HomeAssistantError on a
    not-delivered result.
  - The Start lawn_mower command and the Start button raise HomeAssistantError
    (entity context) on a not-accepted result.
  - An accepted result does NOT raise (happy path).
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.dreame_a2_mower import services
from custom_components.dreame_a2_mower.cloud_client import WriteResult
from custom_components.dreame_a2_mower.mower.state import ActionMode, MowerState


# --------------------------------------------------------------------------
# Service context — mow_zone
# --------------------------------------------------------------------------

def _mow_zone_coord(monkeypatch, dispatch_result):
    coord = MagicMock()
    coord.data = MowerState()
    coord.async_set_updated_data = MagicMock()
    coord.dispatch_action = AsyncMock(return_value=dispatch_result)
    monkeypatch.setattr(services, "_coordinator_from_call", lambda hass, call: coord)
    return coord


def _mow_zone_call():
    return SimpleNamespace(hass=SimpleNamespace(), data={"zone_ids": [1]})


@pytest.mark.asyncio
async def test_mow_zone_accepted_dispatches_and_selects_zone(monkeypatch):
    """Accepted mow_zone: selection state is broadcast AND the zone-mow action
    is dispatched with the requested zones (T7-9: was an assert-nothing test)."""
    from custom_components.dreame_a2_mower.mower.actions import MowerAction

    coord = _mow_zone_coord(monkeypatch, WriteResult.local_ok())
    await services._handle_mow_zone(_mow_zone_call())
    # The optimistic selection update was broadcast (ZONE mode, zone 1).
    coord.async_set_updated_data.assert_called_once()
    new_state = coord.async_set_updated_data.call_args.args[0]
    assert new_state.action_mode == ActionMode.ZONE
    assert new_state.active_selection_zones == (1,)
    # The device action went out with the requested zones.
    coord.dispatch_action.assert_awaited_once_with(
        MowerAction.START_ZONE_MOW, {"zones": [1]}
    )


@pytest.mark.asyncio
async def test_mow_zone_device_rejected_raises_service_validation(monkeypatch):
    _mow_zone_coord(
        monkeypatch,
        WriteResult(delivered=True, accepted=False, code=-3, msg="not supported"),
    )
    with pytest.raises(ServiceValidationError):
        await services._handle_mow_zone(_mow_zone_call())


@pytest.mark.asyncio
async def test_mow_zone_not_delivered_raises_home_assistant_error(monkeypatch):
    _mow_zone_coord(monkeypatch, WriteResult.not_delivered("asleep"))
    with pytest.raises(HomeAssistantError) as exc:
        await services._handle_mow_zone(_mow_zone_call())
    # Not-delivered is the retryable transport class, NOT a ServiceValidationError.
    assert not isinstance(exc.value, ServiceValidationError)


# --------------------------------------------------------------------------
# Entity context — lawn_mower START command
# --------------------------------------------------------------------------

def _lawn_mower(dispatch_result):
    from custom_components.dreame_a2_mower.lawn_mower import DreameA2LawnMower

    coord = MagicMock()
    coord.data = MowerState(action_mode=ActionMode.ALL_AREAS)
    coord.dispatch_action = AsyncMock(return_value=dispatch_result)
    lm = DreameA2LawnMower.__new__(DreameA2LawnMower)
    lm.coordinator = coord
    return lm


@pytest.mark.asyncio
async def test_lawn_mower_start_accepted_dispatches_all_areas():
    """Accepted start (ALL_AREAS mode): START_MOWING is dispatched exactly once
    with no params, and nothing raises (T7-9: was an assert-nothing test)."""
    from custom_components.dreame_a2_mower.mower.actions import MowerAction

    lm = _lawn_mower(WriteResult.local_ok())
    await lm.async_start_mowing()
    lm.coordinator.dispatch_action.assert_awaited_once_with(
        MowerAction.START_MOWING, {}
    )


@pytest.mark.asyncio
async def test_lawn_mower_start_rejected_raises_home_assistant_error():
    lm = _lawn_mower(
        WriteResult(delivered=True, accepted=False, code=-3, msg="nope")
    )
    with pytest.raises(HomeAssistantError) as exc:
        await lm.async_start_mowing()
    # Entity context must NOT raise the service-only ServiceValidationError.
    assert not isinstance(exc.value, ServiceValidationError)


@pytest.mark.asyncio
async def test_lawn_mower_start_not_delivered_raises_home_assistant_error():
    lm = _lawn_mower(WriteResult.not_delivered("asleep"))
    with pytest.raises(HomeAssistantError):
        await lm.async_start_mowing()


# --------------------------------------------------------------------------
# Entity context — Start button
# --------------------------------------------------------------------------

def _start_button(dispatch_result):
    from custom_components.dreame_a2_mower.button import DreameA2StartMowingButton

    coord = MagicMock()
    coord.data = MowerState(action_mode=ActionMode.ALL_AREAS)
    coord.dispatch_action = AsyncMock(return_value=dispatch_result)
    b = DreameA2StartMowingButton.__new__(DreameA2StartMowingButton)
    b.coordinator = coord
    b._attr_unique_id = "test_start_button"
    return b


@pytest.mark.asyncio
async def test_start_button_accepted_dispatches_selected_mode():
    """Accepted Start-button press honours action_mode (ALL_AREAS →
    START_MOWING, {}) and dispatches exactly once (T7-9: was assert-nothing)."""
    from custom_components.dreame_a2_mower.mower.actions import MowerAction

    b = _start_button(WriteResult.local_ok())
    await b.async_press()
    b.coordinator.dispatch_action.assert_awaited_once_with(
        MowerAction.START_MOWING, {}
    )


@pytest.mark.asyncio
async def test_start_button_rejected_raises_home_assistant_error():
    b = _start_button(
        WriteResult(delivered=True, accepted=False, code=-3, msg="nope")
    )
    with pytest.raises(HomeAssistantError) as exc:
        await b.async_press()
    # Entity context must NOT raise the service-only ServiceValidationError.
    assert not isinstance(exc.value, ServiceValidationError)


@pytest.mark.asyncio
async def test_start_button_not_delivered_raises_home_assistant_error():
    b = _start_button(WriteResult.not_delivered("asleep"))
    with pytest.raises(HomeAssistantError):
        await b.async_press()


# --------------------------------------------------------------------------
# T7-23 rejection matrix — the raise_for_write_result call sites that were
# happy-path-only: mow_edge / mow_spot / point+edge patrol / simple-action
# factory (service context) and lawn_mower pause / dock (entity context).
# --------------------------------------------------------------------------

_REJECTED = WriteResult(delivered=True, accepted=False, code=-3, msg="not supported")


def _svc_coord(monkeypatch, **methods):
    coord = MagicMock()
    coord.data = MowerState()
    coord.async_set_updated_data = MagicMock()
    for name, mock in methods.items():
        setattr(coord, name, mock)
    monkeypatch.setattr(services, "_coordinator_from_call", lambda hass, call: coord)
    return coord


@pytest.mark.asyncio
async def test_mow_edge_rejection_raises_service_validation(monkeypatch):
    _svc_coord(monkeypatch, dispatch_action=AsyncMock(return_value=_REJECTED))
    call = SimpleNamespace(hass=SimpleNamespace(), data={"contour_ids": [[1, 0]]})
    with pytest.raises(ServiceValidationError):
        await services._handle_mow_edge(call)


@pytest.mark.asyncio
async def test_mow_spot_rejection_raises_service_validation(monkeypatch):
    _svc_coord(monkeypatch, dispatch_action=AsyncMock(return_value=_REJECTED))
    call = SimpleNamespace(hass=SimpleNamespace(), data={"spot_ids": [2]})
    with pytest.raises(ServiceValidationError):
        await services._handle_mow_spot(call)


@pytest.mark.asyncio
async def test_start_point_patrol_rejection_raises(monkeypatch):
    coord = _svc_coord(
        monkeypatch, start_point_patrol=AsyncMock(return_value=_REJECTED)
    )
    coord._active_map_id = 0
    call = SimpleNamespace(hass=SimpleNamespace(), data={"point_ids": [1, 2]})
    with pytest.raises(ServiceValidationError):
        await services._handle_start_point_patrol(call)
    coord.start_point_patrol.assert_awaited_once_with(map_id=0, point_ids=[1, 2])


@pytest.mark.asyncio
async def test_start_edge_patrol_rejection_raises(monkeypatch):
    coord = _svc_coord(
        monkeypatch, start_edge_patrol=AsyncMock(return_value=_REJECTED)
    )
    coord._active_map_id = 0
    call = SimpleNamespace(hass=SimpleNamespace(), data={"contour_ids": [[1, 0]]})
    with pytest.raises(ServiceValidationError):
        await services._handle_start_edge_patrol(call)


@pytest.mark.asyncio
async def test_simple_action_factory_rejection_raises(monkeypatch):
    """The generic parameterless-action factory (recharge/find_bot/…) surfaces
    a device rejection as ServiceValidationError."""
    _svc_coord(monkeypatch, dispatch_action=AsyncMock(return_value=_REJECTED))
    handler = await services._handle_simple_action("FIND_BOT")
    call = SimpleNamespace(hass=SimpleNamespace(), data={})
    with pytest.raises(ServiceValidationError):
        await handler(call)


@pytest.mark.asyncio
async def test_lawn_mower_pause_rejection_raises_entity_error():
    lm = _lawn_mower(_REJECTED)
    with pytest.raises(HomeAssistantError) as exc:
        await lm.async_pause()
    assert not isinstance(exc.value, ServiceValidationError)


@pytest.mark.asyncio
async def test_lawn_mower_dock_rejection_raises_entity_error():
    lm = _lawn_mower(_REJECTED)
    with pytest.raises(HomeAssistantError) as exc:
        await lm.async_dock()
    assert not isinstance(exc.value, ServiceValidationError)
