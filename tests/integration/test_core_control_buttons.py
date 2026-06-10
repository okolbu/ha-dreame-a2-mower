"""Tests for the Resume and Cancel-dock-return buttons (Phase B, Task 2)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest

from custom_components.dreame_a2_mower import button as btn
from custom_components.dreame_a2_mower.mower.actions import MowerAction
from custom_components.dreame_a2_mower.control_honesty import resolve_control_mode, ControlMode


def _coord():
    """Minimal coordinator mock sufficient for _DreameA2ActionButton.__init__."""
    coord = MagicMock()
    coord.sn = "G2408TEST"
    coord.dispatch_action = AsyncMock()
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


def test_new_buttons_writable():
    assert resolve_control_mode(platform="button", key="resume_mowing") == ControlMode.DEVICE_WRITABLE
    assert resolve_control_mode(platform="button", key="cancel_dock_return") == ControlMode.DEVICE_WRITABLE
