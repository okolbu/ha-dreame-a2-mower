"""Tests for in-progress entry persistence + restore + finalize.

Covers the architecture described in TODO.md "In-progress session
architecture (landed)" — sessions/in_progress.json replaces the old
drafts/ store, restored on boot, auto-closed on session end, and
exposed through finalize_session() for the manual override case.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from live_map import DreameA2LiveMap, MapMode
from session_archive import SessionArchive, IN_PROGRESS_NAME


def _make_coordinator(archive, device):
    return SimpleNamespace(
        session_archive=archive,
        device=device,
        async_add_listener=lambda cb: (lambda: None),
    )


def _make_hass():
    return SimpleNamespace(
        loop=None,
        config=SimpleNamespace(path=lambda *parts: str(Path("/tmp/_unused").joinpath(*parts))),
    )


def _make_entry():
    return SimpleNamespace(options={})


def _make_device(*, started=False, session_known=False, position=None):
    """Build a device stub that satisfies live_map's reads."""
    return SimpleNamespace(
        status=SimpleNamespace(started=started),
        latest_position=position,
        obstacle_detected=False,
        latest_session_summary=None,
        _session_status_known=session_known,
    )


def test_restore_in_progress_on_init(tmp_path):
    archive = SessionArchive(tmp_path)
    archive.write_in_progress({
        "session_start_ts": 1776840000,
        "session_id": 5,
        "session_start": "2026-04-22T08:07:05+00:00",
        "live_path": [[1.0, 2.0], [1.5, 2.5]],
        "obstacles": [],
        "leg_md5s": ["legA"],
        "completed_track": [[[0.0, 0.0], [0.5, 0.5]]],
        "lawn_polygon": [[0.0, 0.0], [10.0, 10.0]],
        "exclusion_zones": [],
        "obstacle_polygons": [],
        "dock_position": [0.1, 0.2],
        "summary_md5": None,
        "summary_end_ts": None,
        "area_mowed_m2": 1.23,
        "map_area_m2": 0,
    })
    device = _make_device(started=False, session_known=False)
    lm = DreameA2LiveMap(_make_hass(), _make_entry(), _make_coordinator(archive, device))

    # State restored from disk.
    assert lm._state.path == [[1.0, 2.0], [1.5, 2.5]]
    assert lm._state.lawn_polygon == [[0.0, 0.0], [10.0, 10.0]]
    assert lm._state.completed_track == [[[0.0, 0.0], [0.5, 0.5]]]
    assert lm._state.dock_position == [0.1, 0.2]
    assert lm._in_progress_leg_md5s == ["legA"]
    # Seeded so the first tick doesn't re-fire start_session().
    assert lm._prev_session_active is True


def test_persist_in_progress_during_active_mow(tmp_path):
    archive = SessionArchive(tmp_path)
    device = _make_device(started=True, session_known=True, position=(100, 100))
    lm = DreameA2LiveMap(_make_hass(), _make_entry(), _make_coordinator(archive, device))

    lm._handle_coordinator_update()

    saved = archive.read_in_progress()
    assert saved is not None
    assert saved["session_start_ts"] > 0
    assert saved["live_path"] == [[1.0, 0.062]]


def test_auto_finalize_on_session_end_no_legs_synthesizes_incomplete(tmp_path):
    """Session ended without any cloud leg summary — we have only the
    captured live path. Auto-close must promote it to an "(incomplete)"
    archive entry rather than silently throw it away."""
    archive = SessionArchive(tmp_path)
    archive.write_in_progress({
        "session_start_ts": 1776840000,
        "live_path": [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]],
        "obstacles": [],
        "leg_md5s": [],
        "completed_track": [],
        "lawn_polygon": [],
        "exclusion_zones": [],
        "obstacle_polygons": [],
        "dock_position": None,
        "summary_md5": None,
        "summary_end_ts": None,
        "area_mowed_m2": 0.5,
        "map_area_m2": 0,
    })
    # Restore from disk (boot path).
    device = _make_device(started=False, session_known=False)
    lm = DreameA2LiveMap(_make_hass(), _make_entry(), _make_coordinator(archive, device))
    assert archive.read_in_progress() is not None  # restored

    # The auto-finalize gate now requires sustained idle. Skip the
    # 120s wait by simulating an already-elapsed inactive period.
    import time as _time
    device._session_status_known = True
    lm._inactive_since = _time.monotonic() - 200.0
    lm._handle_coordinator_update()

    # In-progress is gone; an incomplete archive entry took its place.
    assert archive.read_in_progress() is None
    assert archive.count == 1
    entry = archive.list_sessions()[0]
    raw = archive.load(entry)
    assert raw is not None
    assert raw.get("_incomplete") is True
    assert raw.get("_synthesized_by") == "finalize_session"
    assert len(raw["live_path"]) == 3


