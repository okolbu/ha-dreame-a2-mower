"""Tests for Phase C SIM / messaging diagnostic sensors (Task 3)."""
from custom_components.dreame_a2_mower import sensor_device
from custom_components.dreame_a2_mower.mower.state import MowerState

_LIST = sensor_device.SENSORS


def _desc(key):
    return next(d for d in _LIST if d.key == key)


def test_sim_sensors_read_state():
    s = MowerState(sim_left_days=895, sim_card_id="FAKE", sim_active_time="a", sim_expired_time="e")
    assert _desc("sim_left_days").value_fn(s) == 895
    assert _desc("sim_card_id").value_fn(s) == "FAKE"
    assert _desc("sim_active_time").value_fn(s) == "a"
    assert _desc("sim_expired_time").value_fn(s) == "e"


def test_unread_sensor_reads_state():
    assert _desc("service_messages_unread").value_fn(MowerState(service_messages_unread=2)) == 2
