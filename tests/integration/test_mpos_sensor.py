"""Tests for the MPOS diagnostic sensor value/attrs helpers."""
from custom_components.dreame_a2_mower.entities.sensor.device import _mpos_value, _mpos_attrs
from custom_components.dreame_a2_mower.mower.state import MowerState


class _Coord:
    def __init__(self, state): self.data = state


def test_mpos_value_blank_when_unset():
    assert _mpos_value(_Coord(MowerState())) is None


def test_mpos_value_formats_triple():
    s = MowerState(mpos_x=95, mpos_y=-4, mpos_yaw=0)
    assert _mpos_value(_Coord(s)) == "95, -4, 0"


def test_mpos_attrs_exposes_raw_fields_and_result():
    s = MowerState(mpos_x=95, mpos_y=-4, mpos_yaw=0, mpos_updated_unix=1781000000, mpos_last_result="ok")
    a = _mpos_attrs(_Coord(s))
    assert a["x"] == 95 and a["y"] == -4 and a["yaw"] == 0
    assert a["last_result"] == "ok"
    assert a["last_updated"] is not None        # ISO timestamp
    assert "raw" in a["note"].lower()           # honesty note present


def test_mpos_attrs_blank_timestamp_when_never_refreshed():
    a = _mpos_attrs(_Coord(MowerState()))
    assert a["last_updated"] is None and a["last_result"] is None
