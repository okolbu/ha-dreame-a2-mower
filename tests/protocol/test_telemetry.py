"""Tests for custom_components.dreame_a2_mower.protocol.telemetry."""

from __future__ import annotations

import pytest

from protocol.telemetry import (
    MowingTelemetry,
    decode_s1p4,
    InvalidS1P4Frame,
    Phase,
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


def test_decode_s1p4_exposes_sequence_counter():
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    assert t.sequence == 1094


def test_decode_s1p4_exposes_phase_enum_for_active_mow():
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    assert t.phase is Phase.MOWING


@pytest.mark.parametrize(
    ("phase_byte", "expected"),
    [
        (0, Phase.EDGE_OR_REPOSITION),
        (1, Phase.TRANSIT),
        (2, Phase.MOWING),
        (3, Phase.RETURNING),
    ],
)
def test_decode_s1p4_phase_byte_mapping(phase_byte, expected):
    frame = bytearray(ACTIVE_MOW_FRAME)
    frame[8] = phase_byte
    assert decode_s1p4(bytes(frame)).phase is expected


def test_decode_s1p4_unknown_phase_byte_is_preserved_raw():
    frame = bytearray(ACTIVE_MOW_FRAME)
    frame[8] = 9
    t = decode_s1p4(bytes(frame))
    assert t.phase is Phase.UNKNOWN
    assert t.phase_raw == 9


def test_decode_s1p4_distance_meters_from_deci_units():
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    # raw = 454 → 45.4m
    assert t.distance_m == pytest.approx(45.4)


def test_decode_s1p4_total_area_from_centiares():
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    # raw = 32100 → 321.00m²
    assert t.total_area_m2 == pytest.approx(321.00)


def test_decode_s1p4_mowed_area_from_centiares():
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    # raw = 1250 → 12.50m²
    assert t.area_mowed_m2 == pytest.approx(12.50)
