"""Phase A1 Task 7: time entities with build_from_cfg_fn RMW from raw cfg.

Entities under test (all six that exist in time.py):
  dnd_start_time       / dnd_end_time         -> CFG.DND via build_dnd
  low_speed_at_night_start_time / _end_time   -> CFG.LOW via build_low
  charging_start_time  / charging_end_time    -> CFG.BAT via build_bat_charging

LIT start/end time entities do NOT exist in time.py (no MowerState fields
for LIT start_min / end_min), so they are not tested here.
"""
from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.dreame_a2_mower.time import DreameA2Time, DreameA2TimeEntityDescription, TIMES
from custom_components.dreame_a2_mower.control_honesty import ControlMode

from custom_components.dreame_a2_mower.cloud_client import WriteResult as _WR

# P2 Task 5: the coordinator write families return WriteResult, not bool.
_WR_ACCEPTED = _WR(delivered=True, accepted=True, code=0)
_WR_REJECTED = _WR(delivered=True, accepted=False, code=-3, msg="not supported")



def _find_desc(key: str) -> DreameA2TimeEntityDescription:
    for d in TIMES:
        if d.key == key:
            return d
    raise KeyError(key)


def _make_time(desc: DreameA2TimeEntityDescription, cfg: dict, *,
               control_mode: ControlMode = ControlMode.DEVICE_WRITE_UNPROVEN):
    """Build a minimal DreameA2Time bypassing __init__ to avoid coordinator deps."""
    from custom_components.dreame_a2_mower.mower.state import MowerState

    coord = SimpleNamespace()
    coord.data = MowerState()
    coord.cloud_state = SimpleNamespace(cfg=cfg)
    coord.write_setting = AsyncMock(return_value=_WR_ACCEPTED)

    ent = object.__new__(DreameA2Time)
    ent.coordinator = coord
    ent.entity_description = desc
    ent._control_mode = control_mode
    ent.async_write_ha_state = lambda: None
    return ent, coord


# ---------------------------------------------------------------------------
# dnd_start_time — DND start via build_dnd(raw, start=m)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dnd_start_time_rmw():
    """Setting DND start to 21:00 emits {"value":0,"time":[1260,420]}."""
    desc = _find_desc("dnd_start_time")
    # DND: [value=0, start=1260, end=420]
    ent, coord = _make_time(desc, {"DND": [0, 1260, 420]})

    await ent.async_set_value(datetime.time(21, 0))  # 21*60=1260 min

    coord.write_setting.assert_awaited_once()
    args, kwargs = coord.write_setting.call_args
    assert args[0] == "DND"
    assert args[1] == {"value": 0, "time": [1260, 420]}


@pytest.mark.asyncio
async def test_dnd_start_time_no_base_aborts():
    """With no DND base, write_setting must NOT be called."""
    desc = _find_desc("dnd_start_time")
    ent, coord = _make_time(desc, {})

    await ent.async_set_value(datetime.time(21, 0))

    coord.write_setting.assert_not_awaited()


# ---------------------------------------------------------------------------
# dnd_end_time — DND end via build_dnd(raw, end=m)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dnd_end_time_rmw():
    """Setting DND end to 07:00 emits {"value":0,"time":[1260,420]}."""
    desc = _find_desc("dnd_end_time")
    # DND: [value=0, start=1260, end=420]
    ent, coord = _make_time(desc, {"DND": [0, 1260, 420]})

    await ent.async_set_value(datetime.time(7, 0))  # 7*60=420 min

    coord.write_setting.assert_awaited_once()
    args, kwargs = coord.write_setting.call_args
    assert args[0] == "DND"
    assert args[1] == {"value": 0, "time": [1260, 420]}


@pytest.mark.asyncio
async def test_dnd_end_time_preserves_start_from_raw():
    """When only end changes, start is preserved from the raw cfg."""
    desc = _find_desc("dnd_end_time")
    # raw start=1320 (22:00)
    ent, coord = _make_time(desc, {"DND": [1, 1320, 480]})

    await ent.async_set_value(datetime.time(8, 30))  # 8*60+30=510

    args, _ = coord.write_setting.call_args
    assert args[1] == {"value": 1, "time": [1320, 510]}


@pytest.mark.asyncio
async def test_dnd_end_time_no_base_aborts():
    """With no DND base, write_setting must NOT be called."""
    desc = _find_desc("dnd_end_time")
    ent, coord = _make_time(desc, {})

    await ent.async_set_value(datetime.time(7, 0))

    coord.write_setting.assert_not_awaited()


# ---------------------------------------------------------------------------
# low_speed_at_night_start_time — LOW start via build_low(raw, start=m)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_low_start_time_rmw():
    """Setting LOW start to 22:00 emits {"value":1,"time":[1320,360]}."""
    desc = _find_desc("low_speed_at_night_start_time")
    # LOW: [value=1, start=1320, end=360]
    ent, coord = _make_time(desc, {"LOW": [1, 1320, 360]})

    await ent.async_set_value(datetime.time(22, 0))  # 22*60=1320

    coord.write_setting.assert_awaited_once()
    args, kwargs = coord.write_setting.call_args
    assert args[0] == "LOW"
    assert args[1] == {"value": 1, "time": [1320, 360]}


