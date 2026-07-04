"""P2 Task 7 (R-17/T7-19 + R-38/T3-6) — finalize interleaving pins.

Extends the barrier-executor technique from test_finalize_latch.py to the
interleavings the latch test does NOT cover:

  (a) CROSS-WRITER race — _do_oss_fetch (cloud-summary arm) racing
      _run_finalize_incomplete (local arm) for the SAME session, in both
      entry orders. The latch (_finalize_lock + _finalizing_start_ts)
      must serialize them and the loser must no-op: exactly ONE archive
      row, written by whichever writer entered first.
  (b) RESTORE-AT-BOOT × finalize — a finalize that completes inside
      _restore_in_progress's disk-read executor window must not be
      resurrected as a zombie live session from the stale disk payload.
  (c) RAIN-VETO during route-arm — pins that the rain veto fires at
      DECISION time (live_map/finalize.decide; also entry of
      _finalize_non_mow_immediate) and is deliberately NOT re-checked
      after the dock-wait: a rain edge landing mid-wait does not abort
      an already-armed cloud finalize.
  (d) DOCK-WAIT single-flight (T3-6 fix contract) — N concurrent retry
      ticks entering the dock-wait produce ONE waiter, the attempt is
      stamped BEFORE the wait, the Event is never clobbered, and exactly
      one archive write follows the dock signal.

These tests are also P3's safety net for the session-service extraction:
they pin finalize ordering/latch semantics VERBATIM.
"""
from __future__ import annotations

import asyncio
import json

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.live_map.finalize import FinalizeAction
from custom_components.dreame_a2_mower.state import MowerState

from tests.factories import make_coordinator

T0 = 1_700_000_000

# Minimal valid session-summary JSON that parse_session_summary can consume
# (same shape as _MINIMAL_SUMMARY_JSON in tests/integration/test_coordinator.py).
_CLOUD_SUMMARY_JSON = {
    "start": T0,
    "end": T0 + 3600,
    "time": 60,
    "mode": 0,
    "result": 0,
    "stop_reason": 0,
    "start_mode": 0,
    "pre_type": 0,
    "md5": "cloud-md5-xw",
    "areas": 120.5,
    "map_area": 5000,
    "dock": None,
    "pref": [],
    "region_status": [],
    "faults": [],
    "spot": [],
    "ai_obstacle": [],
    "obstacle": [],
    "map": [],
    "trajectory": [],
}


class _EventSpyCoord(DreameA2MowerCoordinator):
    """Coordinator subclass that records every Event assigned to
    _pending_finalize_done, so tests can count how many dock-wait waiters
    were actually created (the T3-6 single-flight observable)."""

    @property
    def _pending_finalize_done(self):  # type: ignore[override]
        return self.__dict__.get("_pfd_current")

    @_pending_finalize_done.setter
    def _pending_finalize_done(self, value):
        self.__dict__["_pfd_current"] = value
        if value is not None:
            self.__dict__.setdefault("_pfd_created", []).append(value)


def _build_coord(cls=DreameA2MowerCoordinator, *, pending_object_name=None):
    """REAL coordinator wired for BOTH terminal writers + the dispatch path.

    P3 Task 1: factory-built through the real ``__init__`` (which owns the
    finalize latch, dock-wait plumbing, live_map, novel_registry, and the
    session archive — all previously hand-seeded here after ``__new__``).
    The cloud client is a MagicMock at the client boundary. Only
    side-effect-only helpers are mocked (_clear_pending_op,
    _inject_live_map_into_raw_dict, _fire_mowing_ended, _photo_archive) —
    the finalize ordering itself is real.

    The factory hass runs executor jobs inline via an AsyncMock whose
    ``.side_effect`` the barrier tests below swap, and schedules
    ``async_create_task`` coroutines as real tasks (T3-8: the dock-wait is
    wrapped in a Task so unload can cancel it).
    """
    cloud = MagicMock()
    cloud.get_interim_file_url.return_value = "https://oss.example.com/signed"
    cloud.get_file.return_value = json.dumps(_CLOUD_SUMMARY_JSON).encode()

    c = make_coordinator(
        cls=cls,
        cloud=cloud,
        data=MowerState(
            pending_session_object_name=pending_object_name,
            pending_session_first_event_unix=(T0 + 3600) if pending_object_name else None,
            pending_session_attempt_count=0 if pending_object_name else None,
            area_mowed_m2=120.5,
        ),
        _active_map_id=0,
        _real_task_state_observed=True,
        # Side-effect-only collaborators of _do_oss_fetch_body.
        _photo_archive=MagicMock(count=0),
        _photo_sign_fn=None,
        _clear_pending_op=MagicMock(),
        _inject_live_map_into_raw_dict=MagicMock(),
        _fire_mowing_ended=MagicMock(),
    )
    # The real __init__ pointed session_archive at the factory's per-call
    # temp config dir — each _build_coord already gets an isolated archive.

    c.cloud_state = MagicMock()
    c.cloud_state.maps_by_id = {}

    # Record every published MowerState so tests can assert on transient
    # values (e.g. the pre-wait attempt stamp) after the fact.
    c._published_states = []

    def _set_data(new):
        c.data = new
        c._published_states.append(new)

    c.async_set_updated_data = _set_data
    return c


