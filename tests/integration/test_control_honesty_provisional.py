"""Control-honesty marking for the mower's control buttons.

pause_mowing, stop_mowing, and recharge were promoted to device_writable
(Task 3 / phase-b-core-control-verdicts, 2026-06-10) after wiring via routed
op=4/3/6 was confirmed by app-mitm capture (2026-06-09). They share the
same DEVICE_WRITABLE bucket as start_mowing and find_bot.

(The two former READ_ONLY_NOOP buttons — lock_bot op=12 + generate_3dmap op=10,
accepted-but-no-effect on g2408 — were DELETED in refactor-v2 P4.2 (R-28,
track-5 T5-8); there are no noop control buttons left to assert.)
"""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.button import (
    DreameA2CancelDockReturnButton,
    DreameA2FindBotButton,
    DreameA2PauseMowingButton,
    DreameA2RechargeButton,
    DreameA2ResumeMowingButton,
    DreameA2StartMowingButton,
    DreameA2StopMowingButton,
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


def test_writable_buttons_are_not_provisional():
    for cls in _WRITABLE:
        btn = cls(MagicMock())
        assert btn.provisional is False, cls.__name__
        assert btn.read_only is False, cls.__name__
        attrs = btn.extra_state_attributes
        assert attrs["control_mode"] == "device_writable", cls.__name__
        assert attrs["provisional"] is False, cls.__name__
