"""Tests for custom_components.dreame_a2_mower.protocol.heartbeat."""

from __future__ import annotations

import pytest

from protocol.heartbeat import (
    Heartbeat,
    decode_s1p1,
    InvalidS1P1Frame,
)


# From probe_log_20260417_095500.jsonl at 2026-04-17 09:55:56.
HEARTBEAT_FRAME_A = bytes([
    0xCE, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x80, 0xDA, 0x85, 0x24, 0x00, 0x01, 0x80, 0xC1, 0xBA, 0xCE,
])

# From same session, ~68s later — counter advanced at bytes [11,12].
HEARTBEAT_FRAME_B = bytes([
    0xCE, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x80, 0xDB, 0xB5, 0x24, 0x00, 0x01, 0x80, 0xC1, 0xBA, 0xCE,
])


def test_decode_s1p1_returns_heartbeat_dataclass():
    assert isinstance(decode_s1p1(HEARTBEAT_FRAME_A), Heartbeat)


def test_decode_s1p1_rejects_wrong_length():
    with pytest.raises(InvalidS1P1Frame, match="length"):
        decode_s1p1(b"\xce\x00\xce")


def test_decode_s1p1_rejects_wrong_delimiters():
    bad = bytes([0x00]) + HEARTBEAT_FRAME_A[1:]
    with pytest.raises(InvalidS1P1Frame, match="delimiter"):
        decode_s1p1(bad)


def test_decode_s1p1_exposes_counter_bytes_11_12():
    hb = decode_s1p1(HEARTBEAT_FRAME_A)
    assert hb.counter == (0xDA | (0x85 << 8))  # little-endian u16 at [11,12]


def test_decode_s1p1_counter_advances_between_frames():
    a = decode_s1p1(HEARTBEAT_FRAME_A)
    b = decode_s1p1(HEARTBEAT_FRAME_B)
    assert b.counter > a.counter


def test_decode_s1p1_exposes_state_byte_7():
    hb = decode_s1p1(HEARTBEAT_FRAME_A)
    assert hb.state_raw == 0


def test_decode_s1p1_exposes_raw_bytes():
    hb = decode_s1p1(HEARTBEAT_FRAME_A)
    assert hb.raw == HEARTBEAT_FRAME_A
