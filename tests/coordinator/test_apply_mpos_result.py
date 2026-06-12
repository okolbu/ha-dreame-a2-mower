from custom_components.dreame_a2_mower.coordinator._refreshers import apply_mpos_result
from custom_components.dreame_a2_mower.mower.state import MowerState


def test_apply_ok_sets_fields_and_timestamp():
    s = MowerState()
    out = apply_mpos_result(s, {"result": "ok", "x": 95, "y": -4, "yaw": 0}, now_unix=1781000000)
    assert (out.mpos_x, out.mpos_y, out.mpos_yaw) == (95, -4, 0)
    assert out.mpos_updated_unix == 1781000000
    assert out.mpos_last_result == "ok"


def test_apply_idle_keeps_values_updates_result_only():
    s = MowerState(mpos_x=95, mpos_y=-4, mpos_yaw=0, mpos_updated_unix=1780000000, mpos_last_result="ok")
    out = apply_mpos_result(s, {"result": "idle"}, now_unix=1781000000)
    assert (out.mpos_x, out.mpos_y, out.mpos_yaw) == (95, -4, 0)   # unchanged
    assert out.mpos_updated_unix == 1780000000                     # NOT bumped
    assert out.mpos_last_result == "idle"


def test_apply_error_keeps_values_updates_result_only():
    s = MowerState(mpos_x=95, mpos_updated_unix=1780000000, mpos_last_result="ok")
    out = apply_mpos_result(s, {"result": "error"}, now_unix=1781000000)
    assert out.mpos_x == 95
    assert out.mpos_updated_unix == 1780000000
    assert out.mpos_last_result == "error"