def _begin_mow_session(c):
    """Start a live session with mow evidence (area delta > 0) so the
    provisional type classifies as `mow` → cloud-finalized routing."""
    c.live_map.begin_session(T0)
    c.live_map.append_point(t=T0 + 10, x_m=1.0, y_m=1.0, area_m2=0.0, heading_deg=0.0)
    c.live_map.append_point(t=T0 + 20, x_m=2.0, y_m=1.0, area_m2=1.5, heading_deg=0.0)
    # In production the mow-evidence latch is set by the s1p4 telemetry
    # handler (_mqtt_handlers, "latches area_ever_positive when > 0") —
    # append_point itself does not latch it. Mirror the latch here.
    c.live_map.area_ever_positive = True


def _counting_archive(c):
    """Wrap session_archive.archive so calls are counted (identity of the
    wrapper matters: barrier executors key on `fn is c.session_archive.archive`)."""
    calls: list[tuple] = []
    real = c.session_archive.archive

    def _wrapper(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    c.session_archive.archive = _wrapper
    return calls


# ---------------------------------------------------------------------------
# (a) Cross-writer race: _do_oss_fetch × _run_finalize_incomplete
# ---------------------------------------------------------------------------


async def test_cross_writer_oss_first_then_incomplete_archives_once():
    """_do_oss_fetch enters the latch first (blocked mid-body on the signed-URL
    executor hop); _run_finalize_incomplete fires mid-await. The latch must
    serialize: the cloud writer wins, the local writer no-ops. ONE archive
    row, and it is the CLOUD one (md5 != "(incomplete)")."""
    c = _build_coord(pending_object_name="d/sessions/xw.json")
    now = T0 + 3700
    _begin_mow_session(c)
    archive_calls = _counting_archive(c)

    oss_body_entered = asyncio.Event()
    release_oss = asyncio.Event()
    base_executor = c.hass.async_add_executor_job.side_effect

    async def _barrier_executor(fn, *args):
        if fn is c._cloud.get_interim_file_url and not oss_body_entered.is_set():
            oss_body_entered.set()
            await release_oss.wait()
        return await base_executor(fn, *args)

    c.hass.async_add_executor_job.side_effect = _barrier_executor

    task_oss = asyncio.create_task(c._do_oss_fetch(now))
    await oss_body_entered.wait()  # oss body holds the latch, blocked mid-fetch
    task_local = asyncio.create_task(c._run_finalize_incomplete(now))
    await asyncio.sleep(0)
    await asyncio.sleep(0)  # local writer snapshots start_ts, parks on the lock
    release_oss.set()
    await asyncio.gather(task_oss, task_local)

    assert len(archive_calls) == 1, (
        f"exactly ONE archive write expected across the two writers; "
        f"got {len(archive_calls)}"
    )
    sessions = c.session_archive.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].md5 == "cloud-md5-xw", (
        "the FIRST entrant (cloud writer) must win; found md5="
        f"{sessions[0].md5!r}"
    )
    assert not c.live_map.is_active()
    assert c.data.pending_session_object_name is None


