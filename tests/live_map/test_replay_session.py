"""Tests for `DreameA2LiveMap.replay_session` — archive-driven playback.

The method reads one of the archived session-summary JSON files on disk
and pushes its decoded overlay into the camera's live-map attributes,
same shape as the normal per-session dispatch. Used by the
`dreame_a2_mower.replay_session` HA service.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from live_map import LiveMapState


FIXTURE_PATH = (
    Path(__file__).parent.parent
    / "protocol"
    / "fixtures"
    / "session_summary_2026-04-18.json"
)


@pytest.fixture
def raw_summary_json() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def test_state_loads_overlay_fields_from_fixture(raw_summary_json):
    """Archived summary JSON parses and populates the LiveMapState overlay
    fields that a map card needs for replay (lawn polygon, completed
    track segments, obstacle polygons, exclusion zones, dock)."""
    from protocol.session_summary import parse_session_summary

    state = LiveMapState()
    summary = parse_session_summary(raw_summary_json)
    changed = state.load_from_session_summary(summary)
    assert changed is True

    # Sanity-check the shape of each populated field.
    assert isinstance(state.lawn_polygon, list)
    assert len(state.lawn_polygon) > 0
    assert all(isinstance(pt, list) and len(pt) == 2 for pt in state.lawn_polygon)

    assert isinstance(state.completed_track, list)
    assert all(isinstance(seg, list) for seg in state.completed_track)

    assert isinstance(state.obstacle_polygons, list)
    assert isinstance(state.exclusion_zones, list)


def test_loading_same_summary_twice_is_idempotent(raw_summary_json):
    from protocol.session_summary import parse_session_summary

    state = LiveMapState()
    summary = parse_session_summary(raw_summary_json)
    first = state.load_from_session_summary(summary)
    second = state.load_from_session_summary(summary)
    assert first is True
    assert second is False  # md5 unchanged → no-op


def test_attributes_include_frozen_overlay(raw_summary_json):
    """`to_attributes()` must surface the replay overlay so the dispatched
    snapshot carries everything a map card needs to redraw."""
    from protocol.session_summary import parse_session_summary

    state = LiveMapState()
    summary = parse_session_summary(raw_summary_json)
    state.load_from_session_summary(summary)
    attrs = state.to_attributes(position=None, x_factor=1.0, y_factor=1.0)

    assert "lawn_polygon" in attrs
    assert "completed_track" in attrs
    assert "obstacle_polygons" in attrs
    assert "exclusion_zones" in attrs
    assert attrs["lawn_polygon"] == state.lawn_polygon
    assert attrs["summary_md5"] == state.summary_md5


def test_replay_from_file_returns_summary_stats(tmp_path: Path, raw_summary_json):
    """Pure function: given a JSON file path, read + parse + return the
    state that a caller should dispatch."""
    from live_map import replay_from_archive_file

    fixture_file = tmp_path / "sample.json"
    fixture_file.write_text(json.dumps(raw_summary_json))

    state = LiveMapState()
    result = replay_from_archive_file(state, fixture_file, x_factor=1.0, y_factor=1.0)

    assert result["path_points"] > 0  # total points across all track segments
    assert result["md5"] == state.summary_md5
    assert result["segments"] == len(state.completed_track)
    # State got populated with the full overlay.
    assert len(state.lawn_polygon) > 0
    assert len(state.completed_track) > 0


def test_replay_keeps_path_empty_to_avoid_ghost_segments(tmp_path: Path, raw_summary_json):
    """`state.path` is drawn as a single polyline, so flattening the
    multi-segment completed_track into it would render straight lines
    across every pen-up gap. Keep path empty during replay and let the
    TrailLayer render completed_track segment-by-segment."""
    from live_map import replay_from_archive_file

    fixture_file = tmp_path / "sample.json"
    fixture_file.write_text(json.dumps(raw_summary_json))

    state = LiveMapState()
    replay_from_archive_file(state, fixture_file, x_factor=1.0, y_factor=1.0)

    assert state.path == []
    # completed_track is what carries the per-segment geometry.
    assert len(state.completed_track) > 0


def test_replay_from_missing_file_raises():
    from live_map import replay_from_archive_file

    state = LiveMapState()
    with pytest.raises(FileNotFoundError):
        replay_from_archive_file(
            state, Path("/nonexistent/nope.json"), x_factor=1.0, y_factor=1.0
        )


def test_replay_from_malformed_file_raises(tmp_path: Path):
    from live_map import replay_from_archive_file

    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")

    state = LiveMapState()
    with pytest.raises(ValueError):
        replay_from_archive_file(state, bad, x_factor=1.0, y_factor=1.0)
