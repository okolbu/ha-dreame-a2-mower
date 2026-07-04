"""Tests for entity-layer wire-payload builders.

These pure functions are critical because they construct the exact bytes /
values that get sent to the mower firmware.  A bug here would send a
malformed array without any other test catching it.

All builder functions live in:
  - custom_components.dreame_a2_mower.number   (_build_vol)
  - custom_components.dreame_a2_mower.switch   (_build_cls, _build_ata_*, ...)
  - custom_components.dreame_a2_mower.select   (_build_pre_efficiency,
                                                _build_wrp_resume_hours)

Tests cover:
  1. Smoke test — correct output shape and slot assignment with known state.
  2. Defaults test — sensible values when MowerState fields are None.
"""
from __future__ import annotations

import pytest

from custom_components.dreame_a2_mower.state import MowerState
from custom_components.dreame_a2_mower.number import (
    _build_vol,
)
from custom_components.dreame_a2_mower.select import (
    _PRE_PAD_DEFAULTS,
    _build_pre_efficiency,
    _build_wrp_resume_hours,
)
from custom_components.dreame_a2_mower.switch import (
    _build_ata_lift,
    _build_ata_offmap,
    _build_ata_realtime,
    _build_cls,
    _build_int_toggle,
    _build_msg_alert_anomaly,
    _build_msg_alert_consumables,
    _build_msg_alert_error,
    _build_msg_alert_task,
    _build_voice_error,
    _build_voice_regular,
    _build_voice_special,
    _build_voice_work,
)


# ---------------------------------------------------------------------------
# number.py builders
# ---------------------------------------------------------------------------

class TestBuildVol:
    def test_returns_int(self) -> None:
        state = MowerState(volume_pct=50)
        assert _build_vol(state, 75) == 75

    def test_truncates_float(self) -> None:
        state = MowerState()
        assert _build_vol(state, 33.9) == 33

    def test_zero(self) -> None:
        assert _build_vol(MowerState(), 0) == 0

    def test_100(self) -> None:
        assert _build_vol(MowerState(), 100) == 100


# ---------------------------------------------------------------------------
# switch.py builders
# ---------------------------------------------------------------------------

class TestBuildCls:
    def test_true_gives_1(self) -> None:
        assert _build_cls(MowerState(), True) == 1

    def test_false_gives_0(self) -> None:
        assert _build_cls(MowerState(), False) == 0


class TestBuildAtaLift:
    def test_shape(self) -> None:
        result = _build_ata_lift(MowerState(), True)
        assert len(result) == 3

    def test_slot_0_is_new_value(self) -> None:
        assert _build_ata_lift(MowerState(), True)[0] == 1
        assert _build_ata_lift(MowerState(), False)[0] == 0

    def test_slot_1_is_offmap(self) -> None:
        state = MowerState(anti_theft_offmap_alarm=True)
        assert _build_ata_lift(state, False)[1] == 1

    def test_slot_2_is_realtime(self) -> None:
        state = MowerState(anti_theft_realtime_location=True)
        assert _build_ata_lift(state, False)[2] == 1

    def test_none_defaults_other_flags_false(self) -> None:
        result = _build_ata_lift(MowerState(), True)
        assert result[1] == 0
        assert result[2] == 0


class TestBuildAtaOffmap:
    def test_shape(self) -> None:
        result = _build_ata_offmap(MowerState(), True)
        assert len(result) == 3

    def test_slot_1_is_new_value(self) -> None:
        assert _build_ata_offmap(MowerState(), True)[1] == 1
        assert _build_ata_offmap(MowerState(), False)[1] == 0

    def test_slot_0_is_lift(self) -> None:
        state = MowerState(anti_theft_lift_alarm=True)
        assert _build_ata_offmap(state, False)[0] == 1

    def test_slot_2_is_realtime(self) -> None:
        state = MowerState(anti_theft_realtime_location=True)
        assert _build_ata_offmap(state, False)[2] == 1

    def test_none_defaults_other_flags_false(self) -> None:
        result = _build_ata_offmap(MowerState(), True)
        assert result[0] == 0
        assert result[2] == 0


