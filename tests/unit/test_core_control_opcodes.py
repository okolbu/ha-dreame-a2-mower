from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest

from custom_components.dreame_a2_mower.mower.actions import ACTION_TABLE, MowerAction
from custom_components.dreame_a2_mower.coordinator._writes import _WritesMixin


def test_pause_stop_dock_have_routed_opcodes():
    assert ACTION_TABLE[MowerAction.PAUSE]["routed_o"] == 4
    assert ACTION_TABLE[MowerAction.STOP]["routed_o"] == 3
    assert ACTION_TABLE[MowerAction.DOCK]["routed_o"] == 6
    assert ACTION_TABLE[MowerAction.RECHARGE]["routed_o"] == 6


def test_resume_and_cancel_dock_return_exist():
    assert ACTION_TABLE[MowerAction.RESUME]["routed_o"] == 5
    assert ACTION_TABLE[MowerAction.CANCEL_DOCK_RETURN]["routed_o"] == 13
    assert "payload_fn" not in ACTION_TABLE[MowerAction.RESUME]
    assert "payload_fn" not in ACTION_TABLE[MowerAction.CANCEL_DOCK_RETURN]


def _coord():
    c = _WritesMixin()
    c._cloud = SimpleNamespace(
        routed_action=MagicMock(return_value={"out": [{"r": 0}]}),
        action=MagicMock(return_value={"out": [{"r": 0}]}),
    )
    async def _exec(fn, *a):
        return fn(*a)
    c.hass = SimpleNamespace(async_add_executor_job=AsyncMock(side_effect=_exec))
    return c


@pytest.mark.asyncio
@pytest.mark.parametrize("action,op", [
    (MowerAction.PAUSE, 4), (MowerAction.STOP, 3), (MowerAction.DOCK, 6),
    (MowerAction.RECHARGE, 6), (MowerAction.RESUME, 5), (MowerAction.CANCEL_DOCK_RETURN, 13),
])
async def test_dispatch_uses_routed_opcode(action, op):
    c = _coord()
    await c.dispatch_action(action, {})
    c._cloud.routed_action.assert_called_once()
    assert c._cloud.routed_action.call_args[0][0] == op
    c._cloud.action.assert_not_called()