@pytest.mark.asyncio
async def test_low_start_time_no_base_aborts():
    desc = _find_desc("low_speed_at_night_start_time")
    ent, coord = _make_time(desc, {})

    await ent.async_set_value(datetime.time(22, 0))

    coord.write_setting.assert_not_awaited()


# ---------------------------------------------------------------------------
# low_speed_at_night_end_time — LOW end via build_low(raw, end=m)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_low_end_time_rmw():
    """Setting LOW end to 06:00 emits {"value":1,"time":[1320,360]}."""
    desc = _find_desc("low_speed_at_night_end_time")
    # LOW: [value=1, start=1320, end=360]
    ent, coord = _make_time(desc, {"LOW": [1, 1320, 360]})

    await ent.async_set_value(datetime.time(6, 0))  # 6*60=360

    coord.write_setting.assert_awaited_once()
    args, kwargs = coord.write_setting.call_args
    assert args[0] == "LOW"
    assert args[1] == {"value": 1, "time": [1320, 360]}


@pytest.mark.asyncio
async def test_low_end_time_no_base_aborts():
    desc = _find_desc("low_speed_at_night_end_time")
    ent, coord = _make_time(desc, {})

    await ent.async_set_value(datetime.time(6, 0))

    coord.write_setting.assert_not_awaited()


# ---------------------------------------------------------------------------
# charging_start_time — BAT start via build_bat_charging(raw, start=m)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_charging_start_time_rmw():
    """Setting BAT charging start to 18:00 emits {"type":"charging","value":[1,1080,480]}."""
    desc = _find_desc("charging_start_time")
    # BAT: [recharge=15, resume=95, flag=1, custom_en=1, start=1080, end=480]
    ent, coord = _make_time(desc, {"BAT": [15, 95, 1, 1, 1080, 480]})

    await ent.async_set_value(datetime.time(18, 0))  # 18*60=1080

    coord.write_setting.assert_awaited_once()
    args, kwargs = coord.write_setting.call_args
    assert args[0] == "BAT"
    assert args[1] == {"type": "charging", "value": [1, 1080, 480]}


@pytest.mark.asyncio
async def test_charging_start_time_preserves_end_from_raw():
    """end value is preserved from raw cfg, not from MowerState."""
    desc = _find_desc("charging_start_time")
    # raw end=300 (05:00)
    ent, coord = _make_time(desc, {"BAT": [15, 95, 1, 1, 1080, 300]})

    await ent.async_set_value(datetime.time(20, 0))  # 20*60=1200

    args, _ = coord.write_setting.call_args
    assert args[1] == {"type": "charging", "value": [1, 1200, 300]}


@pytest.mark.asyncio
async def test_charging_start_time_no_base_aborts():
    desc = _find_desc("charging_start_time")
    ent, coord = _make_time(desc, {})

    await ent.async_set_value(datetime.time(18, 0))

    coord.write_setting.assert_not_awaited()


# ---------------------------------------------------------------------------
# charging_end_time — BAT end via build_bat_charging(raw, end=m)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_charging_end_time_rmw():
    """Setting BAT charging end to 08:00 emits {"type":"charging","value":[1,1080,480]}."""
    desc = _find_desc("charging_end_time")
    # BAT: [recharge=15, resume=95, flag=1, custom_en=1, start=1080, end=480]
    ent, coord = _make_time(desc, {"BAT": [15, 95, 1, 1, 1080, 480]})

    await ent.async_set_value(datetime.time(8, 0))  # 8*60=480

    coord.write_setting.assert_awaited_once()
    args, kwargs = coord.write_setting.call_args
    assert args[0] == "BAT"
    assert args[1] == {"type": "charging", "value": [1, 1080, 480]}


@pytest.mark.asyncio
async def test_charging_end_time_preserves_start_from_raw():
    """start value is preserved from raw cfg, not from MowerState."""
    desc = _find_desc("charging_end_time")
    # raw start=1200 (20:00)
    ent, coord = _make_time(desc, {"BAT": [15, 95, 1, 0, 1200, 480]})

    await ent.async_set_value(datetime.time(10, 0))  # 10*60=600

    args, _ = coord.write_setting.call_args
    assert args[1] == {"type": "charging", "value": [0, 1200, 600]}


@pytest.mark.asyncio
async def test_charging_end_time_no_base_aborts():
    desc = _find_desc("charging_end_time")
    ent, coord = _make_time(desc, {})

    await ent.async_set_value(datetime.time(8, 0))

    coord.write_setting.assert_not_awaited()


# ---------------------------------------------------------------------------
# read_only guard: control_mode=READ_ONLY_NOOP entities must not write
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_only_entity_does_not_write():
    """When control_mode is READ_ONLY_NOOP (current default), no write should occur."""
    desc = _find_desc("dnd_start_time")
    ent, coord = _make_time(desc, {"DND": [0, 1260, 420]},
                            control_mode=ControlMode.READ_ONLY_NOOP)
    # Inject the _reject_readonly_write no-op (normally from _ControlHonestyMixin)
    ent._reject_readonly_write = AsyncMock()

    await ent.async_set_value(datetime.time(21, 0))

    coord.write_setting.assert_not_awaited()
