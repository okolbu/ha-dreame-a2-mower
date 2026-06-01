"""Tests for _RenderingMixin._publish_live_point / _begin_live_stream — the
client-facing live position stream that replaces server-composited trail PNGs.
"""
from __future__ import annotations

import types

from custom_components.dreame_a2_mower.coordinator._rendering import _RenderingMixin


def _make_coord():
    coord = types.SimpleNamespace()
    coord._live_point_seq = 0
    coord._latest_point = None
    coord._track_snapshot = None
    for name in ("_publish_live_point", "_begin_live_stream"):
        setattr(coord, name, types.MethodType(getattr(_RenderingMixin, name), coord))
    return coord


def test_begin_live_stream_resets():
    coord = _make_coord()
    coord._live_point_seq = 7
    coord._latest_point = [1.0, 2.0, 3.0, 4.0]
    coord._track_snapshot = [[1.0, 2.0, 3.0, 4.0]]
    coord._begin_live_stream(t=1000.0)
    assert coord._live_point_seq == 0
    assert coord._latest_point is None
    assert coord._track_snapshot == []


def test_publish_increments_seq_and_sets_latest():
    coord = _make_coord()
    coord._begin_live_stream(t=1000.0)
    coord._publish_live_point(x_m=1.5, y_m=2.5, heading_deg=90.0, t=1001.0)
    assert coord._live_point_seq == 1
    assert coord._latest_point == [1.5, 2.5, 90.0, 1001.0]
    assert coord._track_snapshot == [[1.5, 2.5, 90.0, 1001.0]]

    coord._publish_live_point(x_m=2.0, y_m=3.0, heading_deg=180.0, t=1002.0)
    assert coord._live_point_seq == 2
    assert coord._latest_point == [2.0, 3.0, 180.0, 1002.0]
    assert coord._track_snapshot == [
        [1.5, 2.5, 90.0, 1001.0],
        [2.0, 3.0, 180.0, 1002.0],
    ]


def test_publish_byte_heading_preserved():
    coord = _make_coord()
    coord._begin_live_stream(t=0.0)
    coord._publish_live_point(x_m=0.0, y_m=0.0, heading_deg=123.4, t=1.0)
    # Byte heading is published as-is (NOT nulled for beacons — the coordinator
    # only sees MowerState, no frame length; the client has a vector fallback).
    assert coord._latest_point[2] == 123.4


def test_publish_none_heading_passes_through():
    coord = _make_coord()
    coord._begin_live_stream(t=0.0)
    coord._publish_live_point(x_m=0.0, y_m=0.0, heading_deg=None, t=1.0)
    assert coord._latest_point[2] is None


def test_publish_without_begin_does_not_crash_on_none_snapshot():
    # _track_snapshot is None before _begin_live_stream; publish must not crash.
    coord = _make_coord()
    coord._publish_live_point(x_m=0.0, y_m=0.0, heading_deg=0.0, t=1.0)
    assert coord._live_point_seq == 1
    assert coord._latest_point == [0.0, 0.0, 0.0, 1.0]
    assert coord._track_snapshot is None