async def test_cross_writer_incomplete_first_then_oss_archives_once():
    """Reverse order: _run_finalize_incomplete enters first (blocked at its
    archive write); _do_oss_fetch fires mid-await. The local writer wins,
    the cloud writer no-ops WITHOUT fetching. ONE archive row: "(incomplete)"."""
    c = _build_coord(pending_object_name="d/sessions/xw.json")
    now = T0 + 3700
    _begin_mow_session(c)
    archive_calls = _counting_archive(c)

    local_archive_started = asyncio.Event()
    release_local = asyncio.Event()
    base_executor = c.hass.async_add_executor_job.side_effect

    async def _barrier_executor(fn, *args):
        if fn is c.session_archive.archive and not local_archive_started.is_set():
            local_archive_started.set()
            await release_local.wait()
        return await base_executor(fn, *args)

    c.hass.async_add_executor_job.side_effect = _barrier_executor

    task_local = asyncio.create_task(c._run_finalize_incomplete(now))
    await local_archive_started.wait()  # local body holds the latch
    task_oss = asyncio.create_task(c._do_oss_fetch(now))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    release_local.set()
    await asyncio.gather(task_local, task_oss)

    assert len(archive_calls) == 1
    sessions = c.session_archive.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].md5 == "(incomplete)", (
        "the FIRST entrant (local writer) must win; found md5="
        f"{sessions[0].md5!r}"
    )
    c._cloud.get_interim_file_url.assert_not_called()
    assert not c.live_map.is_active()


# ---------------------------------------------------------------------------
# (b) Restore-at-boot × finalize
# ---------------------------------------------------------------------------


async def test_restore_race_finalize_completing_mid_read_is_not_resurrected():
    """A finalize that runs to completion while _restore_in_progress is
    suspended in its disk-read executor hop must NOT be resurrected: the
    stale disk payload describes a session that was just archived, so
    hydrating it back into live_map would create a zombie session that a
    later gate tick double-archives ("(incomplete)" md5 ≠ cloud md5, so
    the archive-level dedup cannot catch it)."""
    c = _build_coord(pending_object_name="d/sessions/xw.json")
    now = T0 + 3700
    _begin_mow_session(c)
    archive_calls = _counting_archive(c)

    # Persist the live session to disk — the payload restore will read.
    c.session_archive.write_in_progress(c.live_map.dump_to_payload())

    read_done = asyncio.Event()
    release_read = asyncio.Event()
    base_executor = c.hass.async_add_executor_job.side_effect
    read_fn = c.session_archive.read_in_progress

    async def _barrier_executor(fn, *args):
        if fn == read_fn and not read_done.is_set():  # == not `is`: bound methods are recreated per access
            # Model the dangerous window: the executor thread has ALREADY
            # read the file, but the coroutine has not resumed yet.
            result = fn(*args)
            read_done.set()
            await release_read.wait()
            return result
        return await base_executor(fn, *args)

    c.hass.async_add_executor_job.side_effect = _barrier_executor

    task_restore = asyncio.create_task(c._restore_in_progress())
    await read_done.wait()

    # Finalize completes while restore is parked on the read.
    await c._run_finalize_incomplete(now)
    assert len(archive_calls) == 1
    assert not c.live_map.is_active()
    assert c._finalizing_start_ts == T0

    release_read.set()
    await task_restore

    # The finalized session must NOT come back to life from the stale read.
    assert not c.live_map.is_active(), (
        "restore resurrected a session that finalize archived while the "
        "disk read was in flight (zombie session → later double-archive)"
    )
    assert c.data.session_started_unix is None