class TestBuildAtaRealtime:
    def test_shape(self) -> None:
        result = _build_ata_realtime(MowerState(), True)
        assert len(result) == 3

    def test_slot_2_is_new_value(self) -> None:
        assert _build_ata_realtime(MowerState(), True)[2] == 1
        assert _build_ata_realtime(MowerState(), False)[2] == 0

    def test_slot_0_is_lift(self) -> None:
        state = MowerState(anti_theft_lift_alarm=True)
        assert _build_ata_realtime(state, False)[0] == 1

    def test_slot_1_is_offmap(self) -> None:
        state = MowerState(anti_theft_offmap_alarm=True)
        assert _build_ata_realtime(state, False)[1] == 1

    def test_none_defaults_other_flags_false(self) -> None:
        result = _build_ata_realtime(MowerState(), True)
        assert result[0] == 0
        assert result[1] == 0


# ---------------------------------------------------------------------------
# select.py builders
# ---------------------------------------------------------------------------

class TestBuildPreEfficiency:
    def test_shape(self) -> None:
        """Builder must return exactly 10 elements."""
        result = _build_pre_efficiency(MowerState(), "Standard")
        assert len(result) == 10

    def test_standard_sets_slot_1_to_0(self) -> None:
        result = _build_pre_efficiency(MowerState(), "Standard")
        assert result[1] == 0

    def test_efficient_sets_slot_1_to_1(self) -> None:
        result = _build_pre_efficiency(MowerState(), "Efficient")
        assert result[1] == 1

    def test_slot_0_is_zone_id(self) -> None:
        state = MowerState(pre_zone_id=3)
        result = _build_pre_efficiency(state, "Standard")
        assert result[0] == 3

    def test_slot_2_is_height_mm(self) -> None:
        state = MowerState(pre_mowing_height_mm=55)
        result = _build_pre_efficiency(state, "Standard")
        assert result[2] == 55

    def test_slot_2_defaults_to_pre_pad_defaults_0(self) -> None:
        """height_mm None → uses _PRE_PAD_DEFAULTS[0] (60mm)."""
        result = _build_pre_efficiency(MowerState(), "Standard")
        assert result[2] == _PRE_PAD_DEFAULTS[0]

    def test_trailing_slots_from_pre_pad_defaults(self) -> None:
        """Slots 3..9 must come from _PRE_PAD_DEFAULTS[1:]."""
        result = _build_pre_efficiency(MowerState(), "Standard")
        for i, expected in enumerate(_PRE_PAD_DEFAULTS[1:], start=3):
            assert result[i] == expected, f"slot {i} mismatch"

    def test_none_zone_id_defaults_to_0(self) -> None:
        result = _build_pre_efficiency(MowerState(), "Standard")
        assert result[0] == 0

    def test_pre_pad_defaults_length(self) -> None:
        """_PRE_PAD_DEFAULTS must supply indices 2..9 (8 elements)."""
        assert len(_PRE_PAD_DEFAULTS) == 8


class TestBuildWrpResumeHours:
    """WRP resume-hours select: same {value, time} dict shape as the WRP
    switch builder, with the ``time`` slot driven by the picked option."""

    def test_shape(self) -> None:
        result = _build_wrp_resume_hours(MowerState(), "4 hours")
        assert isinstance(result, dict)
        assert set(result.keys()) == {"value", "time"}

    def test_value_is_enabled(self) -> None:
        state_on = MowerState(rain_protection_enabled=True)
        state_off = MowerState(rain_protection_enabled=False)
        assert _build_wrp_resume_hours(state_on, "4 hours")["value"] == 1
        assert _build_wrp_resume_hours(state_off, "4 hours")["value"] == 0

    def test_time_is_parsed_hours(self) -> None:
        result = _build_wrp_resume_hours(MowerState(), "6 hours")
        assert result["time"] == 6

    def test_zero_hours(self) -> None:
        result = _build_wrp_resume_hours(MowerState(), "0 hours")
        assert result["time"] == 0

    def test_single_hour_label(self) -> None:
        """'1 hour' (singular) must still parse correctly."""
        result = _build_wrp_resume_hours(MowerState(), "1 hour")
        assert result["time"] == 1

    def test_none_enabled_defaults_false(self) -> None:
        """rain_protection_enabled None → treated as False (enabled=0)."""
        result = _build_wrp_resume_hours(MowerState(), "2 hours")
        assert result["value"] == 0


