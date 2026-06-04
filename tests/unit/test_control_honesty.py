"""Unit tests for control_honesty resolver + modes."""
from custom_components.dreame_a2_mower.control_honesty import (
    ControlMode, READ_ONLY_MODES, CONTROL_MODES, resolve_control_mode,
)


def test_read_only_modes_membership():
    assert ControlMode.READ_ONLY_CONFIRMED in READ_ONLY_MODES
    assert ControlMode.DEVICE_WRITABLE not in READ_ONLY_MODES
    assert ControlMode.INTEGRATION_LOCAL not in READ_ONLY_MODES


def test_resolve_direct_scalar_id():
    assert resolve_control_mode(
        platform="number", key="map_N_settings_mowing_height"
    ) is ControlMode.READ_ONLY_CONFIRMED


def test_resolve_generic_switch_by_leaf():
    assert resolve_control_mode(platform="switch", key="child_lock") is ControlMode.DEVICE_WRITABLE
    assert resolve_control_mode(platform="switch", key="dnd") is ControlMode.READ_ONLY_CONFIRMED
    assert resolve_control_mode(platform="switch", key="led_period") is ControlMode.READ_ONLY_NOOP


def test_resolve_setting_select_is_direct_scalar():
    assert resolve_control_mode(platform="select", key="navigation_path") is ControlMode.DEVICE_WRITABLE
    assert resolve_control_mode(platform="select", key="lcd_language") is ControlMode.READ_ONLY_PENDING


def test_resolve_unknown_raises():
    import pytest
    with pytest.raises(KeyError):
        resolve_control_mode(platform="number", key="does_not_exist")
