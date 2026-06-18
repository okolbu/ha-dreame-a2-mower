"""Tests for the message-list sensors (T6).

Three read-only sensors on the PARENT device:
  - DreameA2DeviceMessagesSensor  — device_messages field
  - DreameA2ServiceMessagesSensor — service_messages field
  - DreameA2SharedMessagesSensor  — shared_messages field

DreameA2DeviceMessagesSensor state = TOTAL retained count (device-messages/v2
carries no read flag, so total is the useful signal).
DreameA2ServiceMessagesSensor / DreameA2SharedMessagesSensor state = unread count.
items attr = the full list; recorder-excluded.
"""
from custom_components.dreame_a2_mower.entities.sensor.device import (
    DreameA2DeviceMessagesSensor,
    DreameA2ServiceMessagesSensor,
    DreameA2SharedMessagesSensor,
)
from custom_components.dreame_a2_mower.mower.state import MowerState


class _Coord:
    def __init__(self, data):
        self.data = data
        self.last_update_success = True


def _sensor(cls, data):
    s = cls.__new__(cls)
    s.coordinator = _Coord(data)
    return s


def test_service_messages_sensor_state_is_unread_count():
    data = MowerState()
    data = data.__class__(**{**{f: getattr(data, f) for f in data.__dataclass_fields__}, "service_messages": [
        {"id": "1", "title": "a", "unread": True},
        {"id": "2", "title": "b", "unread": False},
    ]})
    s = _sensor(DreameA2ServiceMessagesSensor, data)
    assert s.native_value == 1
    assert s.extra_state_attributes["items"][0]["id"] == "1"


def test_message_sensors_exclude_recorder():
    assert DreameA2DeviceMessagesSensor._unrecorded_attributes == frozenset({"*"})
    assert DreameA2ServiceMessagesSensor._unrecorded_attributes == frozenset({"*"})
    assert DreameA2SharedMessagesSensor._unrecorded_attributes == frozenset({"*"})


def test_device_messages_sensor_state_and_items():
    """State is the TOTAL retained count, not the unread subset.

    device-messages/v2 carries no reliable read flag (all arrive as unread),
    so the sensor reports total count and accumulates indefinitely up to the cap.
    """
    data = MowerState()
    data = data.__class__(**{**{f: getattr(data, f) for f in data.__dataclass_fields__}, "device_messages": [
        {"id": "10", "title": "x", "unread": True},
        {"id": "11", "title": "y", "unread": True},
        {"id": "12", "title": "z", "unread": False},
    ]})
    s = _sensor(DreameA2DeviceMessagesSensor, data)
    # state = TOTAL count (3), not unread count (2)
    assert s.native_value == 3
    assert len(s.extra_state_attributes["items"]) == 3


def test_shared_messages_sensor_zero_when_none():
    data = MowerState()
    s = _sensor(DreameA2SharedMessagesSensor, data)
    assert s.native_value == 0
    assert s.extra_state_attributes["items"] == []
