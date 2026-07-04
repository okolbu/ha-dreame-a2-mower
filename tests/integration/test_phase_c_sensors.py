"""Tests for Phase C SIM / messaging diagnostic sensors (Task 3)."""
import types
from datetime import UTC, datetime

from custom_components.dreame_a2_mower import binary_sensor as bs
from custom_components.dreame_a2_mower.entities.sensor import device as sensor_device
from custom_components.dreame_a2_mower.entities.sensor.device import SensorDeviceClass
from custom_components.dreame_a2_mower.state import MowerState

_LIST = sensor_device.SENSORS


def _desc(key):
    return next(d for d in _LIST if d.key == key)


def test_sim_sensors_read_state():
    s = MowerState(sim_left_days=895, sim_card_id="FAKE", sim_active_time="a")
    assert _desc("sim_left_days").value_fn(s) == 895
    assert _desc("sim_card_id").value_fn(s) == "FAKE"
    assert _desc("sim_active_time").value_fn(s) == "a"


def test_sim_expires_is_timestamp():
    d = _desc("sim_expired_time")
    assert d.device_class == SensorDeviceClass.TIMESTAMP
    # biz_4g_remain delivers ISO-8601 UTC → a tz-aware datetime
    dt = d.value_fn(MowerState(sim_expired_time="2028-11-19T16:00:00Z"))
    assert dt == datetime(2028, 11, 19, 16, 0, tzinfo=UTC)
    # naive / garbage / None → None (timestamp device_class requires tz-aware)
    assert d.value_fn(MowerState(sim_expired_time="2028-11-20 15:45:29")) is None
    assert d.value_fn(MowerState(sim_expired_time="nonsense")) is None
    assert d.value_fn(MowerState()) is None


def test_sim_data_remaining_sensor_reads_state():
    d = _desc("sim_data_remaining_mb")
    assert d.value_fn(MowerState(sim_data_remaining_mb=1683.05)) == 1683.05
    assert d.value_fn(MowerState()) is None
    assert d.native_unit_of_measurement == "MB"


def test_sim_out_of_warranty_binary_sensor_reads_state():
    d = next(b for b in bs.BINARY_SENSORS if b.key == "sim_out_of_warranty")
    coord = types.SimpleNamespace(data=MowerState(sim_out_of_warranty=True))
    assert d.value_fn(coord) is True
    coord2 = types.SimpleNamespace(data=MowerState(sim_out_of_warranty=False))
    assert d.value_fn(coord2) is False


def test_unread_sensor_reads_state():
    assert _desc("service_messages_unread").value_fn(MowerState(service_messages_unread=2)) == 2


def test_unread_sensor_exposes_attributes():
    d = _desc("service_messages_unread")
    assert d.extra_attributes_fn is not None
    attrs = d.extra_attributes_fn(MowerState(system_messages_unread=1, latest_service_message="Sale"))
    assert attrs["system_messages_unread"] == 1
    assert attrs.get("latest_message") == "Sale"
