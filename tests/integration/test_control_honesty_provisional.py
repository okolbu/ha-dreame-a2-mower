"""Provisional marking for device_write_unproven controls.

These are real device RPCs not yet live-proven on g2408 (stop/pause/dock,
lock_bot, generate_3dmap). They stay operable (no padlock, no snap-back) but
carry a `provisional` extra-state-attribute so the UI / automations can tell
them apart from a confirmed control.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.button import (
    DreameA2FindBotButton,
    DreameA2Generate3DMapButton,
    DreameA2LockBotButton,
    DreameA2PauseMowingButton,
    DreameA2RechargeButton,
    DreameA2StartMowingButton,
    DreameA2StopMowingButton,
)

_UNPROVEN = (
    DreameA2PauseMowingButton,
    DreameA2StopMowingButton,
    DreameA2RechargeButton,
    DreameA2LockBotButton,
    DreameA2Generate3DMapButton,
)
_CONFIRMED = (DreameA2StartMowingButton, DreameA2FindBotButton)


def test_unproven_buttons_are_provisional_not_readonly():
    for cls in _UNPROVEN:
        btn = cls(MagicMock())
        assert btn.provisional is True, cls.__name__
        assert btn.read_only is False, cls.__name__
        attrs = btn.extra_state_attributes
        assert attrs["control_mode"] == "device_write_unproven", cls.__name__
        assert attrs["provisional"] is True, cls.__name__
        # operable: no padlock — keeps its own action icon
        assert btn.icon != "mdi:lock-outline", cls.__name__


def test_confirmed_buttons_are_not_provisional():
    for cls in _CONFIRMED:
        btn = cls(MagicMock())
        assert btn.provisional is False, cls.__name__
        assert btn.read_only is False, cls.__name__
        assert btn.extra_state_attributes["control_mode"] == "device_writable", cls.__name__
