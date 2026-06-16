"""Tests for _RenderingMixin live position stream + backfill snapshot.

The card draws the trail client-side: ``latest_point`` / ``point_seq`` drive
incremental live painting; ``live_track_snapshot()`` is the cold-start backfill,
derived from the authoritative ``live_map.track`` (so it survives a restart) and
decimated for the wire. There is no longer a separate ``_track_snapshot`` mirror.
"""
from __future__ import annotations

import types

from custom_components.dreame_a2_mower.coordinator._rendering import (
    LIVE_TRACK_SNAPSHOT_MAX,
    _RenderingMixin,
)
from custom_components.dreame_a2_mower.live_map.state import TrackPoint


def _tp(i, *, x=None, y=0.0, hdg=None, t=None, area=0.0, role="mowing"):
    return TrackPoint(
        t=float(i if t is None else t),
        x_m=float(i if x is None else x),
        y_m=float(y),
        area_m2=float(area),
        heading_deg=hdg,
        task_state=0,
        role=role,
    )


def _make_coord(track=None):
    coord = types.SimpleNamespace()
    coord._live_point_seq = 0
    coord._latest_point = None
    coord._track_snapshot_cache = None
    coord.live_map = types.SimpleNamespace(track=list(track or []))
    for name in ("_publish_live_point", "_begin_live_stream", "live_track_snapshot"):
        setattr(coord, name, types.MethodType(getattr(_RenderingMixin, name), coord))
    return coord


def test_begin_live_stream_resets_seq_latest_and_cache():
    coord = _make_coord()
    coord._live_point_seq = 7
    coord._latest_point = [1.0, 2.0, 3.0, 4.0]
    coord._track_snapshot_cache = (5, [[1.0, 2.0, 3.0, 4.0]])
    coord._begin_live_stream()
    assert coord._live_point_seq == 0
    assert coord._latest_point is None
    assert coord._track_snapshot_cache is None


def test_publish_increments_seq_and_sets_latest():
    coord = _make_coord()
    coord._begin_live_stream()
    coord._publish_live_point(x_m=1.5, y_m=2.5, heading_deg=90.0, t=1001.0)
    assert coord._live_point_seq == 1
    assert coord._latest_point == [1.5, 2.5, 90.0, 1001.0]

    coord._publish_live_point(x_m=2.0, y_m=3.0, heading_deg=180.0, t=1002.0)
    assert coord._live_point_seq == 2
    assert coord._latest_point == [2.0, 3.0, 180.0, 1002.0]


def test_publish_byte_heading_preserved():
    coord = _make_coord()
    coord._begin_live_stream()
    coord._publish_live_point(x_m=0.0, y_m=0.0, heading_deg=123.4, t=1.0)
    # Byte heading is published as-is (NOT nulled for beacons — the coordinator
    # only sees MowerState, no frame length; the client has a vector fallback).
    assert coord._latest_point[2] == 123.4


def test_publish_none_heading_passes_through():
    coord = _make_coord()
    coord._begin_live_stream()
    coord._publish_live_point(x_m=0.0, y_m=0.0, heading_deg=None, t=1.0)
    assert coord._latest_point[2] is None


def test_live_track_snapshot_derives_rows_from_track():
    track = [
        _tp(0, x=0.0, y=0.0, hdg=None, t=1230.0),
        _tp(1, x=1.0, y=2.0, hdg=90.0, t=1234.0),
    ]
    coord = _make_coord(track)
    # Card contract: [x_m, y_m, heading_deg|None, t] per point, in capture order.
    assert coord.live_track_snapshot() == [
        [0.0, 0.0, None, 1230.0],
        [1.0, 2.0, 90.0, 1234.0],
    ]


def test_live_track_snapshot_empty_when_no_track():
    coord = _make_coord([])
    assert coord.live_track_snapshot() == []


def test_live_track_snapshot_survives_restart():
    # Gap-1 regression: a fresh coordinator (cache None, no _begin_live_stream —
    # the restore path skips it) whose live_map.track was repopulated from
    # in_progress.json must still serve the full backfill.
    track = [_tp(i, x=float(i), t=float(i)) for i in range(5)]
    coord = _make_coord(track)
    snap = coord.live_track_snapshot()
    assert len(snap) == 5
    assert snap[0] == [0.0, 0.0, None, 0.0]
    assert snap[-1] == [4.0, 0.0, None, 4.0]


def test_live_track_snapshot_decimates_keeping_first_and_last():
    # Gap-2 regression: over-cap tracks are DECIMATED (full extent preserved),
    # never truncated-from-the-front.
    n = LIVE_TRACK_SNAPSHOT_MAX * 3 + 7
    track = [_tp(i, x=float(i), t=float(i)) for i in range(n)]
    coord = _make_coord(track)
    snap = coord.live_track_snapshot()
    assert len(snap) <= LIVE_TRACK_SNAPSHOT_MAX + 1
    assert snap[0][0] == 0.0                 # earliest point kept
    assert snap[-1][0] == float(n - 1)       # latest point kept


def test_live_track_snapshot_cached_until_track_grows():
    track = [_tp(i) for i in range(3)]
    coord = _make_coord(track)
    first = coord.live_track_snapshot()
    # Repeated reads between appends reuse the cached list (identity check).
    assert coord.live_track_snapshot() is first
    coord.live_map.track.append(_tp(3))
    second = coord.live_track_snapshot()
    assert second is not first
    assert len(second) == 4