# ---------------------------------------------------------------------------
# AMBIGUOUS_TOGGLE single-int CFG keys (a62)
# ---------------------------------------------------------------------------

class TestBuildIntToggle:
    """FDP / STUN / AOP / PROT all use the trivial 0/1 builder."""

    def test_true_returns_1(self) -> None:
        assert _build_int_toggle(MowerState(), True) == 1

    def test_false_returns_0(self) -> None:
        assert _build_int_toggle(MowerState(), False) == 0

    def test_ignores_state(self) -> None:
        # No fields read from state — purely a 0/1 echo.
        state = MowerState(frost_protection_enabled=True)
        assert _build_int_toggle(state, False) == 0


# ---------------------------------------------------------------------------
# MSG_ALERT — Notification Preferences (4-bool list, a62)
# ---------------------------------------------------------------------------

class TestBuildMsgAlert:
    """Each MSG_ALERT slot builder flips its own index, preserves the others."""

    def test_anomaly_overrides_only_index_0(self) -> None:
        state = MowerState(
            msg_alert_anomaly=True,
            msg_alert_error=True,
            msg_alert_task=False,
            msg_alert_consumables=True,
        )
        result = _build_msg_alert_anomaly(state, False)
        assert result == [0, 1, 0, 1]

    def test_error_overrides_only_index_1(self) -> None:
        state = MowerState(
            msg_alert_anomaly=True,
            msg_alert_error=False,
            msg_alert_task=True,
            msg_alert_consumables=True,
        )
        result = _build_msg_alert_error(state, True)
        assert result == [1, 1, 1, 1]

    def test_task_overrides_only_index_2(self) -> None:
        state = MowerState(
            msg_alert_anomaly=False,
            msg_alert_error=False,
            msg_alert_task=True,
            msg_alert_consumables=False,
        )
        result = _build_msg_alert_task(state, False)
        assert result == [0, 0, 0, 0]

    def test_consumables_overrides_only_index_3(self) -> None:
        state = MowerState(
            msg_alert_anomaly=True,
            msg_alert_error=True,
            msg_alert_task=True,
            msg_alert_consumables=False,
        )
        result = _build_msg_alert_consumables(state, True)
        assert result == [1, 1, 1, 1]

    def test_none_fields_default_false(self) -> None:
        """Unset (None) MowerState fields should serialise as 0."""
        result = _build_msg_alert_anomaly(MowerState(), True)
        assert result == [1, 0, 0, 0]


# ---------------------------------------------------------------------------
# VOICE — Voice Prompt Modes (4-bool list, a62)
# ---------------------------------------------------------------------------

class TestBuildVoice:
    """Each VOICE slot builder flips its own index, preserves the others."""

    def test_regular_overrides_only_index_0(self) -> None:
        state = MowerState(
            voice_regular_notification=False,
            voice_work_status=True,
            voice_special_status=True,
            voice_error_status=True,
        )
        result = _build_voice_regular(state, True)
        assert result == [1, 1, 1, 1]

    def test_work_overrides_only_index_1(self) -> None:
        state = MowerState(
            voice_regular_notification=True,
            voice_work_status=False,
            voice_special_status=True,
            voice_error_status=False,
        )
        result = _build_voice_work(state, True)
        assert result == [1, 1, 1, 0]

    def test_special_overrides_only_index_2(self) -> None:
        state = MowerState(
            voice_regular_notification=True,
            voice_work_status=True,
            voice_special_status=True,
            voice_error_status=True,
        )
        result = _build_voice_special(state, False)
        assert result == [1, 1, 0, 1]

    def test_error_overrides_only_index_3(self) -> None:
        state = MowerState(
            voice_regular_notification=False,
            voice_work_status=False,
            voice_special_status=False,
            voice_error_status=True,
        )
        result = _build_voice_error(state, False)
        assert result == [0, 0, 0, 0]

    def test_none_fields_default_false(self) -> None:
        result = _build_voice_error(MowerState(), True)
        assert result == [0, 0, 0, 1]