def test_auto_finalize_with_existing_legs_just_drops_in_progress(tmp_path):
    """If at least one leg summary fired during the run, the per-leg
    entries are already in the archive — auto-close just removes the
    in-progress aggregator without writing anything."""
    archive = SessionArchive(tmp_path)
    archive.write_in_progress({
        "session_start_ts": 1776840000,
        "live_path": [[0.0, 0.0], [1.0, 0.0]],
        "obstacles": [],
        "leg_md5s": ["legA"],   # at least one leg already recorded
        "completed_track": [],
        "lawn_polygon": [],
        "exclusion_zones": [],
        "obstacle_polygons": [],
        "dock_position": None,
        "summary_md5": None,
        "summary_end_ts": None,
        "area_mowed_m2": 0.0,
        "map_area_m2": 0,
    })
    device = _make_device(started=False, session_known=False)
    lm = DreameA2LiveMap(_make_hass(), _make_entry(), _make_coordinator(archive, device))

    # Same as above: bypass the 120s sustained-idle debounce.
    import time as _time
    device._session_status_known = True
    lm._inactive_since = _time.monotonic() - 200.0
    lm._handle_coordinator_update()

    # No synthesized entry — leg summaries already on disk would be the
    # archive's responsibility, not finalize's.
    assert archive.read_in_progress() is None
    assert archive.count == 0


def test_recharge_transition_does_not_trigger_finalize(tmp_path):
    """Regression: at recharge time the mower goes IDLE → BACK_HOME →
    CHARGING for ~50 s before s2p56 sends pending_resume (code 4).
    The auto-finalize gate must NOT fire during that gap, otherwise
    the in-progress entry gets deleted and a fresh start_session
    creates a phantom new run when pending_resume arrives."""
    archive = SessionArchive(tmp_path)
    archive.write_in_progress({
        "session_start_ts": 1776840000,
        "live_path": [[0.0, 0.0], [1.0, 1.0]],
        "obstacles": [],
        "leg_md5s": [],
        "completed_track": [],
        "lawn_polygon": [],
        "exclusion_zones": [],
        "obstacle_polygons": [],
        "dock_position": None,
        "summary_md5": None,
        "summary_end_ts": None,
        "area_mowed_m2": 0.0,
        "map_area_m2": 0,
    })

    # Simulate the recharge window: started=False but status enum
    # reports BACK_HOME / CHARGING — the recharge-state gate must
    # suppress finalize entirely.
    try:
        from dreame.const import DreameMowerStatus as _S
    except ImportError:
        _S = None
    pytest_skip = _S is None
    if pytest_skip:
        pytest.skip("DreameMowerStatus enum unavailable in test env")

    device = SimpleNamespace(
        status=SimpleNamespace(started=False, status=_S.BACK_HOME),
        latest_position=None,
        obstacle_detected=False,
        latest_session_summary=None,
        _session_status_known=True,
    )
    lm = DreameA2LiveMap(_make_hass(), _make_entry(), _make_coordinator(archive, device))
    # Pretend a long time has passed in the inactive state — the
    # recharge gate should still keep the timer disarmed.
    import time as _time
    lm._inactive_since = _time.monotonic() - 200.0
    lm._prev_session_active = True

    lm._handle_coordinator_update()

    # In-progress survives unchanged; timer was reset.
    assert archive.read_in_progress() is not None
    assert lm._inactive_since is None


def test_finalize_session_returns_no_in_progress_when_clean(tmp_path):
    archive = SessionArchive(tmp_path)
    device = _make_device(started=False, session_known=True)
    lm = DreameA2LiveMap(_make_hass(), _make_entry(), _make_coordinator(archive, device))

    result = lm.finalize_session()
    assert result == {"result": "no_in_progress"}


def test_leg_merge_skips_stale_summary_from_previous_run(tmp_path):
    """Regression: device.latest_session_summary is sticky after a run
    completes. When a new run starts, the leg-merge code MUST NOT
    absorb that previous summary's tracks into the fresh in-progress
    entry — only legs whose start_ts falls inside the current session
    window should merge."""
    archive = SessionArchive(tmp_path)
    # Stale summary from a run that ended an hour ago.
    stale = SimpleNamespace(
        md5="stale-md5",
        start_ts=1776840000,
        end_ts=1776843600,
        track_segments=[[(0.0, 0.0), (1.0, 1.0)]],
        lawn_polygon=[(0.0, 0.0), (10.0, 10.0)],
        exclusions=[],
        obstacles=[],
        dock=(0.0, 0.0),
    )
    device = _make_device(started=True, session_known=True, position=(100, 100))
    device.latest_session_summary = stale
    lm = DreameA2LiveMap(_make_hass(), _make_entry(), _make_coordinator(archive, device))

    # Force a fresh session boundary well after the stale leg ended.
    lm._prev_session_active = False
    lm._handle_coordinator_update()

    # The fresh session_start is "now"; stale.start_ts is an hour
    # before that, so the merge gate must reject it.
    assert lm._state.completed_track == []
    assert lm._state.lawn_polygon == []
    # md5 still recorded so we don't keep evaluating it every tick.
    assert "stale-md5" in lm._in_progress_leg_md5s


