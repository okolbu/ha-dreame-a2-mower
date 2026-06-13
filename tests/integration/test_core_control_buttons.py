"""Tests for the Resume and Cancel-dock-return buttons (Phase B, Task 2)."""
from unittest.mock import AsyncMock, MagicMock
import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.dreame_a2_mower import button as btn
from custom_components.dreame_a2_mower.cloud_client import WriteResult
from custom_components.dreame_a2_mower.mower.actions import MowerAction
from custom_components.dreame_a2_mower.control_honesty import resolve_control_mode, ControlMode


def _coord():
    """Minimal coordinator mock sufficient for _DreameA2ActionButton.__init__.

    dispatch_action returns an explicit *accepted* WriteResult so the
    happy-path assertions are meaningful — a bare AsyncMock would return a
    MagicMock whose truthy ``.accepted`` makes raise_for_write_result a no-op
    by accident.
    """
    coord = MagicMock()
    coord.sn = "G2408TEST"
    coord.dispatch_action = AsyncMock(return_value=WriteResult.local_ok())
    return coord


@pytest.mark.asyncio
async def test_resume_button_dispatches_resume():
    b = btn.DreameA2ResumeMowingButton(_coord())
    await b.async_press()
    b.coordinator.dispatch_action.assert_awaited_once()
    assert b.coordinator.dispatch_action.call_args[0][0] == MowerAction.RESUME


@pytest.mark.asyncio
async def test_cancel_dock_return_button_dispatches():
    b = btn.DreameA2CancelDockReturnButton(_coord())
    await b.async_press()
    b.coordinator.dispatch_action.assert_awaited_once()
    assert b.coordinator.dispatch_action.call_args[0][0] == MowerAction.CANCEL_DOCK_RETURN


@pytest.mark.asyncio
async def test_action_button_raises_on_device_rejection():
    """A delivered-but-rejected WriteResult surfaces as a HomeAssistantError."""
    coord = _coord()
    coord.dispatch_action = AsyncMock(
        return_value=WriteResult(delivered=True, accepted=False, code=-3, msg="nope")
    )
    b = btn.DreameA2ResumeMowingButton(coord)
    with pytest.raises(HomeAssistantError):
        await b.async_press()


@pytest.mark.asyncio
async def test_action_button_raises_on_not_delivered():
    """A not-delivered WriteResult surfaces as a HomeAssistantError (retryable)."""
    coord = _coord()
    coord.dispatch_action = AsyncMock(return_value=WriteResult.not_delivered("asleep"))
    b = btn.DreameA2CancelDockReturnButton(coord)
    with pytest.raises(HomeAssistantError):
        await b.async_press()


def test_new_buttons_writable():
    assert resolve_control_mode(platform="button", key="resume_mowing") == ControlMode.DEVICE_WRITABLE
    assert resolve_control_mode(platform="button", key="cancel_dock_return") == ControlMode.DEVICE_WRITABLE
