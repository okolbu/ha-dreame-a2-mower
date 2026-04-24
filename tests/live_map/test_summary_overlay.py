"""Tests for the session-summary overlay in LiveMapState."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from live_map import LiveMapState
from protocol.session_summary import parse_session_summary


FIXTURE_PATH = (
    Path(__file__).parent.parent / "protocol" / "fixtures" / "session_summary_2026-04-18.json"
)


@pytest.fixture
def summary():
    return parse_session_summary(json.loads(FIXTURE_PATH.read_text()))


def test_fresh_state_has_empty_overlay_fields():
    s = LiveMapState()
    assert s.lawn_polygon == []
    assert s.exclusion_zones == []
    assert s.completed_track == []
    assert s.obstacle_polygons == []
    assert s.dock_position is None
    assert s.summary_md5 is None


def test_load_from_session_summary_populates_all_overlay_fields(summary):
    s = LiveMapState()
    changed = s.load_from_session_summary(summary)

    assert changed is True
    assert len(s.lawn_polygon) == 481
    assert s.lawn_polygon[0] == [-4.70, -14.08]
    assert len(s.exclusion_zones) == 1
    assert len(s.exclusion_zones[0]) == 4
    assert len(s.completed_track) >= 200  # 280 breaks → ~281 segments
    assert len(s.obstacle_polygons) == 7
    assert s.obstacle_polygons[0][0] == [-1.10, 11.63]
    assert s.dock_position == [1.54, 0.02]
    assert s.summary_md5 == "f7335acc02f19d78345cb037f8875101"
    assert s.summary_end_ts == 1776541055


def test_load_from_session_summary_is_idempotent(summary):
    s = LiveMapState()
    assert s.load_from_session_summary(summary) is True
    # Second call with the same summary returns False and leaves state.
    assert s.load_from_session_summary(summary) is False


def test_load_from_none_is_noop():
    s = LiveMapState()
    assert s.load_from_session_summary(None) is False
    assert s.lawn_polygon == []


def test_overlay_cleared_by_set_mode_latest(summary):
    """Switching to LATEST clears the overlay; the coordinator is expected
    to reload the newest archive into the overlay right after. In LATEST
    mode we show the *most recent* thing — not whatever was previously
    loaded."""
    from live_map import MapMode

    s = LiveMapState()
    s.load_from_session_summary(summary)
    assert s.lawn_polygon != []

    s.set_mode(MapMode.LATEST)

    assert s.lawn_polygon == []
    assert s.summary_md5 is None
    assert s.path == []


def test_to_attributes_includes_overlay(summary):
    s = LiveMapState()
    s.load_from_session_summary(summary)
    attrs = s.to_attributes(position=[0.5, 0.5])

    assert "lawn_polygon" in attrs
    assert len(attrs["lawn_polygon"]) == 481
    assert "exclusion_zones" in attrs
    assert "completed_track" in attrs
    assert "obstacle_polygons" in attrs
    assert "dock_position" in attrs
    assert attrs["dock_position"] == [1.54, 0.02]
    assert attrs["summary_end_ts"] == 1776541055


def test_to_attributes_omits_dock_when_unknown():
    s = LiveMapState()
    attrs = s.to_attributes(position=None)
    assert attrs["dock_position"] is None
    assert attrs["lawn_polygon"] == []


def test_load_detects_new_summary_by_md5():
    """Simulated second session with different md5 should replace the overlay."""
    s = LiveMapState()

    class FakeSummary:
        def __init__(self, md5, polygon, end_ts):
            self.md5 = md5
            self.end_ts = end_ts
            self.lawn_polygon = polygon
            self.track_segments = ()
            self.exclusions = ()
            self.obstacles = ()
            self.dock = None

    a = FakeSummary("hash-a", [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)], 100)
    b = FakeSummary("hash-b", [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0)], 200)

    assert s.load_from_session_summary(a) is True
    assert len(s.lawn_polygon) == 3
    assert s.load_from_session_summary(a) is False  # same hash
    assert s.load_from_session_summary(b) is True   # new hash
    assert s.lawn_polygon == [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0]]
    assert s.summary_md5 == "hash-b"