def test_leg_merge_accepts_summary_inside_current_session(tmp_path):
    """Counterpart to the regression test — a leg whose start_ts lies
    inside the current session window MUST merge so multi-leg
    recharge cycles still aggregate correctly."""
    import time as _time
    archive = SessionArchive(tmp_path)
    now = int(_time.time())
    fresh = SimpleNamespace(
        md5="fresh-md5",
        start_ts=now,            # leg started right now
        end_ts=now + 60,
        track_segments=[[(2.0, 2.0), (3.0, 3.0)]],
        lawn_polygon=[(0.0, 0.0), (5.0, 5.0)],
        exclusions=[],
        obstacles=[],
        dock=(0.0, 0.0),
    )
    device = _make_device(started=True, session_known=True, position=(100, 100))
    device.latest_session_summary = fresh
    lm = DreameA2LiveMap(_make_hass(), _make_entry(), _make_coordinator(archive, device))
    lm._prev_session_active = False
    lm._handle_coordinator_update()

    assert "fresh-md5" in lm._in_progress_leg_md5s
    assert lm._state.completed_track == [[[2.0, 2.0], [3.0, 3.0]]]
    assert lm._state.lawn_polygon == [[0.0, 0.0], [5.0, 5.0]]


def test_restore_self_heals_poisoned_completed_track(tmp_path):
    """alpha.46-on-disk in-progress entries may carry the previous
    run's completed_track merged in. Restore should drop overlay
    fields whose summary_end_ts is older than this session's start."""
    import time as _time
    archive = SessionArchive(tmp_path)
    now = int(_time.time())
    archive.write_in_progress({
        "session_start_ts": now,
        "session_id": 1,
        "session_start": _make_session_start_iso(now),
        "live_path": [[0.0, 0.0]],
        "obstacles": [],
        "leg_md5s": ["stale-md5"],
        # Bogus carry-over from the previous run (end_ts before this session).
        "completed_track": [[[5.0, 5.0], [6.0, 6.0]]],
        "lawn_polygon": [[0.0, 0.0], [10.0, 10.0]],
        "exclusion_zones": [],
        "obstacle_polygons": [],
        "dock_position": [0.0, 0.0],
        "summary_md5": "stale-md5",
        "summary_end_ts": now - 3600,   # an hour before this session
        "area_mowed_m2": 0.0,
        "map_area_m2": 0,
    })
    device = _make_device(started=False, session_known=False)
    lm = DreameA2LiveMap(_make_hass(), _make_entry(), _make_coordinator(archive, device))

    # Self-heal: poisoned overlay dropped.
    assert lm._state.completed_track == []
    assert lm._state.lawn_polygon == []
    assert lm._in_progress_leg_md5s == []
    # Live path is preserved (it's ours, not poisoned).
    assert lm._state.path == [[0.0, 0.0]]


def _make_session_start_iso(unix_ts: int) -> str:
    import datetime as _dt
    return _dt.datetime.fromtimestamp(unix_ts, tz=_dt.timezone.utc).isoformat(timespec="seconds")


def test_finalize_session_archives_incomplete_when_path_only(tmp_path):
    archive = SessionArchive(tmp_path)
    archive.write_in_progress({
        "session_start_ts": 1776840000,
        "live_path": [[0.0, 0.0], [3.0, 4.0]],  # 5m total
        "obstacles": [],
        "leg_md5s": [],
        "completed_track": [],
        "lawn_polygon": [],
        "exclusion_zones": [],
        "obstacle_polygons": [],
        "dock_position": None,
        "summary_md5": None,
        "summary_end_ts": None,
        "area_mowed_m2": 0.0,
        "map_area_m2": 0,
    })
    device = _make_device(started=False, session_known=True)
    lm = DreameA2LiveMap(_make_hass(), _make_entry(), _make_coordinator(archive, device))

    # Avoid the auto-fire from __init__ + first tick by calling
    # finalize_session() directly (the auto path is exercised
    # by test_auto_finalize_on_session_end_no_legs_synthesizes_incomplete).
    result = lm.finalize_session()
    assert result["result"] == "archived_incomplete"
    assert result["area_mowed_m2"] > 0
    assert archive.count == 1
    assert archive.read_in_progress() is None
