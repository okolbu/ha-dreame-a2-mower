import json
from pathlib import Path

import pytest

from custom_components.dreame_a2_mower.protocol import cfg_payloads as cp

_FIX = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "cfg_envelopes_2026-06-09.json").read_text()
)
READS = _FIX["reads"]
WRITES = _FIX["writes"]


def test_build_dnd_matches_capture():
    out = cp.build_dnd(READS["DND"], value=True)
    assert out == {"value": 1, "time": [1260, 420]}


def test_build_dnd_changes_time_preserves_value():
    out = cp.build_dnd(READS["DND"], start=1260, end=420)
    assert out == {"value": 0, "time": [1260, 420]}


def test_build_low_matches_capture():
    out = cp.build_low(READS["LOW"], value=False)
    assert out == {"value": 0, "time": [1200, 480]}


def test_build_wrp_preserves_sen_and_defaults():
    out = cp.build_wrp(READS["WRP"], value=False)
    assert out == {"value": 0, "time": 4, "sen": 1}


def test_build_wrp_change_time():
    out = cp.build_wrp(READS["WRP"], time=5)
    assert out == {"value": 1, "time": 5, "sen": 1}


def test_build_bat_charging_matches_capture():
    out = cp.build_bat_charging(READS["BAT"], enabled=False)
    assert out == {"type": "charging", "value": [0, 1080, 480]}


def test_build_bat_power_preserves_flag():
    out = cp.build_bat_power(READS["BAT"], recharge=15, resume=95)
    assert out == {"type": "power", "value": [15, 95, 1]}


def test_build_lit_toggle_working_preserves_rest():
    out = cp.build_lit(READS["LIT"], working=False)
    assert out == {"value": 0, "time": [480, 1200], "light": [1, 0, 1, 1], "fill": 1}


def test_build_lit_period_on():
    out = cp.build_lit(READS["LIT"], value=True)
    assert out == {"value": 1, "time": [480, 1200], "light": [1, 1, 1, 1], "fill": 1}


def test_build_rec_toggle_value_preserves_mode_report():
    out = cp.build_rec(READS["REC"], value=False)
    assert out == {"value": 0, "sen": 1, "mode": [1, 1, 1, 1], "report": [0, 1, 3]}


def test_build_rec_change_sensitivity():
    out = cp.build_rec(READS["REC"], sen=2)
    assert out == {"value": 1, "sen": 2, "mode": [1, 1, 1, 1], "report": [0, 1, 3]}


def test_build_lang_voice():
    out = cp.build_lang(READS["LANG"], kind="voice", value=0)
    assert out == {"type": "voice", "value": 0}


def test_build_lang_text():
    out = cp.build_lang(READS["LANG"], kind="text", value=7)
    assert out == {"type": "text", "value": 7}


@pytest.mark.parametrize("fn,args", [
    (cp.build_dnd, {"value": True}), (cp.build_low, {"value": True}),
    (cp.build_lit, {"value": True}), (cp.build_rec, {"value": True}),
    (cp.build_bat_charging, {"enabled": True}), (cp.build_bat_power, {"recharge": 10, "resume": 90}),
    (cp.build_wrp, {"value": True}),
])
def test_builders_return_none_on_empty_base(fn, args):
    assert fn(None, **args) is None
    assert fn([], **args) is None


PRE_BASE = _FIX["pre"]["baseline"]  # [0,0,0,0,55,1,8,1,0,1,1,2,1,20,10,7,1,2,0]


def test_apply_pre_sets_index_and_scope():
    out = cp.apply_pre(PRE_BASE, map_idx=1, index=4, value=60)
    assert out[0] == 0      # version write-byte
    assert out[1] == 1      # map idx
    assert out[2] == 0      # General region
    assert out[4] == 60     # height changed
    assert out[3] == PRE_BASE[3] and out[5] == PRE_BASE[5] and out[16] == PRE_BASE[16]
    assert len(out) == len(PRE_BASE)


def test_apply_pre_efficiency_passthrough():
    out = cp.apply_pre(PRE_BASE, map_idx=0, index=3, value=1)
    assert out[3] == 1 and out[1] == 0 and out[2] == 0


def test_apply_pre_ai_bit_set_and_clear():
    out = cp.apply_pre_ai_bit(PRE_BASE, map_idx=0, bit=0, on=False)  # baseline [15]=7
    assert out[15] == 6
    base6 = list(PRE_BASE); base6[15] = 6
    out2 = cp.apply_pre_ai_bit(base6, map_idx=0, bit=0, on=True)
    assert out2[15] == 7


def test_apply_pre_none_base():
    assert cp.apply_pre(None, map_idx=0, index=4, value=60) is None
    assert cp.apply_pre([0, 0], map_idx=0, index=16, value=1) is None  # too short for idx 16
    assert cp.apply_pre_ai_bit(None, map_idx=0, bit=0, on=True) is None
