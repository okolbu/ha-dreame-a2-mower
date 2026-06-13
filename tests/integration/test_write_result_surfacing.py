"""Task B acceptance tests — write rejections surface as HA exceptions.

Covers the plan's §1.2-B acceptance criterion:
  - mow_zone SERVICE handler raises ServiceValidationError on a device-rejected
    (r=-3 / delivered-but-not-accepted) result, and HomeAssistantError on a
    not-delivered result.
  - The Start lawn_mower command and the Start button raise HomeAssistantError
    (entity context) on a not-accepted result.
  - An accepted result does NOT raise (happy path).
"""
import asyncio
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
async def test_mow_zone_accepted_does_not_raise(monkeypatch):
    _mow_zone_coord(monkeypatch, WriteResult.local_ok())
    # No exception expected.
    await services._handle_mow_zone(_mow_zone_call())


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
async def test_lawn_mower_start_accepted_does_not_raise():
    lm = _lawn_mower(WriteResult.local_ok())
    await lm.async_start_mowing()


@pytest.mark.asyncio
async def test_lawn_mower_start_rejected_raises_home_assistant_error():
    lm = _lawn_mower(
        WriteResult(delivered=True, accepted=False, code=-3, msg="nope")
    )
    with pytest.raises(HomeAssistantError):
        await lm.async_start_mowing()


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
async def test_start_button_accepted_does_not_raise():
    b = _start_button(WriteResult.local_ok())
    await b.async_press()


@pytest.mark.asyncio
async def test_start_button_rejected_raises_home_assistant_error():
    b = _start_button(
        WriteResult(delivered=True, accepted=False, code=-3, msg="nope")
    )
    with pytest.raises(HomeAssistantError):
        await b.async_press()


@pytest.mark.asyncio
async def test_start_button_not_delivered_raises_home_assistant_error():
    b = _start_button(WriteResult.not_delivered("asleep"))
    with pytest.raises(HomeAssistantError):
        await b.async_press()
