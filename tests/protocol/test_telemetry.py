"""Tests for custom_components.dreame_a2_mower.protocol.telemetry."""

from __future__ import annotations

import pytest

from custom_components.dreame_a2_mower.protocol.telemetry import (
    MowingTelemetry,
    decode_s1p4,
    InvalidS1P4Frame,
)


# Verified frame: x=-1562mm, y=2847mm, phase=2, area_mowed=12.50m²,
# total_area=321.00m², distance=45.4m, seq=1094.
ACTIVE_MOW_FRAME = bytes([
    0xCE,                                     # [0] delimiter
    0xE6, 0xF9,                               # [1-2] x = -1562 (int16_le, 0xF9E6)
    0x1F, 0x0B,                               # [3-4] y = 2847 (int16_le, 0x0B1F)
    0x00,                                     # [5] static
    0x46, 0x04,                               # [6-7] seq = 1094
    0x02,                                     # [8] phase = mowing
    0x00,                                     # [9] static
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00,       # [10-15] motion (zeros)
    0x00, 0x00,                               # [16-17] motion
    0xFF, 0x7F, 0x00, 0x80,                   # [18-21] sentinel vectors
    0x01, 0x02,                               # [22-23] flags
    0xC6, 0x01,                               # [24-25] distance = 454 (÷10 = 45.4m)
    0x64, 0x7D,                               # [26-27] total area = 32100 (÷100 = 321.00m²)
    0x00,                                     # [28] static
    0xE2, 0x04,                               # [29-30] area mowed = 1250 (÷100 = 12.50m²)
    0x00,                                     # [31] static
    0xCE,                                     # [32] delimiter
])


def test_decode_s1p4_valid_frame_returns_telemetry_dataclass():
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    assert isinstance(t, MowingTelemetry)


def test_decode_s1p4_position_is_charger_relative_mm():
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    assert t.x_mm == -1562
    assert t.y_mm == 2847


def test_decode_s1p4_rejects_wrong_length():
    with pytest.raises(InvalidS1P4Frame, match="length"):
        decode_s1p4(b"\xce\x00\xce")


def test_decode_s1p4_rejects_missing_start_delimiter():
    bad = bytes([0x00]) + ACTIVE_MOW_FRAME[1:]
    with pytest.raises(InvalidS1P4Frame, match="delimiter"):
        decode_s1p4(bad)


def test_decode_s1p4_rejects_missing_end_delimiter():
    bad = ACTIVE_MOW_FRAME[:-1] + bytes([0x00])
    with pytest.raises(InvalidS1P4Frame, match="delimiter"):
        decode_s1p4(bad)
