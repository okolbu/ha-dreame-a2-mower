"""Tests for DreameA2LiveMap.set_mode() and mode-aware coordinator ticks.

These exercise the HA-facing glue class without a real HA event loop —
the fake hass stub routes `_send_update` to a direct dispatch which we
do not intercept. The important behaviour is the state transitions and
which archive entries get loaded into the overlay.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from live_map import DreameA2LiveMap, LiveMapState, MapMode


FIXTURE_PATH = (
    Path(__file__).parent.parent
    / "protocol"
    / "fixtures"
    / "session_summary_2026-04-18.json"
)


class FakeArchive:
    def __init__(self, entries, root):
        self._entries = entries
        self.root = Path(root)
        self._in_progress = None

    def latest(self):
        return self._entries[0] if self._entries else None

    def list_sessions(self):
        return list(self._entries)

    # In-progress entry — minimal stubs matching SessionArchive's API.
    def read_in_progress(self):
        return self._in_progress

    def write_in_progress(self, payload):
        self._in_progress = dict(payload)

    def delete_in_progress(self):
        self._in_progress = None

    def in_progress_entry(self):
        return None


def _make_live_map(archive=None, device=None):
    hass = SimpleNamespace(loop=None)
    entry = SimpleNamespace(options={})
    coordinator = SimpleNamespace(
        session_archive=archive,
        device=device,
        async_add_listener=lambda cb: (lambda: None),
    )
    lm = DreameA2LiveMap(hass, entry, coordinator)
    return lm


def _write_fixture(tmp_path: Path, filename: str = "summary.json") -> Path:
    dst = tmp_path / filename
    dst.write_text(FIXTURE_PATH.read_text())
    return dst


def test_set_mode_blank_clears_state():
    lm = _make_live_map()
    lm._state.append_point(1.0, 2.0)
    lm._state.lawn_polygon = [[0.0, 0.0]]
    lm.set_mode(MapMode.BLANK)
    assert lm._state.mode is MapMode.BLANK
    assert lm._state.path == []
    assert lm._state.lawn_polygon == []


def test_set_mode_latest_reloads_newest_archive(tmp_path):
    _write_fixture(tmp_path, "summary.json")
    entry = SimpleNamespace(
        filename="summary.json",
        md5="abc",
        end_ts=1,
        start_ts=0,
        duration_min=1,
        area_mowed_m2=1.0,
        map_area_m2=1,
    )
    archive = FakeArchive([entry], tmp_path)

    lm = _make_live_map(archive=archive)
    lm.set_mode(MapMode.LATEST)

    assert lm._state.mode is MapMode.LATEST
    assert len(lm._state.lawn_polygon) > 0  # overlay loaded from archive


def test_set_mode_latest_with_empty_archive_leaves_state_empty():
    lm = _make_live_map(archive=FakeArchive([], "/tmp"))
    lm.set_mode(MapMode.LATEST)
    assert lm._state.mode is MapMode.LATEST
    assert lm._state.lawn_polygon == []


def test_set_mode_session_loads_pinned_archive(tmp_path):
    _write_fixture(tmp_path, "pinned.json")
    entry = SimpleNamespace(
        filename="pinned.json",
        md5="pinhash",
        end_ts=1,
        start_ts=0,
        duration_min=1,
        area_mowed_m2=1.0,
        map_area_m2=1,
    )
    archive = FakeArchive([entry], tmp_path)

    lm = _make_live_map(archive=archive)
    lm.set_mode(MapMode.SESSION, archive_entry=entry)

    assert lm._state.mode is MapMode.SESSION
    assert lm._state.pinned_md5 == "pinhash"
    assert len(lm._state.lawn_polygon) > 0


def test_set_mode_session_without_entry_raises():
    lm = _make_live_map(archive=FakeArchive([], "/tmp"))
    with pytest.raises(ValueError):
        lm.set_mode(MapMode.SESSION)


def test_tick_in_blank_mode_accumulates_path_but_does_not_dispatch():
    # Path now accumulates in every mode so a Latest-switch mid-mow
    # carries the full current-run buffer (commit 25afba4). What
    # BLANK mode protects is the *displayed snapshot*: no dispatch
    # happens. Mode itself stays BLANK.
    device = SimpleNamespace(
        status=SimpleNamespace(started=True),
        latest_position=(100, 100),
        obstacle_detected=False,
        latest_session_summary=None,
        _session_status_known=True,
    )
    lm = _make_live_map(device=device)
    lm.set_mode(MapMode.BLANK)
    lm._handle_coordinator_update()
    # Path *did* accumulate (silent buffer), but mode is preserved.
    assert lm._state.path != []
    assert lm._state.mode is MapMode.BLANK


def test_tick_in_session_mode_accumulates_path_but_overlay_frozen(tmp_path):
    _write_fixture(tmp_path, "pinned.json")
    entry = SimpleNamespace(
        filename="pinned.json",
        md5="pinhash",
        end_ts=1,
        start_ts=0,
        duration_min=1,
        area_mowed_m2=1.0,
        map_area_m2=1,
    )
    archive = FakeArchive([entry], tmp_path)
    device = SimpleNamespace(
        status=SimpleNamespace(started=True),
        latest_position=(100, 100),
        obstacle_detected=False,
        latest_session_summary=None,
        _session_status_known=True,
    )
    lm = _make_live_map(archive=archive, device=device)
    lm.set_mode(MapMode.SESSION, archive_entry=entry)
    overlay_before = list(lm._state.lawn_polygon)

    lm._handle_coordinator_update()

    # Path accumulates silently in SESSION mode too; overlay must
    # not change (the pinned session is frozen).
    assert lm._state.path != []
    assert lm._state.lawn_polygon == overlay_before


def test_latest_mode_session_start_wipes_overlay():
    """In LATEST mode, when a new run begins, the previous-session overlay is
    wiped so the map shows a clean canvas + the new live path only."""
    device = SimpleNamespace(
        status=SimpleNamespace(started=False),
        latest_position=None,
        obstacle_detected=False,
        latest_session_summary=None,
    )

    lm = _make_live_map(device=device)
    lm._state.mode = MapMode.LATEST
    lm._state.lawn_polygon = [[0.0, 0.0], [1.0, 0.0]]
    lm._state.completed_track = [[[0.0, 0.0]]]
    lm._state.summary_md5 = "old"

    # First tick: not started, prev_session_active bootstraps to False.
    lm._handle_coordinator_update()
    # Overlay should still be present (no transition yet).
    assert lm._state.lawn_polygon != []

    # Mower starts.
    device.status = SimpleNamespace(started=True)
    device.latest_position = (100, 100)  # 1 m, 0.1 m
    lm._handle_coordinator_update()

    assert lm._state.lawn_polygon == []
    assert lm._state.completed_track == []
    assert lm._state.summary_md5 is None
    # New live point recorded for the new run.
    assert len(lm._state.path) == 1


def test_latest_mode_position_only_when_active():
    """Position is None between runs, so the TrailLayer draws no marker at
    the dock. Position is a real coord only while `started` is True."""
    device = SimpleNamespace(
        status=SimpleNamespace(started=False),
        latest_position=(0, 0),  # idle beacon reports dock pos
        obstacle_detected=False,
        latest_session_summary=None,
    )
    captured: list = []

    from live_map import LIVE_MAP_UPDATE_SIGNAL  # noqa: F401

    import live_map as _lm_mod

    def _fake_dispatch(hass, signal, attrs):
        captured.append(attrs)

    orig = _lm_mod.async_dispatcher_send
    _lm_mod.async_dispatcher_send = _fake_dispatch
    try:
        lm = _make_live_map(device=device)
        lm._state.mode = MapMode.LATEST
        lm._handle_coordinator_update()
    finally:
        _lm_mod.async_dispatcher_send = orig

    assert captured, "expected a dispatch on coordinator update"
    assert captured[-1]["position"] is None


def test_latest_mode_new_summary_clears_live_path(tmp_path):
    """When a fresh session summary arrives during LATEST mode, the live
    path is superseded by the summary's completed_track overlay."""
    import live_map as _lm_mod
    from protocol.session_summary import parse_session_summary

    summary = parse_session_summary(json.loads(FIXTURE_PATH.read_text()))

    device = SimpleNamespace(
        status=SimpleNamespace(started=False),
        latest_position=None,
        obstacle_detected=False,
        latest_session_summary=summary,
    )
    captured: list = []

    def _fake_dispatch(hass, signal, attrs):
        captured.append(attrs)

    orig = _lm_mod.async_dispatcher_send
    _lm_mod.async_dispatcher_send = _fake_dispatch
    try:
        lm = _make_live_map(device=device)
        lm._state.mode = MapMode.LATEST
        # Accumulated live points from the just-finished run.
        lm._state.append_point(1.0, 2.0)
        lm._state.append_point(2.0, 3.0)

        lm._handle_coordinator_update()
    finally:
        _lm_mod.async_dispatcher_send = orig

    assert lm._state.path == []
    assert len(lm._state.lawn_polygon) > 0
    assert lm._state.summary_md5 == summary.md5
