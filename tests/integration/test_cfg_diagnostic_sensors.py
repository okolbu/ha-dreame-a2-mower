"""Tests for WRF/TIME/VER CFG-backed disabled-by-default diagnostic sensors.

Covers:
1. cfg_to_state_updates correctly ports WRF → weather_forecast_reference,
   TIME → timezone, VER → cfg_version.
2. Each sensor's native_value returns the expected HA-facing value.
3. Absent or malformed keys are omitted / skipped gracefully.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.dreame_a2_mower.coordinator._property_apply import (
    cfg_to_state_updates,
)


# ---------------------------------------------------------------------------
# cfg_to_state_updates — CFG port tests
# ---------------------------------------------------------------------------


def test_wrf_on_ported_as_1():
    out = cfg_to_state_updates({"WRF": 1})
    assert out["weather_forecast_reference"] == 1


def test_wrf_off_ported_as_0():
    out = cfg_to_state_updates({"WRF": 0})
    assert out["weather_forecast_reference"] == 0


def test_time_ported_as_string():
    out = cfg_to_state_updates({"TIME": "Europe/Oslo"})
    assert out["timezone"] == "Europe/Oslo"


def test_ver_ported_as_int():
    out = cfg_to_state_updates({"VER": 444})
    assert out["cfg_version"] == 444


def test_all_three_together():
    cfg = {"WRF": 1, "TIME": "Europe/Oslo", "VER": 444}
    out = cfg_to_state_updates(cfg)
    assert out["weather_forecast_reference"] == 1
    assert out["timezone"] == "Europe/Oslo"
    assert out["cfg_version"] == 444


def test_absent_wrf_not_in_output():
    out = cfg_to_state_updates({})
    assert "weather_forecast_reference" not in out


def test_absent_time_not_in_output():
    out = cfg_to_state_updates({})
    assert "timezone" not in out


def test_absent_ver_not_in_output():
    out = cfg_to_state_updates({})
    assert "cfg_version" not in out


def test_wrf_malformed_skipped():
    out = cfg_to_state_updates({"WRF": "not-an-int", "VER": 10})
    assert "weather_forecast_reference" not in out
    assert out["cfg_version"] == 10


def test_time_empty_string_skipped():
    """Empty string must be rejected — sensor should return None, not ''."""
    out = cfg_to_state_updates({"TIME": ""})
    assert "timezone" not in out


def test_ver_malformed_skipped():
    out = cfg_to_state_updates({"VER": "bad", "WRF": 0})
    assert "cfg_version" not in out
    assert out["weather_forecast_reference"] == 0


# ---------------------------------------------------------------------------
# Sensor native_value via DIAGNOSTIC_SENSORS descriptors
# ---------------------------------------------------------------------------


def _coord_with_state(**kwargs):
    """Build a mock coordinator whose .data is a MagicMock with attr overrides."""
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    data = MagicMock()
    for attr, val in kwargs.items():
        setattr(data, attr, val)
    coord.data = data
    return coord


def _descriptor(key: str):
    from custom_components.dreame_a2_mower.sensor import DIAGNOSTIC_SENSORS
    return next(d for d in DIAGNOSTIC_SENSORS if d.key == key)


def test_weather_forecast_reference_sensor_on():
    d = _descriptor("weather_forecast_reference")
    coord = _coord_with_state(weather_forecast_reference=1)
    assert d.value_fn(coord) == "on"


def test_weather_forecast_reference_sensor_off():
    d = _descriptor("weather_forecast_reference")
    coord = _coord_with_state(weather_forecast_reference=0)
    assert d.value_fn(coord) == "off"


def test_weather_forecast_reference_sensor_none():
    d = _descriptor("weather_forecast_reference")
    coord = _coord_with_state(weather_forecast_reference=None)
    assert d.value_fn(coord) is None


def test_timezone_sensor():
    d = _descriptor("timezone")
    coord = _coord_with_state(timezone="Europe/Oslo")
    assert d.value_fn(coord) == "Europe/Oslo"


def test_timezone_sensor_none():
    d = _descriptor("timezone")
    coord = _coord_with_state(timezone=None)
    assert d.value_fn(coord) is None


def test_cfg_version_sensor():
    d = _descriptor("cfg_version")
    coord = _coord_with_state(cfg_version=444)
    assert d.value_fn(coord) == 444


def test_cfg_version_sensor_none():
    d = _descriptor("cfg_version")
    coord = _coord_with_state(cfg_version=None)
    assert d.value_fn(coord) is None


def test_weather_forecast_reference_sensor_is_disabled_by_default():
    d = _descriptor("weather_forecast_reference")
    assert d.entity_registry_enabled_default is False


def test_timezone_sensor_is_disabled_by_default():
    d = _descriptor("timezone")
    assert d.entity_registry_enabled_default is False


def test_cfg_version_sensor_is_disabled_by_default():
    d = _descriptor("cfg_version")
    assert d.entity_registry_enabled_default is False


def test_all_three_have_diagnostic_entity_category():
    from homeassistant.helpers.entity import EntityCategory
    for key in ("weather_forecast_reference", "timezone", "cfg_version"):
        d = _descriptor(key)
        assert d.entity_category == EntityCategory.DIAGNOSTIC, (
            f"{key}: expected DIAGNOSTIC, got {d.entity_category}"
        )
