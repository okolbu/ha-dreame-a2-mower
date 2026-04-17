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
