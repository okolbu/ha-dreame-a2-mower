"""Provisional marking for device_write_unproven controls.

lock_bot and generate_3dmap are real device RPCs not yet live-proven on g2408.
They stay operable (no padlock, no snap-back) but carry a `provisional`
extra-state-attribute so the UI / automations can tell them apart from a
confirmed control.

pause_mowing, stop_mowing, and recharge were promoted to device_writable
(Task 3 / phase-b-core-control-verdicts, 2026-06-10) after wiring via routed
op=4/3/6 was confirmed by app-mitm capture (2026-06-09). They now share the
same DEVICE_WRITABLE bucket as start_mowing and find_bot.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.button import (
    DreameA2CancelDockReturnButton,
    DreameA2FindBotButton,
    DreameA2Generate3DMapButton,
    DreameA2LockBotButton,
    DreameA2PauseMowingButton,
    DreameA2RechargeButton,
    DreameA2ResumeMowingButton,
    DreameA2StartMowingButton,
    DreameA2StopMowingButton,
)

# Still unproven on g2408 — accepted-but-no-effect observed for both.
_UNPROVEN = (
    DreameA2LockBotButton,
    DreameA2Generate3DMapButton,
)
# Confirmed writable: wired via routed opcodes, live-confirmed or app-mitm verified.
_WRITABLE = (
    DreameA2StartMowingButton,
    DreameA2FindBotButton,
    DreameA2PauseMowingButton,
    DreameA2StopMowingButton,
    DreameA2RechargeButton,
    DreameA2ResumeMowingButton,
    DreameA2CancelDockReturnButton,
)


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


def test_writable_buttons_are_not_provisional():
    for cls in _WRITABLE:
        btn = cls(MagicMock())
        assert btn.provisional is False, cls.__name__
        assert btn.read_only is False, cls.__name__
        attrs = btn.extra_state_attributes
        assert attrs["control_mode"] == "device_writable", cls.__name__
        assert attrs["provisional"] is False, cls.__name__