async def test_restore_race_new_session_on_memory_side_still_restores():
    """Control for the discard guard: a DIFFERENT (newer) live session that
    began during the restore read window survives restore untouched — the
    guard only discards when the merged payload IS the finalized session."""
    c = _build_coord()
    _begin_mow_session(c)
    c.session_archive.write_in_progress(c.live_map.dump_to_payload())

    read_done = asyncio.Event()
    release_read = asyncio.Event()
    base_executor = c.hass.async_add_executor_job.side_effect
    read_fn = c.session_archive.read_in_progress

    async def _barrier_executor(fn, *args):
        if fn == read_fn and not read_done.is_set():  # == not `is`: bound methods are recreated per access
            result = fn(*args)
            read_done.set()
            await release_read.wait()
            return result
        return await base_executor(fn, *args)

    c.hass.async_add_executor_job.side_effect = _barrier_executor

    task_restore = asyncio.create_task(c._restore_in_progress())
    await read_done.wait()

    # Finalize the old session, then a NEW session begins (well outside the
    # SAME_SESSION_TOLERANCE_S window) before restore resumes.
    await c._run_finalize_incomplete(T0 + 3700)
    new_start = T0 + 7200
    c.live_map.begin_session(new_start)

    release_read.set()
    await task_restore

    assert c.live_map.is_active()
    assert c.live_map.started_unix == new_start, (
        "the newer in-memory session must survive restore (merge rule: "
        "diverging start_ts → memory wins)"
    )


# ---------------------------------------------------------------------------
# (c) Rain veto during route-arm
# ---------------------------------------------------------------------------


async def test_rain_active_at_tick_time_vetoes_dispatch():
    """Control case: rain_delay_active at DECISION time → decide() returns
    NOOP for the session-end edge → _periodic_session_retry dispatches
    nothing. (Veto sites: live_map/finalize.py::decide priority-1 branch and
    _finalize_non_mow_immediate's entry guard — both entry-time checks.)"""
    c = _build_coord()
    _begin_mow_session(c)
    c._prev_task_state = 0  # was running
    c.data = MowerState(task_state_code=None, area_mowed_m2=120.5)  # now idle
    c._rain_delay_started_at = T0 + 3600  # resume_hours None → active until undock
    dispatched = []

    async def _spy_dispatch(action, now_unix):
        dispatched.append(action)

    c._dispatch_finalize_action = _spy_dispatch

    await c._periodic_session_retry()

    assert dispatched == [], "rain-active tick must not dispatch a finalize"
    assert c.live_map.is_active()


async def test_rain_edge_after_route_arm_does_not_abort_finalize():
    """PINS CURRENT BEHAVIOUR (deliberate, documented limitation): the rain
    veto is checked at decision/entry time ONLY. Once the dispatch has been
    armed (dock-wait in flight), a rain edge (_rain_delay_started_at set by
    _mqtt_handlers._fire_rain_delay_started_if_edge) does NOT abort the
    in-flight cloud finalize: the dock signal completes the wait and
    _do_oss_fetch archives the session. There is no post-wait rain re-check
    in _route_finalize — changing that would reorder finalize semantics."""
    c = _build_coord(pending_object_name="d/sessions/xw.json")
    now = T0 + 3700
    _begin_mow_session(c)
    archive_calls = _counting_archive(c)

    task = asyncio.create_task(
        c._dispatch_finalize_action(FinalizeAction.AWAIT_OSS_FETCH, now)
    )
    # Let the dispatch route into the dock-wait.
    for _ in range(4):
        await asyncio.sleep(0)
    assert c._pending_finalize_done is not None, "dock-wait must be armed"

    # Rain edge lands MID-WAIT.
    c._rain_delay_started_at = now
    assert c.rain_delay_active is True

    # Mower docks (charging push) — _on_state_update would fire this signal.
    c._pending_finalize_done_reason = "charging"
    c._pending_finalize_done.set()
    await asyncio.wait_for(task, timeout=5)

    # Current behaviour: the armed finalize proceeds despite the rain edge.
    assert len(archive_calls) == 1
    assert c.session_archive.list_sessions()[0].md5 == "cloud-md5-xw"
    assert not c.live_map.is_active()


# ---------------------------------------------------------------------------
# (d) Dock-wait single-flight (T3-6 fix contract)
# ---------------------------------------------------------------------------


