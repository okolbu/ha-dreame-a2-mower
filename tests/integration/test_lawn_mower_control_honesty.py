"""DreameA2LawnMower carries the uniform control-honesty surface.

Phase 2.1(d): the primary lawn_mower entity gained _ControlHonestyMixin so it
exposes control_mode / read_only / provisional like every other control. It is
DEVICE_WRITABLE (`_W`) — operable, no padlock, no snap-back.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.control_honesty import (
    ControlMode,
    _ControlHonestyMixin,
)
from custom_components.dreame_a2_mower.lawn_mower import DreameA2LawnMower


def _coord():
    coord = MagicMock()
    coord.mqtt_is_fresh = True
    coord.cloud_is_fresh = True
    coord.entry.entry_id = "fake"
    return coord


def test_lawn_mower_inherits_control_honesty_mixin():
    assert issubclass(DreameA2LawnMower, _ControlHonestyMixin)


def test_lawn_mower_is_device_writable_not_readonly():
    ent = DreameA2LawnMower(_coord())
    assert ent.control_mode is ControlMode.DEVICE_WRITABLE
    assert ent.read_only is False
    assert ent.provisional is False


def test_lawn_mower_control_attrs_surfaced():
    ent = DreameA2LawnMower(_coord())
    attrs = ent.extra_state_attributes
    assert attrs["control_mode"] == "device_writable"
    assert attrs["read_only"] is False
    assert attrs["provisional"] is False
