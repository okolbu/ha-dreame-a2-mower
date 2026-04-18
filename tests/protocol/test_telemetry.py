"""Tests for custom_components.dreame_a2_mower.protocol.telemetry."""

from __future__ import annotations

import pytest

from protocol.telemetry import (
    MowingTelemetry,
    PositionBeacon,
    decode_s1p4,
    decode_s1p4_position,
    InvalidS1P4Frame,
    Phase,
)


# Fixture frame: raw x=-1562 (cm → -15.62m), y=2847 (mm → 2.85m), phase=2,
# area_mowed=12.50m², total_area=321.00m², distance=45.4m, seq=1094.
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


def test_decode_s1p4_position_raw_scales_are_cm_for_x_and_mm_for_y():
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    assert t.x_cm == -1562
    assert t.y_mm == 2847


def test_decode_s1p4_position_exposed_in_metres_uses_per_axis_scale():
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    # X divides raw by 100 (cm → m); Y divides raw by 1000 (mm → m).
    assert t.x_m == pytest.approx(-15.62)
    assert t.y_m == pytest.approx(2.847)


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
    # ACTIVE_MOW_FRAME has phase byte = 2 (PHASE_2 per current labelling).
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    assert t.phase is Phase.PHASE_2


@pytest.mark.parametrize(
    ("phase_byte", "expected"),
    [
        (0, Phase.MOWING),
        (1, Phase.TRANSIT),
        (2, Phase.PHASE_2),
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


# --- 8-byte idle/beacon frame tests -----------------------------------

# Captured live: X=737cm, Y=-5040mm, docked mower emitting minimal beacon.
BEACON_DOCKED = bytes([0xCE, 0xE1, 0x02, 0x50, 0xEC, 0xFF, 0x06, 0xCE])

# Captured live during user remote-drive: X=1986cm, Y=2480mm.
BEACON_DRIVE = bytes([0xCE, 0xC2, 0x07, 0xB0, 0x09, 0x00, 0xE9, 0xCE])

# Captured live, near dock: X=25cm, Y=-112mm.
BEACON_NEAR_DOCK = bytes([0xCE, 0x19, 0x00, 0x90, 0xFF, 0xFF, 0xFD, 0xCE])


def test_decode_s1p4_position_from_beacon_returns_position():
    p = decode_s1p4_position(BEACON_DOCKED)
    assert isinstance(p, PositionBeacon)
    assert p.x_cm == 737
    assert p.y_mm == -5040


def test_decode_s1p4_position_handles_positive_y():
    p = decode_s1p4_position(BEACON_DRIVE)
    assert p.x_cm == 1986
    assert p.y_mm == 2480


def test_decode_s1p4_position_handles_small_negative_y():
    p = decode_s1p4_position(BEACON_NEAR_DOCK)
    assert p.x_cm == 25
    assert p.y_mm == -112


def test_decode_s1p4_position_accepts_full_frame_too():
    # The convenience decoder should work on 33-byte frames, returning
    # a PositionBeacon with just X/Y (callers who want full telemetry
    # should call decode_s1p4 directly).
    p = decode_s1p4_position(ACTIVE_MOW_FRAME)
    assert p.x_cm == -1562
    assert p.y_mm == 2847


def test_decode_s1p4_position_rejects_unexpected_length():
    with pytest.raises(InvalidS1P4Frame):
        decode_s1p4_position(bytes([0xCE, 0x00, 0x00, 0xCE]))  # 4 bytes


def test_decode_s1p4_position_rejects_missing_delimiters():
    with pytest.raises(InvalidS1P4Frame):
        decode_s1p4_position(bytes([0x00, 0xE1, 0x02, 0x50, 0xEC, 0xFF, 0x06, 0x00]))


def test_position_beacon_x_m_and_y_m_helpers():
    p = decode_s1p4_position(BEACON_DRIVE)
    assert p.x_m == pytest.approx(19.86)
    assert p.y_m == pytest.approx(2.48)
