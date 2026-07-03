"""Phase A1: descriptor switches with build_from_cfg_fn RMW from raw cfg."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.dreame_a2_mower import _switch_base as sb
from custom_components.dreame_a2_mower.control_honesty import ControlMode

from custom_components.dreame_a2_mower.cloud_client import WriteResult as _WR

# P2 Task 5: the coordinator write families return WriteResult, not bool.
_WR_ACCEPTED = _WR(delivered=True, accepted=True, code=0)
_WR_REJECTED = _WR(delivered=True, accepted=False, code=-3, msg="not supported")



def _make_switch(desc, cfg):
    """Build a minimal DreameA2Switch, bypassing __init__ to avoid coordinator deps."""
    coord = SimpleNamespace()
    coord.data = SimpleNamespace()
    coord.cloud_state = SimpleNamespace(cfg=cfg)
    coord.write_setting = AsyncMock(return_value=_WR_ACCEPTED)

    ent = object.__new__(sb.DreameA2Switch)
    ent.coordinator = coord
    ent.entity_description = desc
    ent._control_mode = ControlMode.DEVICE_WRITABLE
    ent.async_write_ha_state = lambda: None
    return ent, coord


@pytest.mark.asyncio
async def test_build_from_cfg_fn_rmw_calls_write_setting():
    desc = sb.DreameA2SwitchEntityDescription(
        key="dnd", name="DND", cfg_key="DND",
        build_from_cfg_fn=lambda raw, enabled: {"value": int(enabled), "time": [raw[1], raw[2]]},
        value_fn=lambda s: False,
    )
    ent, coord = _make_switch(desc, {"DND": [0, 1260, 420]})
    await ent.async_turn_on()
    coord.write_setting.assert_awaited_once()
    args, kwargs = coord.write_setting.call_args
    assert args[0] == "DND"
    assert args[1] == {"value": 1, "time": [1260, 420]}


@pytest.mark.asyncio
async def test_build_from_cfg_fn_none_base_reverts():
    desc = sb.DreameA2SwitchEntityDescription(
        key="rec", name="REC", cfg_key="REC",
        build_from_cfg_fn=lambda raw, enabled: None,  # no base
        value_fn=lambda s: False,
    )
    ent, coord = _make_switch(desc, {})  # REC absent
    await ent.async_turn_on()
    coord.write_setting.assert_not_awaited()  # aborted, no write
