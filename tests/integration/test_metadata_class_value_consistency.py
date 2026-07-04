"""P4.3 (R-50 / track-5 T5-5): device_class ↔ emitted-value consistency.

HA rejects a sensor at RUNTIME (state goes unavailable / logs an error) when
its ``device_class`` is incompatible with the state it emits:

  * TIMESTAMP  → the state must be a tz-aware ``datetime``.
  * DATE       → the state must be a ``date`` OBJECT (HA calls ``.isoformat()``
                 on native_value; an ISO string raises ValueError at add-time).
  * DURATION   → the state must be a number AND the unit a time unit.
  * AREA       → the state must be a number AND the unit an area unit.
  * DISTANCE   → the state must be a number AND the unit a length unit.

Unit tests otherwise pass even when this pairing is wrong (the descriptor is
just data), so these assertions are the guard that would catch a class that was
added without converting the value_fn (the epoch→datetime trap for
``last_settings_change_unix`` in particular).
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from custom_components.dreame_a2_mower.entities.sensor import device as sensor_device
from custom_components.dreame_a2_mower.entities.sensor.device import (
    SensorDeviceClass,
)
from custom_components.dreame_a2_mower.state import MowerState

SENSORS = sensor_device.SENSORS

# Valid HA unit vocab per device_class (the subset used by this integration).
_TIME_UNITS = {"s", "min", "h", "d", "ms", "µs"}
_AREA_UNITS = {"m²", "cm²", "km²", "ha"}
_LENGTH_UNITS = {"m", "km", "cm", "mm"}


def _desc(key):
    return next(d for d in SENSORS if d.key == key)


# ---------------------------------------------------------------------------
# TIMESTAMP: value_fn must emit a tz-aware datetime (or None), never a raw int.
# ---------------------------------------------------------------------------

def test_last_settings_change_is_timestamp_datetime():
    d = _desc("last_settings_change_unix")
    assert d.device_class == SensorDeviceClass.TIMESTAMP
    # Real epoch → tz-aware datetime (NOT the raw int that would runtime-reject).
    dt = d.value_fn(MowerState(last_settings_change_unix=1782665658))
    assert isinstance(dt, datetime)
    assert dt.tzinfo is not None
    # None → None (no crash, entity just unknown).
    assert d.value_fn(MowerState()) is None


def test_latest_session_time_is_timestamp_datetime():
    d = _desc("latest_session_unix_ts")
    assert d.device_class == SensorDeviceClass.TIMESTAMP
    dt = d.value_fn(MowerState(latest_session_unix_ts=1782665658))
    assert isinstance(dt, datetime)
    assert dt.tzinfo is not None
    assert d.value_fn(MowerState()) is None


# ---------------------------------------------------------------------------
# DATE: value_fn must emit a date or ISO YYYY-MM-DD string (or None).
# ---------------------------------------------------------------------------

def test_first_mowing_date_is_date_object():
    d = _desc("first_mowing_date")
    assert d.device_class == SensorDeviceClass.DATE
    val = d.value_fn(MowerState(first_mowing_date="2026-06-21"))
    # HA's DATE class calls ``.isoformat()`` on native_value → it MUST be a
    # ``date`` object, NOT an ISO string (a string raises ValueError at
    # add-time; live-caught in P4.7). None-when-unset is allowed.
    assert val is None or isinstance(val, date)
    assert val == date(2026, 6, 21)
    # empty/None state → None, not a crash
    assert d.value_fn(MowerState(first_mowing_date=None)) is None
    if isinstance(val, str):
        # Must be parseable as an ISO date, else HA rejects it at runtime.
        assert date.fromisoformat(val) == date(2026, 6, 21)
    else:
        assert isinstance(val, date)
    assert d.value_fn(MowerState()) is None


# ---------------------------------------------------------------------------
# DURATION / AREA / DISTANCE: numeric value + a unit valid for the class.
# ---------------------------------------------------------------------------

_DURATION_KEYS = {
    "total_mowing_time_min": ("total_mowing_time_min", 120),
    "latest_session_duration_min": ("latest_session_duration_min", 46),
    "sim_left_days": ("sim_left_days", 895),
    "human_presence_push_interval_min": ("human_presence_alert_push_interval_min", 10),
}


@pytest.mark.parametrize("key", sorted(_DURATION_KEYS))
def test_duration_sensors_numeric_and_time_unit(key):
    d = _desc(key)
    assert d.device_class == SensorDeviceClass.DURATION
    assert d.native_unit_of_measurement in _TIME_UNITS
    field, sample = _DURATION_KEYS[key]
    val = d.value_fn(MowerState(**{field: sample}))
    assert isinstance(val, (int, float))


_AREA_KEYS = {
    "area_mowed_m2": ("area_mowed_m2", 77.5),
    "total_lawn_area_m2": ("total_lawn_area_m2", 500.0),
    "total_mowed_area_m2": ("total_mowed_area_m2", 1234.0),
    "latest_session_area_m2": ("latest_session_area_m2", 77.5),
}


@pytest.mark.parametrize("key", sorted(_AREA_KEYS))
def test_area_sensors_numeric_and_area_unit(key):
    d = _desc(key)
    assert d.device_class == SensorDeviceClass.AREA
    assert d.native_unit_of_measurement in _AREA_UNITS
    field, sample = _AREA_KEYS[key]
    val = d.value_fn(MowerState(**{field: sample}))
    assert isinstance(val, (int, float))


def test_session_distance_is_distance_and_length_unit():
    d = _desc("session_distance_m")
    assert d.device_class == SensorDeviceClass.DISTANCE
    assert d.native_unit_of_measurement in _LENGTH_UNITS
    val = d.value_fn(MowerState(session_distance_m=12.3))
    assert isinstance(val, (int, float))


# ---------------------------------------------------------------------------
# P4.6-INPUT (deferred from P4.3): latest_video_duration lives in
# DIAGNOSTIC_SENSORS (coord-aware value_fn), not SENSORS/MowerState — verified
# correct manually in P4.3 but never parametrized into this guard.
# ---------------------------------------------------------------------------

def test_latest_video_duration_is_numeric_and_time_unit():
    from types import SimpleNamespace

    d = _diag("latest_video")
    assert d.device_class == SensorDeviceClass.DURATION
    assert d.native_unit_of_measurement in _TIME_UNITS
    coord = SimpleNamespace(
        _video_archive=SimpleNamespace(latest=lambda: SimpleNamespace(duration=42))
    )
    val = d.value_fn(coord)
    assert isinstance(val, (int, float))
    # Empty archive -> None (no crash, entity just unknown).
    coord_empty = SimpleNamespace(_video_archive=SimpleNamespace(latest=lambda: None))
    assert d.value_fn(coord_empty) is None


# ---------------------------------------------------------------------------
# P4.6-INPUT (deferred from P4.3): per-map AREA/DURATION class-level
# descriptors (entities/sensor/map.py, session.py) — verified correct
# manually, never parametrized into this guard.
# ---------------------------------------------------------------------------

def _map_coord(*, sessions=()):
    from unittest.mock import MagicMock

    coord = MagicMock()
    coord.entry.entry_id = "e"
    map_obj = MagicMock()
    map_obj.total_area_m2 = 500.0
    coord.cloud_state.maps_by_id = {0: map_obj}
    coord.session_archive._index = list(sessions)
    return coord


def test_map_area_sensor_is_area_and_area_unit():
    from custom_components.dreame_a2_mower.entities.sensor.map import (
        DreameA2MapAreaSensor,
    )

    s = DreameA2MapAreaSensor(_map_coord(), map_id=0)
    assert s._attr_device_class == SensorDeviceClass.AREA
    assert s._attr_native_unit_of_measurement in _AREA_UNITS
    assert isinstance(s.native_value, (int, float))


def test_map_session_area_total_is_area_and_area_unit():
    from types import SimpleNamespace

    from custom_components.dreame_a2_mower.entities.sensor.session import (
        DreameA2MapSessionAreaTotalSensor,
    )

    sessions = (
        SimpleNamespace(map_id=0, area_mowed_m2=50.0, session_type="mow"),
    )
    s = DreameA2MapSessionAreaTotalSensor(_map_coord(sessions=sessions), map_id=0)
    assert s._attr_device_class == SensorDeviceClass.AREA
    assert s._attr_native_unit_of_measurement in _AREA_UNITS
    assert isinstance(s.native_value, (int, float))


def test_map_session_time_total_is_duration_and_time_unit():
    from types import SimpleNamespace

    from custom_components.dreame_a2_mower.entities.sensor.session import (
        DreameA2MapSessionTimeTotalSensor,
    )

    sessions = (
        SimpleNamespace(map_id=0, duration_min=30, session_type="mow"),
    )
    s = DreameA2MapSessionTimeTotalSensor(_map_coord(sessions=sessions), map_id=0)
    assert s._attr_device_class == SensorDeviceClass.DURATION
    assert s._attr_native_unit_of_measurement in _TIME_UNITS
    assert isinstance(s.native_value, (int, float))


# ---------------------------------------------------------------------------
# mowing_count: the invalid "x" unit is gone (unitless counter).
# ---------------------------------------------------------------------------

def test_mowing_count_has_no_invalid_unit():
    d = _desc("mowing_count")
    assert d.native_unit_of_measurement is None
    assert d.value_fn(MowerState(mowing_count=116)) == 116


# ---------------------------------------------------------------------------
# T5-17: raw-code shadow sensors disabled by default for the public release.
# ---------------------------------------------------------------------------

def _diag(key):
    return next(d for d in sensor_device.DIAGNOSTIC_SENSORS if d.key == key)


def test_raw_shadow_sensors_disabled_by_default():
    # SENSORS-table one.
    assert _desc("charging_status_code_raw").entity_registry_enabled_default is False
    # DIAGNOSTIC_SENSORS ones.
    for key in ("mowing_phase", "task_state_code", "slam_task_label"):
        assert _diag(key).entity_registry_enabled_default is False
    # Raw slot probes were already disabled — keep them so.
    for key in ("s5p104_raw", "s5p105_raw", "s5p106_raw", "s5p107_raw", "s6p1_raw"):
        assert _desc(key).entity_registry_enabled_default is False


# ---------------------------------------------------------------------------
# T5-15 / T5-17: position sensors + mowing_phase carry NO state_class.
# ---------------------------------------------------------------------------

def test_position_and_phase_sensors_have_no_state_class():
    for key in ("position_x_m", "position_y_m", "position_north_m", "position_east_m"):
        assert _diag(key).state_class is None
    assert _diag("mowing_phase").state_class is None


# ---------------------------------------------------------------------------
# T5-4 / R-50: settings controls carry CONFIG (not None, not DIAGNOSTIC).
# ---------------------------------------------------------------------------

def test_settings_controls_are_config_category():
    from homeassistant.helpers.entity import EntityCategory

    from custom_components.dreame_a2_mower.entities.switch.base import DreameA2Switch
    from custom_components.dreame_a2_mower.entities.select.global_ import (
        DreameA2SettingSelect,
    )
    from custom_components.dreame_a2_mower.number import DreameA2Number

    for cls in (DreameA2Switch, DreameA2SettingSelect, DreameA2Number):
        assert cls._attr_entity_category == EntityCategory.CONFIG


# ---------------------------------------------------------------------------
# R-51 / T5-7: mqtt_connectivity absorbs the numeric age_s attribute.
# ---------------------------------------------------------------------------

def test_mqtt_connectivity_exposes_age_s():
    import time
    import types

    from custom_components.dreame_a2_mower.entities.sensor.device import (
        DreameA2MqttConnectivitySensor,
    )

    s = DreameA2MqttConnectivitySensor.__new__(DreameA2MqttConnectivitySensor)
    # last heartbeat 30s ago → age_s ~= 30.
    snap = types.SimpleNamespace(last_heartbeat_unix=int(time.time()) - 30)
    sm = types.SimpleNamespace(snapshot=lambda: snap)
    s.coordinator = types.SimpleNamespace(state_machine=sm)
    attrs = s.extra_state_attributes
    assert 29 <= attrs["age_s"] <= 32
    # No heartbeat yet → None (no crash).
    snap.last_heartbeat_unix = None
    assert s.extra_state_attributes["age_s"] is None
