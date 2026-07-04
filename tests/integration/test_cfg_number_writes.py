"""Phase A1: number entities with build_from_cfg_fn RMW from raw cfg."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.dreame_a2_mower.number import DreameA2Number, NUMBERS
from custom_components.dreame_a2_mower.control_honesty import ControlMode

from custom_components.dreame_a2_mower.cloud_client import WriteResult as _WR

# P2 Task 5: the coordinator write families return WriteResult, not bool.
_WR_ACCEPTED = _WR(delivered=True, accepted=True, code=0)
_WR_REJECTED = _WR(delivered=True, accepted=False, code=-3, msg="not supported")



def _find_desc(key: str):
    for d in NUMBERS:
        if d.key == key:
            return d
    raise KeyError(key)


def _make_number(desc, cfg, *, control_mode=ControlMode.DEVICE_WRITABLE):
    """Build a minimal DreameA2Number, bypassing __init__ to avoid coordinator deps."""
    from custom_components.dreame_a2_mower.state import MowerState

    coord = SimpleNamespace()
    coord.data = MowerState()
    coord.cloud_state = SimpleNamespace(cfg=cfg)
    coord.write_setting = AsyncMock(return_value=_WR_ACCEPTED)

    ent = object.__new__(DreameA2Number)
    ent.coordinator = coord
    ent.entity_description = desc
    ent._control_mode = control_mode
    ent.async_write_ha_state = lambda: None
    return ent, coord


# ---------------------------------------------------------------------------
# auto_recharge_battery_pct  — BAT[0] via build_bat_power
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_recharge_battery_pct_rmw():
    """Setting auto_recharge to 20 should emit BAT power-payload with [20, 95, 1]."""
    desc = _find_desc("auto_recharge_battery_pct")
    # BAT: [recharge=15, resume=95, flag=1, custom_en, start, end]
    ent, coord = _make_number(desc, {"BAT": [15, 95, 1, 1, 1080, 480]})

    await ent.async_set_native_value(20)

    coord.write_setting.assert_awaited_once()
    args, kwargs = coord.write_setting.call_args
    assert args[0] == "BAT"
    assert args[1] == {"type": "power", "value": [20, 95, 1]}
    # field_updates should include the optimistic field
    assert kwargs.get("field_updates") == {"auto_recharge_battery_pct": 20}


@pytest.mark.asyncio
async def test_auto_recharge_battery_pct_preserves_resume_from_raw():
    """resume value comes from raw cfg, not from MowerState."""
    desc = _find_desc("auto_recharge_battery_pct")
    # raw resume=88 — MowerState default would be 95
    ent, coord = _make_number(desc, {"BAT": [15, 88, 1, 0, 0, 0]})

    await ent.async_set_native_value(20)

    args, _ = coord.write_setting.call_args
    assert args[1] == {"type": "power", "value": [20, 88, 1]}


@pytest.mark.asyncio
async def test_auto_recharge_battery_pct_no_base_aborts():
    """When cfg has no BAT key, write_setting must NOT be called."""
    desc = _find_desc("auto_recharge_battery_pct")
    ent, coord = _make_number(desc, {})

    await ent.async_set_native_value(20)

    coord.write_setting.assert_not_awaited()


# ---------------------------------------------------------------------------
# resume_battery_pct  — BAT[1] via build_bat_power
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_battery_pct_rmw():
    """Setting resume to 90 should emit BAT power-payload with [15, 90, 1]."""
    desc = _find_desc("resume_battery_pct")
    ent, coord = _make_number(desc, {"BAT": [15, 95, 1, 1, 1080, 480]})

    await ent.async_set_native_value(90)

    coord.write_setting.assert_awaited_once()
    args, kwargs = coord.write_setting.call_args
    assert args[0] == "BAT"
    assert args[1] == {"type": "power", "value": [15, 90, 1]}
    assert kwargs.get("field_updates") == {"resume_battery_pct": 90}


@pytest.mark.asyncio
async def test_resume_battery_pct_preserves_recharge_from_raw():
    """recharge value comes from raw cfg, not from MowerState."""
    desc = _find_desc("resume_battery_pct")
    # raw recharge=20
    ent, coord = _make_number(desc, {"BAT": [20, 95, 1, 0, 0, 0]})

    await ent.async_set_native_value(90)

    args, _ = coord.write_setting.call_args
    assert args[1] == {"type": "power", "value": [20, 90, 1]}


@pytest.mark.asyncio
async def test_resume_battery_pct_no_base_aborts():
    """When cfg has no BAT key, write_setting must NOT be called."""
    desc = _find_desc("resume_battery_pct")
    ent, coord = _make_number(desc, {})

    await ent.async_set_native_value(90)

    coord.write_setting.assert_not_awaited()


# ---------------------------------------------------------------------------
# human_presence_alert_sensitivity  — REC[1] via build_rec
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_human_presence_alert_sensitivity_rmw():
    """Setting sensitivity to 2 (High) should emit full REC payload."""
    desc = _find_desc("human_presence_alert_sensitivity")
    # REC: [value=1, sen=1, m0=1, m1=1, m2=1, m3=1, r0=0, r1=1, r2=3]
    ent, coord = _make_number(desc, {"REC": [1, 1, 1, 1, 1, 1, 0, 1, 3]})

    await ent.async_set_native_value(2)

    coord.write_setting.assert_awaited_once()
    args, kwargs = coord.write_setting.call_args
    assert args[0] == "REC"
    assert args[1] == {
        "value": 1,
        "sen": 2,
        "mode": [1, 1, 1, 1],
        "report": [0, 1, 3],
    }
    assert kwargs.get("field_updates") == {"human_presence_alert_sensitivity": 2}


@pytest.mark.asyncio
async def test_human_presence_alert_sensitivity_preserves_value_from_raw():
    """enabled flag (value) comes from raw cfg, not from MowerState."""
    desc = _find_desc("human_presence_alert_sensitivity")
    # value=0 (disabled)
    ent, coord = _make_number(desc, {"REC": [0, 1, 1, 1, 1, 1, 0, 1, 3]})

    await ent.async_set_native_value(2)

    args, _ = coord.write_setting.call_args
    assert args[1]["value"] == 0  # preserved from raw


@pytest.mark.asyncio
async def test_human_presence_alert_sensitivity_no_base_aborts():
    """When cfg has no REC key, write_setting must NOT be called."""
    desc = _find_desc("human_presence_alert_sensitivity")
    ent, coord = _make_number(desc, {})

    await ent.async_set_native_value(2)

    coord.write_setting.assert_not_awaited()
