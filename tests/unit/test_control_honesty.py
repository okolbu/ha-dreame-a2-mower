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


from custom_components.dreame_a2_mower.control_honesty import _ControlHonestyMixin, ControlMode


class _FakeEntity(_ControlHonestyMixin):
    """Minimal stand-in: no HA base, just the mixin + the hooks it reads."""
    def __init__(self, mode):
        self._control_mode = mode
        self.wrote = False
        self.published = 0
        self._attr_icon = "mdi:knob"
    def async_write_ha_state(self):
        self.published += 1


def test_read_only_property():
    assert _FakeEntity(ControlMode.READ_ONLY_CONFIRMED).read_only is True
    assert _FakeEntity(ControlMode.DEVICE_WRITABLE).read_only is False


def test_padlock_icon_only_when_read_only():
    assert _FakeEntity(ControlMode.READ_ONLY_PENDING).icon == "mdi:lock-outline"
    assert _FakeEntity(ControlMode.DEVICE_WRITABLE).icon == "mdi:knob"


def test_extra_state_attributes_marks_read_only():
    a = _FakeEntity(ControlMode.READ_ONLY_NOOP).extra_state_attributes
    assert a == {"control_mode": "read_only_noop", "read_only": True}
    assert _FakeEntity(ControlMode.INTEGRATION_LOCAL).extra_state_attributes == {
        "control_mode": "integration_local", "read_only": False,
    }


async def test_reject_readonly_write_republishes_and_does_not_write():
    e = _FakeEntity(ControlMode.READ_ONLY_CONFIRMED)
    await e._reject_readonly_write()
    assert e.published == 1 and e.wrote is False


def test_resolve_generic_scalar_time():
    assert resolve_control_mode(platform="time", key="anything") is ControlMode.READ_ONLY_NOOP
