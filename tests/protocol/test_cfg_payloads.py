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
])
def test_builders_return_none_on_empty_base(fn, args):
    assert fn(None, **args) is None
    assert fn([], **args) is None
