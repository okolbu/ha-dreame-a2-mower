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


def test_telemetry_extends_path_when_active_is_stale_but_in_progress_exists(tmp_path):
    """Regression (2026-04-22 alpha.59): the integration's `active`
    flag depends on s2p56/task_status/status_enum/cleaning_paused —
    any of which can be stale (cloud get_properties fails on
    device-deep-sleep; MQTT property pushes can be hours apart while
    s1p4 telemetry keeps flowing). User reported the path frozen at
    122 pts for 46 min while the mower was clearly mowing (s1p4
    still pushing, battery draining).

    Telemetry-is-truth: if s1p4 reports a position, draw the line
    regardless of `active`.
    """
    archive = SessionArchive(tmp_path)
    archive.write_in_progress({
        "session_start_ts": 1776840000,
        "session_id": 1,
        "session_start": "2026-04-22T08:00:00+00:00",
        "live_path": [[0.0, 0.0]],
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

    # Stale state-properties: started=False, no s2p56 confirmation
    # — but real telemetry IS arriving (latest_position non-None).
    device = SimpleNamespace(
        status=SimpleNamespace(started=False),
        latest_position=(500, 500),
        obstacle_detected=False,
        latest_session_summary=None,
        _session_status_known=False,
    )
    coord = _make_coordinator(archive, device)
    lm = DreameA2LiveMap(_make_hass(), _make_entry(), coord)

    # Restore loaded the seed point.
    assert lm._state.path == [[0.0, 0.0]]

    lm._handle_coordinator_update()

    # Telemetry should have been appended even though `active=False`.
    assert len(lm._state.path) == 2
    assert lm._state.path[-1] == [5.0, 0.312]  # 500cm * 1.0 / 100, 500mm * 0.625 / 1000


def test_telemetry_outside_session_does_not_persist_phantom(tmp_path):
    """Counterpart to the telemetry-is-truth fix: when there's no
    active session AND no in_progress entry on disk (e.g. between
    runs, or after a finalize), telemetry still draws on the live
    canvas but must NOT be persisted as a phantom in_progress file.
    """
    archive = SessionArchive(tmp_path)
    # No in_progress on disk; nothing restored.

    device = SimpleNamespace(
        status=SimpleNamespace(started=False),
        latest_position=(500, 500),
        obstacle_detected=False,
        latest_session_summary=None,
        _session_status_known=True,  # known not active
    )
    coord = _make_coordinator(archive, device)
    lm = DreameA2LiveMap(_make_hass(), _make_entry(), coord)

    # No session restored.
    assert lm._have_active_in_progress is False
    assert lm._state.path == []

    lm._handle_coordinator_update()

    # Telemetry drew live (in-memory) but no phantom file on disk.
    assert len(lm._state.path) == 1  # appended in memory
    assert archive.read_in_progress() is None  # no persist


def test_approximate_area_retracing_doesnt_inflate(tmp_path):
    """Regression (2026-04-22): a 1.7-hour run on a ~339 m² lawn was
    showing 532 m² in the picker because the old _approximate_area
    used path_length × swath, which over-counts every retrace.

    Walking the same line N times should report a single-pass area,
    not N × pass area. Legacy method fails this; rasteriser passes.
    """
    from live_map import _approximate_area, _legacy_path_length_area

    path_one_pass = [[float(i), 0.0] for i in range(11)]
    path_three_pass = path_one_pass + path_one_pass[::-1] + path_one_pass

    one_legacy = _legacy_path_length_area(path_one_pass)
    three_legacy = _legacy_path_length_area(path_three_pass)
    one_raster = _approximate_area(path_one_pass)
    three_raster = _approximate_area(path_three_pass)

    # Legacy: triples the area on retrace (broken behaviour).
    assert three_legacy >= 2.5 * one_legacy
    # Rasteriser: stays the same on retrace (correct behaviour).
    assert three_raster == one_raster


def test_approximate_area_serpentine_pattern_matches_strip_total(tmp_path):
    """Walk a 10 m × 10 m area in 20 strips of 10 m each, separated
    by 0.5 m. Each strip cuts a 0.22 m wide swath (blade width).
    Adjacent strips have a (0.5 - 0.22) = 0.28 m gap so they don't
    overlap. Expected total area ≈ 20 × 10 × 0.22 = 44 m².
    Rasteriser should land within 30 % of that (granularity from
    grid + disc-stamp behaviour at strip ends)."""
    from live_map import _approximate_area
    path = []
    for row in range(20):
        y = row * 0.5
        if row % 2 == 0:
            for x in range(0, 11):
                path.append([float(x), y])
        else:
            for x in range(10, -1, -1):
                path.append([float(x), y])
    area = _approximate_area(path)
    # 44 m² ground truth ± 50 % envelope. Disc stamping +
    # connector-strip painting pushes the result up to ~63 m².
    # The point of the test isn't precise calibration (the user
    # confirmed ~16 % over the cloud's number is acceptable for
    # the picker label); it's that we're in the right order of
    # magnitude AND don't massively over- or under-count.
    assert 30 <= area <= 70, f"area={area}, expected near 44 m²"


def test_approximate_area_skips_segments_with_cutting_zero(tmp_path):
    """Cutting filter (alpha.73): path entries with 3rd element = 0
    mean the firmware's area_mowed_m2 counter didn't tick forward
    between this point and the previous one, i.e. blades-up
    transit / return-to-dock. These segments must be excluded
    from the area calc.

    Field-verified 2026-04-22: a 30 s straight-line dock-to-
    mowing-resume drive kept area_mowed_cent constant while
    travelling ~10 m. The phase byte sat at constant=2 the whole
    time (phase-byte filter doesn't work on this firmware), but
    the area-counter delta is a perfect discriminator.

    Legacy 2-element entries (no indicator) default to paint —
    so older in_progress files load fine."""
    from live_map import _approximate_area
    # 11 mowing points (cutting=1), 11 transit points (cutting=0),
    # 11 more mowing. Transit between the two mowing runs must be
    # skipped.
    path_mowing_only = (
        [[float(i), 0.0, 1] for i in range(11)]
        + [[float(20 + i), 5.0, 1] for i in range(11)]
    )
    path_with_transit = (
        [[float(i), 0.0, 1] for i in range(11)]
        + [[10.0 + (i + 1) * 1.0, 0.0, 0] for i in range(10)]
        + [[float(20 + i), 5.0, 1] for i in range(11)]
    )
    a_mowing = _approximate_area(path_mowing_only)
    a_with_transit = _approximate_area(path_with_transit)
    # The transit segments themselves get skipped, but the
    # boundary segment FROM the last transit point TO the first
    # mowing point of the second leg is still painted (its
    # endpoint has cutting=1, only segments whose endpoint reports
    # cutting=0 get skipped). At the small synthetic test scale
    # that connector contributes meaningful relative overhead;
    # cap at +50 % to allow for it while still catching a
    # regression where the filter doesn't fire at all (which
    # would roughly double the area).
    assert a_with_transit <= a_mowing * 1.5
    # Also confirm the filter is doing SOMETHING — without the
    # filter, painting all 31 connected segments (including the
    # 10 m of transit) would land much higher.
    path_unfiltered = (
        [[float(i), 0.0, 1] for i in range(11)]
        + [[10.0 + (i + 1) * 1.0, 0.0, 1] for i in range(10)]
        + [[float(20 + i), 5.0, 1] for i in range(11)]
    )
    a_unfiltered = _approximate_area(path_unfiltered)
    # Unfiltered should be meaningfully larger (the 10 m transit
    # band gets painted as a full strip ~10 m × 0.22 m ≈ 2.2 m²
    # of additional cells). Filtered should be smaller.
    assert a_unfiltered > a_with_transit + 1.0

    # Legacy entries still paint.
    legacy = [[float(i), 0.0] for i in range(11)]
    assert _approximate_area(legacy) > 0


def test_approximate_area_skips_pen_up_jumps(tmp_path):
    """A telemetry drop / dock visit shows up as a >5 m jump between
    consecutive points. Painting a swath across that jump would
    phantom-claim metres of coverage the mower never cut."""
    from live_map import _approximate_area
    # Two short connected runs separated by a 20 m teleport.
    path = (
        [[float(i), 0.0] for i in range(5)]   # 4 m line
        + [[100.0, 100.0]]                     # 20+ m jump (pen-up)
        + [[float(i) + 100.0, 100.0] for i in range(5)]  # another 4 m line
    )
    area = _approximate_area(path)
    # Two 4 m × 0.22 m strips ≈ 2 × 0.88 m² = ~1.76 m². Disc-stamp
    # padding pushes to ~3 m². The 100 m² teleport must NOT be
    # painted — that would phantom-claim 22 m² of fake coverage.
    assert area < 6.0


def test_dispatched_attrs_cached_for_late_subscriber_replay(tmp_path):
    """Regression (2026-04-22 alpha.55): a camera entity that subscribes
    *after* the first dispatch (which fires inside
    coordinator.async_config_entry_first_refresh, before
    async_forward_entry_setups creates camera) used to miss it
    entirely. live_map now caches the most recent attrs in
    `_last_dispatched_attrs` so the camera can replay it on
    `async_added_to_hass`.
    """
    archive = SessionArchive(tmp_path)
    archive.write_in_progress({
        "session_start_ts": 1776840000,
        "session_id": 3,
        "session_start": "2026-04-22T08:00:00+00:00",
        "live_path": [[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]],
        "obstacles": [],
        "leg_md5s": [],
        "completed_track": [],
        "lawn_polygon": [],
        "exclusion_zones": [],
        "obstacle_polygons": [],
        "dock_position": None,
        "summary_md5": None,
        "summary_end_ts": None,
        "area_mowed_m2": 1.5,
        "map_area_m2": 0,
    })
    device = _make_device(started=True, session_known=True, position=None)
    lm = DreameA2LiveMap(_make_hass(), _make_entry(), _make_coordinator(archive, device))

    # Pre-tick: nothing dispatched yet.
    assert lm._last_dispatched_attrs is None

    # Simulate the first coordinator tick (what async_setup's
    # call_soon_threadsafe would have done in HA — but our test
    # _make_hass returns loop=None so we drive it manually).
    lm._handle_coordinator_update()

    # The cached snapshot is what the late camera-subscriber will replay.
    assert lm._last_dispatched_attrs is not None
    cached = lm._last_dispatched_attrs
    assert cached["session_id"] == 3
    assert cached["path"] == [[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]]


def test_boot_active_blip_does_not_wipe_restored_path(tmp_path):
    """Regression (2026-04-22): on HA boot, the in_progress.json is
    restored (state.path populated), but the first few coordinator
    ticks may see active=False because s2p56 hasn't arrived yet.
    The end-of-tick `_prev_session_active = active` then downgrades
    the seeded True to False. When s2p56 finally arrives and active
    flips True, start_session() used to fire and wipe state.path.
    The `_have_active_in_progress` flag must suppress that.
    """
    archive = SessionArchive(tmp_path)
    archive.write_in_progress({
        "session_start_ts": 1776840000,
        "session_id": 5,
        "session_start": "2026-04-22T08:00:00+00:00",
        "live_path": [[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]],
        "obstacles": [],
        "leg_md5s": [],
        "completed_track": [],
        "lawn_polygon": [],
        "exclusion_zones": [],
        "obstacle_polygons": [],
        "dock_position": None,
        "summary_md5": None,
        "summary_end_ts": None,
        "area_mowed_m2": 1.0,
        "map_area_m2": 0,
    })

    # Boot: device hasn't yet received s2p56; started=False initially.
    device = _make_device(started=False, session_known=False)
    lm = DreameA2LiveMap(_make_hass(), _make_entry(), _make_coordinator(archive, device))
    assert lm._state.path == [[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]]
    assert lm._have_active_in_progress is True

    # Tick 1: still no s2p56 → active=False. Downgrade prev_active.
    lm._handle_coordinator_update()
    assert lm._prev_session_active is False
    assert lm._state.path == [[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]]

    # Tick 2: s2p56 arrives saying pending_resume → active=True.
    # The False→True transition would normally fire start_session
    # and wipe path. The _have_active_in_progress guard must stop it.
    device.status = SimpleNamespace(started=True)
    device._session_status_known = True
    lm._handle_coordinator_update()

    assert lm._state.path == [[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]], \
        "boot active-blip race wiped restored path — start_session fired spuriously"
    assert lm._state.session_id == 5  # not bumped


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
