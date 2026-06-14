"""Control-honesty marking for the mower's control buttons.

lock_bot (op=12) and generate_3dmap (op=10) are real device RPCs that the
g2408 firmware ACCEPTS (cloud r=0) but that have no observable effect —
accepted-but-no-effect. generate_3dmap was live-tested 2026-06-08; lock_bot
op=12 is the lock_robot-op12 incident. Both are therefore READ_ONLY_NOOP
(`_N`): honestly padlocked as no-ops.

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

# Confirmed accepted-but-no-effect on g2408 → READ_ONLY_NOOP.
_NOOP = (
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


def test_noop_buttons_are_readonly_noop():
    for cls in _NOOP:
        btn = cls(MagicMock())
        assert btn.read_only is True, cls.__name__
        assert btn.provisional is False, cls.__name__
        attrs = btn.extra_state_attributes
        assert attrs["control_mode"] == "read_only_noop", cls.__name__
        assert attrs["read_only"] is True, cls.__name__
        assert attrs["provisional"] is False, cls.__name__
        # honestly marked no-op → padlock icon
        assert btn.icon == "mdi:lock-outline", cls.__name__


def test_writable_buttons_are_not_provisional():
    for cls in _WRITABLE:
        btn = cls(MagicMock())
        assert btn.provisional is False, cls.__name__
        assert btn.read_only is False, cls.__name__
        attrs = btn.extra_state_attributes
        assert attrs["control_mode"] == "device_writable", cls.__name__
        assert attrs["provisional"] is False, cls.__name__
