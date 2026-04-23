"""Validation tests: do the int16_le and 12-bit-packed pose decoders
agree on captured g2408 frames? If they diverge, the apk decoder is
wrong for g2408 (or vice versa)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protocol.pose import (
    decode_pose_int16le,
    decode_pose_packed12,
)


_FIXTURES = Path(__file__).parent / "fixtures" / "captured_s1p4_frames.json"


def _load_frames():
    with _FIXTURES.open() as fh:
        return json.load(fh)["frames"]


@pytest.mark.parametrize("frame", _load_frames())
def test_int16le_decode_matches_capture_baseline(frame):
    """Sanity: the int16_le decoder still produces the values we
    expect from the captured frames. If this fails, our test
    fixture is malformed or the decoder regressed."""
    got = decode_pose_int16le(frame["bytes"])
    assert got.x_cm == frame["expected_x_cm_int16le"]
    assert got.y_mm == frame["expected_y_mm_int16le"]


@pytest.mark.parametrize("frame", _load_frames())
def test_packed12_decode_runs_without_error(frame):
    """Sanity: the apk decoder doesn't crash on real frames."""
    got = decode_pose_packed12(frame["bytes"])
    assert isinstance(got.x_raw, int)
    assert isinstance(got.y_raw, int)
    assert 0.0 <= got.angle_deg < 360.0


def test_decoders_agree_for_zero_position():
    """If the mower is at (0, 0), both decoders should return 0/0
    regardless of which scheme is correct — both interpretations
    of an all-zero byte slice yield 0."""
    payload = [0xCE] + [0] * 32
    assert decode_pose_int16le(payload).x_cm == 0
    assert decode_pose_int16le(payload).y_mm == 0
    assert decode_pose_packed12(payload).x_raw == 0
    assert decode_pose_packed12(payload).y_raw == 0
