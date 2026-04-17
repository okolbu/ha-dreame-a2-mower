"""Tests for s2p51 multiplexed config decoder."""

from __future__ import annotations

import pytest

from protocol.config_s2p51 import (
    Setting,
    S2P51Event,
    decode_s2p51,
    S2P51DecodeError,
)


def test_decode_timestamp_event_returns_timestamp_kind():
    payload = {"time": "1776415722", "tz": "UTC"}
    ev = decode_s2p51(payload)
    assert ev.setting is Setting.TIMESTAMP
    assert ev.values == {"time": 1776415722, "tz": "UTC"}


def test_decode_ambiguous_toggle_value_one():
    ev = decode_s2p51({"value": 1})
    assert ev.setting is Setting.AMBIGUOUS_TOGGLE
    assert ev.values == {"value": 1}


def test_decode_ambiguous_toggle_value_zero():
    ev = decode_s2p51({"value": 0})
    assert ev.setting is Setting.AMBIGUOUS_TOGGLE
    assert ev.values == {"value": 0}


def test_decode_rejects_malformed_payload():
    with pytest.raises(S2P51DecodeError, match="unknown"):
        decode_s2p51({"nonsense": True})


def test_decode_rejects_empty_payload():
    with pytest.raises(S2P51DecodeError, match="empty"):
        decode_s2p51({})


def test_decode_dnd_event_extracts_start_end_enabled():
    ev = decode_s2p51({"end": 420, "start": 1320, "value": 1})
    assert ev.setting is Setting.DND
    assert ev.values == {"start_min": 1320, "end_min": 420, "enabled": True}


def test_decode_dnd_event_disabled():
    ev = decode_s2p51({"end": 420, "start": 1320, "value": 0})
    assert ev.setting is Setting.DND
    assert ev.values["enabled"] is False


def test_decode_low_speed_nighttime_three_element_list():
    # [enabled, start_min, end_min] — times clearly larger than 1
    ev = decode_s2p51({"value": [1, 1260, 360]})
    assert ev.setting is Setting.LOW_SPEED_NIGHT
    assert ev.values == {"enabled": True, "start_min": 1260, "end_min": 360}


def test_decode_rain_protection_two_element_list():
    # [enabled, resume_hours]
    ev = decode_s2p51({"value": [1, 3]})
    assert ev.setting is Setting.RAIN_PROTECTION
    assert ev.values == {"enabled": True, "resume_hours": 3}