async def test_dock_wait_single_flight_one_waiter_one_attempt():
    """T3-6: the 60 s retry tick fires independently of the previous run, so
    N dispatches can enter the ≤10-min dock-wait concurrently. Single-flight
    contract: ONE waiter Event is created, the attempt is stamped BEFORE the
    wait (so decide()'s 2c retry branch is suppressed during the wait
    window), the later entries abort without clobbering the Event, and the
    dock signal produces exactly ONE archive write."""
    c = _build_coord(cls=_EventSpyCoord, pending_object_name="d/sessions/xw.json")
    now = T0 + 3700
    _begin_mow_session(c)
    archive_calls = _counting_archive(c)

    # Three retry ticks enter the dispatch while none has completed.
    tasks = [
        asyncio.create_task(
            c._dispatch_finalize_action(FinalizeAction.AWAIT_OSS_FETCH, now + i)
        )
        for i in range(3)
    ]
    for _ in range(6):
        await asyncio.sleep(0)

    created = c.__dict__.get("_pfd_created", [])
    assert len(created) == 1, (
        f"exactly ONE dock-wait waiter must be armed across the 3 concurrent "
        f"ticks; {len(created)} Event(s) were created (waiter stacking — T3-6)"
    )
    # The attempt stamp lands BEFORE the wait, so re-entry is suppressed even
    # while the winner is still waiting.
    assert c.data.pending_session_last_attempt_unix == now, (
        "pending_session_last_attempt_unix must be stamped BEFORE the dock "
        "wait (T3-6), not only after it completes"
    )

    # Mower docks: the single charging signal must complete ALL entries.
    c._pending_finalize_done_reason = "charging"
    c._pending_finalize_done.set()
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)

    assert len(archive_calls) == 1
    assert c.session_archive.list_sessions()[0].md5 == "cloud-md5-xw"
    assert not c.live_map.is_active()
    # Event lifecycle: the slot is cleared by the (single) waiter's finally.
    assert c._pending_finalize_done is None
    # Exactly one OSS attempt was made.
    max_attempts = max(
        (s.pending_session_attempt_count or 0) for s in c._published_states
    )
    assert max_attempts == 1, (
        f"one dock signal must produce one OSS attempt; saw attempt_count "
        f"reach {max_attempts}"
    )


async def test_dock_wait_single_flight_finalize_incomplete_arm():
    """The FINALIZE_INCOMPLETE dispatch arm (max-age / max-attempts give-up
    for a cloud-finalized session) has its own dock-wait call site and fires
    EVERY tick once max-age is exceeded — it must be single-flight too."""
    c = _build_coord(cls=_EventSpyCoord, pending_object_name="d/sessions/xw.json")
    now = T0 + 3700
    _begin_mow_session(c)
    archive_calls = _counting_archive(c)

    tasks = [
        asyncio.create_task(
            c._dispatch_finalize_action(FinalizeAction.FINALIZE_INCOMPLETE, now + i)
        )
        for i in range(2)
    ]
    for _ in range(6):
        await asyncio.sleep(0)

    created = c.__dict__.get("_pfd_created", [])
    assert len(created) == 1, (
        f"exactly ONE dock-wait waiter must be armed; {len(created)} created"
    )

    c._pending_finalize_done_reason = "charging"
    c._pending_finalize_done.set()
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)

    assert len(archive_calls) == 1
    assert c.session_archive.list_sessions()[0].md5 == "(incomplete)"
    assert not c.live_map.is_active()
    assert c._pending_finalize_done is None


async def test_wait_for_dock_return_reentry_returns_already_waiting():
    """Primitive-level contract: a second _wait_for_dock_return while a
    waiter is armed returns 'already-waiting' immediately and must NOT
    clobber the first waiter's Event — the first waiter still resolves on
    the signal and clears the slot in its finally."""
    c = _build_coord()

    first = asyncio.create_task(c._wait_for_dock_return(timeout_s=5))
    await asyncio.sleep(0)
    armed_event = c._pending_finalize_done
    assert armed_event is not None

    second = await asyncio.wait_for(c._wait_for_dock_return(timeout_s=5), timeout=1)
    assert second == "already-waiting"
    assert c._pending_finalize_done is armed_event, (
        "re-entry must not replace the armed waiter's Event"
    )

    c._pending_finalize_done_reason = "charging"
    armed_event.set()
    assert await asyncio.wait_for(first, timeout=5) == "charging"
    assert c._pending_finalize_done is None
