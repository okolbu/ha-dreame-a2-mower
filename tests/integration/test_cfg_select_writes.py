"""Phase A1: select descriptors with build_from_cfg_fn RMW from raw cfg.

Tests three selects that use the new build_from_cfg_fn path:
  - voice_language  (LANG, kind="voice")
  - lcd_language    (LANG, kind="text")
  - rain_protection_resume_hours (WRP, sets time)
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.dreame_a2_mower.entities.select import global_ as sg
from custom_components.dreame_a2_mower.control_honesty import ControlMode

from custom_components.dreame_a2_mower.cloud_client import WriteResult as _WR

# P2 Task 5: the coordinator write families return WriteResult, not bool.
_WR_ACCEPTED = _WR(delivered=True, accepted=True, code=0)
_WR_REJECTED = _WR(delivered=True, accepted=False, code=-3, msg="not supported")



def _make_select(desc, cfg):
    """Build a minimal DreameA2SettingSelect, bypassing __init__ to avoid coordinator deps."""
    coord = SimpleNamespace()
    coord.data = SimpleNamespace(
        rain_protection_enabled=True,
        rain_protection_resume_hours=4,
        language_voice_idx=7,
        language_text_idx=0,
        language_code="text=0,voice=7",
        pre_zone_id=0,
        pre_mowing_height_mm=60,
        pre_mowing_efficiency=0,
        navigation_path_smart=False,
    )
    coord.cloud_state = SimpleNamespace(cfg=cfg)
    coord.write_setting = AsyncMock(return_value=_WR_ACCEPTED)

    ent = object.__new__(sg.DreameA2SettingSelect)
    ent.coordinator = coord
    ent.entity_description = desc
    ent._control_mode = ControlMode.DEVICE_WRITABLE
    ent.async_write_ha_state = lambda: None
    return ent, coord


def _get_desc(key):
    """Look up a descriptor from SETTING_SELECTS by key."""
    for d in sg.SETTING_SELECTS:
        if d.key == key:
            return d
    raise KeyError(f"No SETTING_SELECTS descriptor with key={key!r}")


# ---------------------------------------------------------------------------
# voice_language
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_voice_language_english_idx0():
    """Selecting English (idx 0) with cfg LANG=[7,7] writes {type:'voice', value:0}."""
    desc = _get_desc("voice_language")
    ent, coord = _make_select(desc, {"LANG": [7, 7]})
    await ent.async_select_option("English")
    coord.write_setting.assert_awaited_once()
    args, _ = coord.write_setting.call_args
    assert args[0] == "LANG"
    assert args[1] == {"type": "voice", "value": 0}


@pytest.mark.asyncio
async def test_voice_language_norwegian_idx7():
    """Selecting Norwegian (idx 7) writes {type:'voice', value:7}."""
    desc = _get_desc("voice_language")
    ent, coord = _make_select(desc, {"LANG": [0, 0]})
    await ent.async_select_option("Norwegian")
    coord.write_setting.assert_awaited_once()
    args, _ = coord.write_setting.call_args
    assert args[0] == "LANG"
    assert args[1] == {"type": "voice", "value": 7}


@pytest.mark.asyncio
async def test_voice_language_danish_idx9():
    """Selecting Danish (idx 9) writes {type:'voice', value:9}."""
    desc = _get_desc("voice_language")
    ent, coord = _make_select(desc, {"LANG": [0, 0]})
    await ent.async_select_option("Danish")
    coord.write_setting.assert_awaited_once()
    args, _ = coord.write_setting.call_args
    assert args[1] == {"type": "voice", "value": 9}


# ---------------------------------------------------------------------------
# lcd_language
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lcd_language_norwegian_idx7():
    """Selecting Norwegian (text idx 7) writes {type:'text', value:7}."""
    desc = _get_desc("lcd_language")
    ent, coord = _make_select(desc, {"LANG": [0, 7]})
    await ent.async_select_option("Norwegian")
    coord.write_setting.assert_awaited_once()
    args, _ = coord.write_setting.call_args
    assert args[0] == "LANG"
    assert args[1] == {"type": "text", "value": 7}


@pytest.mark.asyncio
async def test_lcd_language_danish_idx0():
    """Selecting Danish (text idx 0) writes {type:'text', value:0}."""
    desc = _get_desc("lcd_language")
    ent, coord = _make_select(desc, {"LANG": [0, 7]})
    await ent.async_select_option("Danish")
    coord.write_setting.assert_awaited_once()
    args, _ = coord.write_setting.call_args
    assert args[0] == "LANG"
    assert args[1] == {"type": "text", "value": 0}


@pytest.mark.asyncio
async def test_lcd_language_english_idx2():
    """Selecting English (text idx 2) writes {type:'text', value:2}."""
    desc = _get_desc("lcd_language")
    ent, coord = _make_select(desc, {"LANG": [0, 7]})
    await ent.async_select_option("English")
    coord.write_setting.assert_awaited_once()
    args, _ = coord.write_setting.call_args
    assert args[1] == {"type": "text", "value": 2}


# ---------------------------------------------------------------------------
# rain_protection_resume_hours
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wrp_resume_6h_writes_correct_payload():
    """Selecting '6 hours' with cfg WRP=[1,4] writes {value:1, time:6, sen:1}."""
    desc = _get_desc("rain_protection_resume_hours")
    ent, coord = _make_select(desc, {"WRP": [1, 4]})
    await ent.async_select_option("6 hours")
    coord.write_setting.assert_awaited_once()
    args, _ = coord.write_setting.call_args
    assert args[0] == "WRP"
    assert args[1] == {"value": 1, "time": 6, "sen": 1}


@pytest.mark.asyncio
async def test_wrp_resume_0h_writes_correct_payload():
    """Selecting '0 hours' (never resume) with WRP=[0,4] writes {value:0, time:0, sen:1}."""
    desc = _get_desc("rain_protection_resume_hours")
    ent, coord = _make_select(desc, {"WRP": [0, 4]})
    await ent.async_select_option("0 hours")
    coord.write_setting.assert_awaited_once()
    args, _ = coord.write_setting.call_args
    assert args[0] == "WRP"
    assert args[1] == {"value": 0, "time": 0, "sen": 1}


@pytest.mark.asyncio
async def test_wrp_resume_1h_label():
    """Selecting '1 hour' (singular) with WRP=[1,2] writes {value:1, time:1, sen:1}."""
    desc = _get_desc("rain_protection_resume_hours")
    ent, coord = _make_select(desc, {"WRP": [1, 2]})
    await ent.async_select_option("1 hour")
    coord.write_setting.assert_awaited_once()
    args, _ = coord.write_setting.call_args
    assert args[1] == {"value": 1, "time": 1, "sen": 1}


@pytest.mark.asyncio
async def test_wrp_no_base_aborts_write():
    """rain_protection_resume_hours with no WRP in cfg must NOT call write_setting."""
    desc = _get_desc("rain_protection_resume_hours")
    ent, coord = _make_select(desc, {})  # WRP absent
    await ent.async_select_option("3 hours")
    coord.write_setting.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrp_short_base_aborts_write():
    """WRP=[1] (too short) must also abort."""
    desc = _get_desc("rain_protection_resume_hours")
    ent, coord = _make_select(desc, {"WRP": [1]})
    await ent.async_select_option("3 hours")
    coord.write_setting.assert_not_awaited()
