"""Session finalize service (layer 4) — extracted VERBATIM from
``coordinator/_session.py`` + ``coordinator/_lidar_oss.py`` §1 in refactor-v2
P3.9a (autopsy #4 / #10 §1).

This module owns the most corpus-validated, behaviourally-subtle code in the
repo: the session finalize state machine. Its ordering, the single finalize
latch (``finalize_with_latch`` + the ``_finalize_lock`` / ``_finalizing_start_ts``
completion sentinel), the ≤10-min dock-return wait (``wait_for_dock_return``
with the P2.7 single-flight guard + the P2.8 ``_pending_finalize_task``
cancellation), the cloud-vs-local routing (``route_finalize`` /
``dispatch_finalize_action``), and the OSS-summary assembly
(``inject_live_map_into_raw_dict`` / ``finalize_classify_raw_dict`` /
``do_oss_fetch_body``) are ALL moved byte-for-byte — pinned by
``tests/coordinator/test_finalize_interleavings.py`` /
``test_finalize_latch.py`` + ``tests/integration/test_pending_finalize.py``.

Each function takes the coordinator (``coord``) as its first argument instead of
``self`` so the behaviour is identical while the code lives at the domain layer.
The finalize latch/dock-wait state (``_finalize_lock``, ``_finalizing_start_ts``,
``_pending_finalize_done``, ``_pending_finalize_task``, …) still lives on
``_CoreMixin.__init__`` (T2-16: attrs move with the full thin-coordinator collapse
in 9e); these functions read/write it on ``coord``. The coordinator keeps thin
delegating methods (``_SessionMixin`` / ``_LidarOssMixin``) for its public + test
surface — every ``self.<method>`` call below stays a ``coord.<method>`` call so
that test monkeypatches (which patch the coord method) are preserved exactly.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import types as _types
from collections.abc import Awaitable, Callable
from typing import Any

from ...const import (
    LOG_NOVEL_KEY_SESSION_SUMMARY,
    LOGGER,
)
from ...live_map.finalize import FinalizeAction
from ...live_map.finalize import decide as _finalize_decide
from ...archive.session import ArchivedSession
from ...protocol import session_summary as _session_summary
from ...state.apply import _SESSION_SUMMARY_CHECK


def finalize_classify_raw_dict(raw_dict: dict, cloud_segments) -> None:
    """Smooth raw_dict['track'] roles and store cloud_track verbatim.

    cloud_segments: parsed SessionSummary.track_segments (iterable of legs of
    (x,y)). Stored verbatim under 'cloud_track' for reference. NOTE: the cloud
    track is NOT used to reclassify roles — area-delta (set at capture) is
    authoritative; classify_track only smooths isolated stutters. See
    live_map/classify.py for why cloud-coverage rescue was dropped.
    """
    from ...live_map.classify import classify_track

    cloud = [[[float(p[0]), float(p[1])] for p in seg] for seg in (cloud_segments or [])]
    raw_dict["cloud_track"] = cloud
    track_rows = raw_dict.get("track") or []
    points = [
        {"t": r[0], "x_m": r[1], "y_m": r[2], "area_m2": r[3],
         "heading_deg": r[4], "task_state": r[5], "role": r[6]}
        for r in track_rows
    ]
    classify_track(points)
    raw_dict["track"] = [
        [p["t"], p["x_m"], p["y_m"], p["area_m2"], p["heading_deg"],
         p["task_state"], p["role"]]
        for p in points
    ]


def inject_live_map_into_raw_dict(coord, raw_dict: dict[str, Any]) -> None:
    """Add LiveMapState-tracked fields to a cloud-OSS raw_dict before archive.

    Mutates raw_dict in place. Called from do_oss_fetch and from the
    FINALIZE_INCOMPLETE path. Skips fields whose source is empty so
    older cloud blobs aren't polluted with empty arrays.
    """
    if coord.live_map.track:
        raw_dict["track"] = [
            [p.t, p.x_m, p.y_m, p.area_m2, p.heading_deg, p.task_state, p.role]
            for p in coord.live_map.track
        ]
    if coord.live_map.wifi_samples:
        raw_dict["wifi_samples"] = [
            [float(x), float(y), int(r), int(t)]
            for (x, y, r, t) in coord.live_map.wifi_samples
        ]
    if coord.live_map.battery_samples:
        raw_dict["battery_samples"] = [
            [int(t), int(v)] for (t, v) in coord.live_map.battery_samples
        ]
    if coord.live_map.charging_status_samples:
        raw_dict["charging_status_samples"] = [
            [int(t), int(v)] for (t, v) in coord.live_map.charging_status_samples
        ]
    if coord.live_map.state_samples:
        raw_dict["state_samples"] = [
            [int(t), int(v)] for (t, v) in coord.live_map.state_samples
        ]
    if coord.live_map.error_samples:
        raw_dict["error_samples"] = [
            [int(t), int(v)] for (t, v) in coord.live_map.error_samples
        ]
    if coord.live_map.charge_at_start is not None:
        raw_dict["charge_at_start"] = int(coord.live_map.charge_at_start)
    if coord.live_map.settings_snapshot is not None:
        raw_dict["settings_snapshot"] = dict(coord.live_map.settings_snapshot)
    from ...live_map.classify import classify_session_type
    lm = coord.live_map
    codes = [code for _, code in (lm.error_samples or [])]
    saw_mow_start = any(c in (50, 53) for c in codes)
    saw_patrol_start = (51 in codes) or lm.saw_patrol_start
    end_codes = [c for c in codes if c in (75, 76)]
    last_point_end_code = end_codes[-1] if end_codes else None
    session_type, outcome = classify_session_type(
        last_task_op=lm.last_task_op,
        saw_mow_start=saw_mow_start,
        area_ever_positive=lm.area_ever_positive,
        last_point_end_code=last_point_end_code,
        saw_patrol_start=saw_patrol_start,
    )
    raw_dict["session_type"] = session_type
    if outcome is not None:
        raw_dict["outcome"] = outcome
    if lm.target_ids:
        raw_dict["target_ids"] = list(lm.target_ids)


def resolve_finalize_map_id(coord) -> int:
    """Map id to stamp on a session being finalized.

    Active-map at finalize time is the canonical answer; if no
    active map yet (rare — MAPL not yet polled), fall back to the
    lowest-id cached map; if no maps cached at all, sentinel -1.
    """
    if coord._active_map_id is not None:
        return int(coord._active_map_id)
    if coord.cloud_state.maps_by_id:
        return min(coord.cloud_state.maps_by_id.keys())
    return -1


async def periodic_session_retry(coord) -> None:
    """Periodic tick (every RETRY_INTERVAL_SECONDS) for session finalization.

    Calls ``finalize.decide(state, prev_task_state, now_unix)`` and
    dispatches the returned action.  All cloud I/O and disk I/O go through
    the executor per spec §3.
    """
    import time as _time
    now_unix = int(_time.time())
    action = _finalize_decide(
        coord.data,
        coord._prev_task_state,
        now_unix,
        rain_delay_active=coord.rain_delay_active,
    )
    # Boot-stale guard: filter out the gate's false-positive when
    # we just restarted into an MQTT-quiet window mid-session.
    # `_restore_in_progress` seeds `_prev_task_state=0` to support
    # auto-finalize when the mower finished a mow while HA was off
    # — but combined with MowerState.task_state_code's default None
    # (no s2p56 push has landed yet), the gate would otherwise hit
    # FINALIZE_INCOMPLETE on the first retry tick after boot. Skip
    # the dispatch ONLY when the action came from the
    # session_just_ended branch (i.e. no pending OSS object name)
    # AND we haven't observed any real task_state push yet. The
    # max-age / max-attempts FINALIZE_INCOMPLETE path through a
    # known pending OSS key is unaffected.
    # See 2026-05-15 rain-stop incident: HA restarted in a 22-min
    # MQTT-quiet window while the mower was paused-charging; the
    # gate created a phantom (incomplete) session at 0 m² / 337 min.
    if (
        action == FinalizeAction.FINALIZE_INCOMPLETE
        and coord.data.task_state_code is None
        and not coord._real_task_state_observed
        and not coord.data.pending_session_object_name
    ):
        LOGGER.debug(
            "[F5.6.1] _periodic_session_retry: skipping FINALIZE_INCOMPLETE "
            "from boot-stale state (task_state_code still default None, no "
            "fresh MQTT push observed yet, no pending OSS event). "
            "prev_task_state=%r, _real_task_state_observed=%s",
            coord._prev_task_state, coord._real_task_state_observed,
        )
        return
    if action == FinalizeAction.NOOP:
        return
    # v1.0.0a48: bumped to WARNING so the trail shows up in the
    # default HA log. Only fires on non-NOOP actions, which means
    # at most a handful per mow.
    LOGGER.debug(
        "[F5.6.1] _periodic_session_retry: action=%s "
        "task_state=%r prev=%r pending_oss=%r",
        action.name,
        coord.data.task_state_code,
        coord._prev_task_state,
        coord.data.pending_session_object_name,
    )
    await coord._dispatch_finalize_action(action, now_unix)


async def wait_for_dock_return(
    coord,
    *,
    timeout_s: int = 300,
) -> str:
    """Block until the mower has docked or ``timeout_s`` has elapsed.

    Returns one of:
      'charging'        — charging_status flipped to ChargingStatus.CHARGING (1)
      'timeout'         — the dock signal did not fire in time
      'already-waiting' — a waiter is already armed (T3-6 single-flight);
                          the caller must ABORT its dispatch — the
                          in-flight waiter's dispatch completes the
                          finalize.

    The caller logs the reason so the timeout can be tuned later.
    Trail collection continues during the wait because MQTT events keep
    flowing into LiveMapState while we await here.

    Signals are delivered by _on_state_update in _mqtt_handlers.py:
    it checks _pending_finalize_done after each state mutation.

    The finally block clears _pending_finalize_done to None so subsequent
    MQTT pushes don't accidentally set a stale event from a future mow.

    Single-flight (T3-6): the 60 s retry tick does not await the previous
    run, so during the ≤10-min wait each tick used to re-enter here,
    overwrite the single _pending_finalize_done Event (orphaning the
    elder waiters into full-timeout sleeps) and open windows where a
    waiter's finally nulled the slot out from under the newest waiter,
    losing the dock signal entirely. The guard below refuses to stack:
    only the first entry arms an Event; callers guard/abort on the
    'already-waiting' reason (this check is the defense-in-depth layer;
    both call sites also check the slot before entering).

    T3-8: the actual wait runs inside a Task held on
    _pending_finalize_task so async_unload_entry can cancel an in-flight
    ≤10-min wait before tearing down transports. Cancelling that task
    raises CancelledError out of the ``asyncio.wait_for`` below, which is
    NOT caught here — it propagates straight through this method (skipping
    the post-wait finalize dispatch entirely) up to the caller's own task,
    a clean cooperative abort. The ``finally`` still clears both slots so a
    subsequent restart/reload starts from a clean state.
    """
    if coord._pending_finalize_done is not None:
        return "already-waiting"
    coord._pending_finalize_done = asyncio.Event()
    coord._pending_finalize_done_reason = None
    wait_task = coord.hass.async_create_task(coord._pending_finalize_done.wait())
    coord._pending_finalize_task = wait_task
    try:
        await asyncio.wait_for(wait_task, timeout=timeout_s)
        return coord._pending_finalize_done_reason or "early"
    except asyncio.TimeoutError:
        return "timeout"
    finally:
        coord._pending_finalize_done = None
        if coord._pending_finalize_task is wait_task:
            coord._pending_finalize_task = None


async def finalize_prior_for_new_command(coord, now_unix: int) -> None:
    """(c) Finalize the still-active prior session at a new-command boundary.

    Invoked when a DISTINCT new task command begins while the previous
    session is still active (e.g. the user abandoned a manual run on the
    lawn and started a mow from there with no dock between). Unlike the
    normal end-of-session finalize, there is NO dock wait here: the mower
    did not dock — a new command superseded the prior run — so we finalize
    immediately with whatever the prior live_map captured.

    Routes by the prior session's provisional type: a mow finalizes via
    the cloud-summary path if its OSS key already arrived (else locally);
    a non-mow finalizes locally. After this returns the live_map session
    has been ended, so the caller's begin_session starts a clean session.
    """
    if not coord.live_map.is_active():
        return
    # Same cloud-vs-local routing as the gate path, but with NO dock-wait:
    # the mower did not dock, a new command superseded the prior run.
    await coord._route_finalize(
        now_unix, dock_wait=False, trigger="new-command-boundary",
    )


async def finalize_non_mow_immediate(coord, now_unix: int, trigger: str) -> None:
    """Finalize a non-mow (non-cloud-finalized) session immediately on arrival.

    Called from two new trigger paths (Option A fix):
      1. s2p2=75 (arrived_at_maintenance_point) — primary, to-point-specific
         arrival signal emitted at ~t+40s for op=109 runs.
      2. task_state edge 0/4→2/None inside _on_state_update — robustness bonus,
         catches the edge visible BEFORE _prev_task_state is advanced.

    In both cases the session is non-cloud-finalized (no OSS summary expected),
    so there is NO dock-wait: we finalize at the arrival point and the return
    drive is not captured. This keeps the session representation clean.

    Hard guards (checked synchronously before the first await):
      - live_map must be active (no double-finalize).
      - session must be non-cloud-finalized (mow/patrol path NEVER uses this).
      - rain_delay_active must be False (pause-at-dock for rain is not a
        session end).

    The s2p2=75-vs-task_state-edge double-fire race (both can pass the
    is_active() guard before either reaches end_session()) is now closed by
    the single finalize latch inside _run_finalize_incomplete
    (_finalize_with_latch), which de-dupes concurrent finalizes of the same
    session — no per-method bool latch needed.
    """
    if not coord.live_map.is_active():
        LOGGER.debug(
            "[F5.6.1] _finalize_non_mow_immediate(trigger=%s): live_map not active — skip",
            trigger,
        )
        return
    if coord._provisional_session_is_cloud_finalized():
        LOGGER.debug(
            "[F5.6.1] _finalize_non_mow_immediate(trigger=%s): session is cloud-finalized "
            "(mow/patrol) — refusing to finalize non-mow path; this is a bug if called "
            "for a real mow",
            trigger,
        )
        return
    if coord.rain_delay_active:
        # Rain pause-at-dock veto (mirrors the finalize-gate veto in
        # live_map/finalize.decide). The 0/4→2/None task_state edge that
        # triggers this path also fires when the mower docks to wait out a
        # rain delay — that is NOT a session end. rain_delay_active is
        # bounded for resume_hours>=1 (the resume window expires); for
        # resume_hours in {0, None} it stays active until the mower undocks
        # (which clears _rain_delay_started_at) — in practice the mower
        # must undock to resume, so the session still resolves.
        LOGGER.debug(
            "[F5.6.1] _finalize_non_mow_immediate(trigger=%s): rain delay active "
            "— vetoing finalize (mower paused at dock for rain, session not ended)",
            trigger,
        )
        return
    LOGGER.debug(
        "[F5.6.1] _finalize_non_mow_immediate: trigger=%s — finalizing non-mow session "
        "immediately (no dock-wait); live_map.total_points=%d",
        trigger,
        coord.live_map.total_points(),
    )
    # The double-fire race is closed by the finalize latch inside
    # _run_finalize_incomplete (_finalize_with_latch) — a concurrent second
    # trigger for the same session no-ops there.
    await coord._run_finalize_incomplete(now_unix)


def provisional_session_type(coord) -> str:
    """Provisional finalize-time session type, computed from the SAME
    inputs `_inject_live_map_into_raw_dict` uses so the routing decision
    and the archived `session_type` agree. `last_point_end_code` is
    irrelevant to routing so we pass None.
    """
    from ...live_map.classify import classify_session_type

    lm = coord.live_map
    codes = [code for _, code in (lm.error_samples or [])]
    saw_mow_start = any(c in (50, 53) for c in codes)
    saw_patrol_start = (51 in codes) or lm.saw_patrol_start
    session_type, _ = classify_session_type(
        last_task_op=lm.last_task_op,
        saw_mow_start=saw_mow_start,
        area_ever_positive=lm.area_ever_positive,
        last_point_end_code=None,
        saw_patrol_start=saw_patrol_start,
    )
    return session_type


def provisional_session_is_mow(coord) -> bool:
    """True iff the live_map provisionally classifies as a MOW (not patrol
    / maintenance_run / manual_drive). Kept for callers that need the
    strict mow distinction."""
    return provisional_session_type(coord) == "mow"


def provisional_session_is_cloud_finalized(coord) -> bool:
    """True iff the live_map produces a cloud OSS summary we should wait
    for (mow OR patrol). This is the finalize-ROUTING signal: cloud-finalized
    types fetch the summary; the rest finalize locally. Patrol is the reason
    this is distinct from `_provisional_session_is_mow` — it's not a mow but
    it IS cloud-finalized (verified 2026-05-30: mode=108 archive has an md5).
    """
    from ...live_map.classify import CLOUD_FINALIZED_SESSION_TYPES

    return provisional_session_type(coord) in CLOUD_FINALIZED_SESSION_TYPES


async def route_finalize(
    coord, now_unix: int, *, dock_wait: bool, trigger: str
) -> None:
    """Single cloud-vs-local finalize routing decision.

    - Cloud-finalized (mow/patrol) AND an OSS object key is present:
      optionally wait for the dock-return drive to finish capturing
      (``dock_wait``), then fetch + archive the cloud summary via
      ``_do_oss_fetch``.
    - Otherwise (non-cloud-finalized, or cloud-finalized with no OSS key):
      finalize locally with whatever live_map has — never dock-waits.

    ``trigger`` only labels the log lines so the entry point that routed
    here stays visible in the log. The routing predicate is byte-equivalent
    to the inlined callers it replaces.
    """
    if (
        coord._provisional_session_is_cloud_finalized()
        and coord.data.pending_session_object_name
    ):
        if dock_wait:
            if coord._pending_finalize_done is not None:
                # T3-6 single-flight: a dock-wait is already in flight
                # from an earlier retry tick. Entering again would stack
                # a second waiter on the single Event slot; abort this
                # dispatch — the in-flight waiter completes the finalize.
                LOGGER.debug(
                    "[F5.6.1] _route_finalize(%s): dock-wait already in "
                    "flight — skipping duplicate finalize dispatch",
                    trigger,
                )
                return
            LOGGER.info(
                "[F5.6.1] session-done received (%s) — "
                "entering pending-finalize wait (≤10 min)",
                trigger,
            )
            # T3-6: stamp the attempt BEFORE the wait so decide()'s
            # retry branch (2c) stops returning AWAIT_OSS_FETCH every
            # tick during the wait window. The post-fetch stamp in
            # _do_oss_fetch_body still lands as before; only decide()
            # consumes this field.
            coord.async_set_updated_data(
                dataclasses.replace(
                    coord.data,
                    pending_session_last_attempt_unix=now_unix,
                )
            )
            reason = await coord._wait_for_dock_return(timeout_s=600)
            LOGGER.info("[F5.6.1] pending-finalize wait ended: reason=%s", reason)
            if reason == "already-waiting":
                # Defense-in-depth (guard above races nothing in
                # single-threaded asyncio, but the primitive refuses to
                # stack regardless) — never proceed past a wait we did
                # not own.
                return
        await coord._do_oss_fetch(now_unix)
        return
    LOGGER.info(
        "[F5.6.1] session-done (%s) but provisional type is "
        "NON-CLOUD-FINALIZED (or no OSS key) — finalizing locally "
        "immediately (no dock-wait)",
        trigger,
    )
    await coord._run_finalize_incomplete(now_unix)


async def dispatch_finalize_action(
    coord, action: FinalizeAction, now_unix: int
) -> None:
    """Dispatch a FinalizeAction from the finalize gate.

    BEGIN_SESSION / BEGIN_LEG: already handled by _on_state_update on every
        property push; nothing to do in the retry path.
    AWAIT_OSS_FETCH / FINALIZE_COMPLETE: fetch the cloud-summary JSON,
        parse it, archive it, and update MowerState.
    FINALIZE_INCOMPLETE: archive whatever live_map has with an "(incomplete)"
        suffix in the md5 field, then clear pending state.
    NOOP: do nothing.

    All blocking I/O runs in the executor per spec §3.

    For AWAIT_OSS_FETCH / FINALIZE_COMPLETE: if the session is cloud-finalized
    (mow/patrol), enters a pending-finalize wait (up to 10 min) so trail
    collection captures the dock-return drive BEFORE the archive write —
    see _wait_for_dock_return. Non-cloud-finalized sessions (maintenance/manual)
    finalize immediately with no dock-wait.
    For FINALIZE_INCOMPLETE: same split — dock-wait only for cloud-finalized
    sessions; non-cloud-finalized sessions (rare MQTT-drop fallback) finalize
    immediately.
    """
    if action in (FinalizeAction.BEGIN_SESSION, FinalizeAction.BEGIN_LEG, FinalizeAction.NOOP):
        return

    if action in (FinalizeAction.AWAIT_OSS_FETCH, FinalizeAction.FINALIZE_COMPLETE):
        # (a) Route through the shared decision helper. The cloud OSS summary
        # only arrives for a mow OR a patrol; a maintenance run / manual
        # drive produces no summary, so awaiting one would hang the finalize
        # (live_map stays active and the NEXT run merges into it). For these
        # two actions the finalize gate only returns them when an OSS object
        # key is present (decide(): AWAIT_OSS_FETCH/FINALIZE_COMPLETE both
        # require pending_session_object_name), so the routing predicate
        # `cloud-finalized AND object_name` reduces to the old
        # `cloud-finalized` check — byte-equivalent. Cloud-finalized →
        # dock-wait then OSS fetch; otherwise finalize locally immediately.
        await coord._route_finalize(
            now_unix, dock_wait=True, trigger=f"action={action.name}",
        )
        return

    if action == FinalizeAction.FINALIZE_INCOMPLETE:
        # NOT routed through _route_finalize: both arms here finalize
        # locally (_run_finalize_incomplete) regardless of cloud-finalized
        # type — only the dock-wait differs — so _route_finalize's
        # cloud→_do_oss_fetch predicate doesn't apply.
        # (b) Non-cloud-finalized sessions (maintenance/manual runs) never
        # produce an OSS summary and don't have a return-drive to capture, so
        # skip the dock-wait exactly as the AWAIT_OSS_FETCH branch above does.
        # This path is a rare MQTT-drop fallback; the guard must NOT change
        # mow behaviour — only the non-cloud-finalized arm skips the wait.
        if not coord._provisional_session_is_cloud_finalized():
            LOGGER.info(
                "[F5.6.1] session-done (action=FINALIZE_INCOMPLETE) but provisional type is "
                "NON-CLOUD-FINALIZED — finalizing locally immediately (no dock-wait)",
            )
            await coord._run_finalize_incomplete(now_unix)
            return
        if coord._pending_finalize_done is not None:
            # T3-6 single-flight: this arm fires EVERY tick once
            # max-age/max-attempts is exceeded — same stacking hazard as
            # the AWAIT_OSS_FETCH arm. Abort; the in-flight waiter's
            # dispatch completes the finalize.
            LOGGER.debug(
                "[F5.6.1] FINALIZE_INCOMPLETE: dock-wait already in "
                "flight — skipping duplicate finalize dispatch"
            )
            return
        LOGGER.info(
            "[F5.6.1] session-done received (action=FINALIZE_INCOMPLETE) — "
            "entering pending-finalize wait (≤10 min)"
        )
        reason = await coord._wait_for_dock_return(timeout_s=600)
        LOGGER.info("[F5.6.1] pending-finalize wait ended: reason=%s", reason)
        if reason == "already-waiting":
            # Defense-in-depth — never proceed past a wait we did not own.
            return
        await coord._run_finalize_incomplete(now_unix)
        return

    LOGGER.warning("[F5.6.1] _dispatch_finalize_action: unhandled action=%s", action)


async def finalize_with_latch(
    coord, body: Callable[[], Awaitable[None]], *, label: str
) -> None:
    """Serialize + de-dupe a terminal archive write (P3e.4).

    Both terminal writers (_do_oss_fetch, _run_finalize_incomplete) run
    their body through here. The latch:
      1. captures the live session's start_ts SYNCHRONOUSLY (before any
         await) so a concurrent second entry snapshots the same key while
         the session is still active;
      2. acquires _finalize_lock (serializes all finalize entries);
      3. no-ops if that start_ts was already FINALIZED to completion
         (== _finalizing_start_ts, which _post_archive_reset stamps on a
         successful archive+end_session) — the concurrent-double-fire case;
      4. otherwise runs ``body`` and releases in a finally.

    Crucially _finalizing_start_ts is set on COMPLETION, not at entry, so a
    legitimate SEQUENTIAL retry of a still-pending OSS fetch (the
    AWAIT_OSS_FETCH retry loop, which early-returns without completing while
    the cloud summary is not yet available) is NOT de-duped — only a second
    entry that races a finalize that actually completed is.

    The disk-fallback manual case (no live session → started_unix is None)
    is never de-duped here (no key to match); the archive-level
    (md5, start_ts) dedup remains the backstop for it. ``label`` only tags
    the no-op debug log.
    """
    # Capture BEFORE the first await: both concurrent entries snapshot the
    # same start_ts while the session is still active, before either body
    # runs end_session().
    intended_start = coord.live_map.started_unix
    async with coord._finalize_lock:
        if (
            intended_start is not None
            and intended_start == coord._finalizing_start_ts
        ):
            LOGGER.debug(
                "[F5.6.1] _finalize_with_latch(%s): session start_ts=%s "
                "already finalized — no-op (concurrent trigger)",
                label, intended_start,
            )
            return
        await body()


async def merge_recorder_into_payload(
    coord, payload: dict[str, Any], *, label: str
) -> None:
    """Recorder-merge safety net (2026-05-16 spec) — shared by both
    terminal archive writers (_do_oss_fetch and _run_finalize_incomplete).

    Fills gaps in the battery/wifi/state/charging/error sample arrays from
    HA's recorder history for the session's ``[start, end]`` window.
    Idempotent; any failure leaves the in_progress samples untouched.

    ``label`` only varies the INFO log line so the two callers stay
    distinguishable in the log; behaviour is otherwise identical.
    """
    try:
        from ...coordinator._recorder_merge import merge_recorder_samples

        _start_ts = int(payload.get("start") or 0)
        _end_ts = int(payload.get("end") or 0)
        if _start_ts > 0 and _end_ts > _start_ts:
            _counts = await merge_recorder_samples(
                coord.hass, payload, _start_ts, _end_ts,
            )
            LOGGER.info(
                "[recorder_merge] %s: "
                "battery=%d, wifi=%d, state=%d, charging=%d, error=%d "
                "samples merged from recorder for session [%d, %d]",
                label,
                _counts["battery_recorder_count"],
                _counts["wifi_recorder_count"],
                _counts["state_recorder_count"],
                _counts["charging_recorder_count"],
                _counts["error_recorder_count"],
                _start_ts, _end_ts,
            )
    except Exception:
        LOGGER.exception(
            "[recorder_merge] %s: merge failed; "
            "using in_progress samples only",
            label,
        )


async def post_archive_reset(
    coord,
    *,
    now_unix: int,
    area_mowed_m2: float | None,
    duration_min: int | None,
    completed: bool,
    extra_updates: dict | None = None,
    delete_log_tag: str = "_do_finalize_incomplete",
) -> None:
    """Shared post-archive teardown for both terminal writers.

    Runs the sequence both writers run after a successful archive:
      1. delete_in_progress (executor, try/except-logged) — removes the
         synthesized in-progress entry so the picker doesn't show a phantom
         "in progress" row alongside the archived entry.
      2. _clear_pending_op() — drop the pending op latches + sidecar.
      3. _fire_mowing_ended(...) — emit the lifecycle event.
      4. live_map.end_session().
      5. async_set_updated_data(replace(... pending_* cleared, count, ...)).

    ``archived_session_count`` is read AFTER delete_in_progress (the archive
    write has already happened in the caller), matching prior behaviour.

    ``extra_updates`` carries the cloud path's extra MowerState fields
    (latest_session_*, total_lawn_area_m2); the caller computes them and
    passes the dict. The local path passes None.

    ``delete_log_tag`` only varies the delete_in_progress warning prefix so
    the two callers stay distinguishable in the log.
    """
    # Without this, the synthesized in-progress entry keeps
    # reappearing in the picker after every finalize, leaving the
    # archived entry _and_ a phantom "in progress" row side-by-side.
    try:
        await coord.hass.async_add_executor_job(
            coord.session_archive.delete_in_progress
        )
    except Exception as ex:
        LOGGER.warning(
            "[F5.6.1] %s: delete_in_progress raised: %s", delete_log_tag, ex
        )

    coord._clear_pending_op()

    coord._fire_mowing_ended(
        now_unix=now_unix,
        area_mowed_m2=area_mowed_m2,
        duration_min=duration_min,
        completed=completed,
    )
    # Stamp the finalize latch's completion key (P3e.4) BEFORE end_session()
    # clears started_unix. A concurrent second finalize of this same session
    # — which snapshotted the same start_ts before either body ran — then
    # no-ops at the latch's pre-check instead of double-archiving.
    if coord.live_map.started_unix is not None:
        coord._finalizing_start_ts = coord.live_map.started_unix
    coord.live_map.end_session()
    new_count = coord.session_archive.count
    coord.async_set_updated_data(
        dataclasses.replace(
            coord.data,
            pending_session_object_name=None,
            pending_session_first_event_unix=None,
            pending_session_last_attempt_unix=None,
            pending_session_attempt_count=None,
            archived_session_count=new_count,
            session_started_unix=None,
            session_track_segments=(),
            **(extra_updates or {}),
        )
    )


async def run_finalize_incomplete(coord, now_unix: int) -> None:
    """Archive whatever the live_map has as an "(incomplete)" session.

    Builds a minimal ArchivedSession directly from LiveMapState (no cloud
    summary), archives it, then clears pending state and ends the session.

    The archived entry has md5="(incomplete)" so callers can distinguish it
    from a cloud-fetched session.

    Called from several paths:
      - ``_dispatch_finalize_action(FinalizeAction.FINALIZE_INCOMPLETE)``
        (periodic retry gate, F5.6.1)
      - ``_route_finalize`` local arm (gate + new-command boundary)
      - ``_finalize_non_mow_immediate`` (s2p2=75 / task_state edge)
      - ``dispatch_action(MowerAction.FINALIZE_SESSION, ...)``
        (manual escape hatch, F5.10.1)

    The actual work runs inside _finalize_with_latch so concurrent entries
    for the same session de-dupe (single finalize latch, P3e.4).
    """
    await coord._finalize_with_latch(
        lambda: coord._do_run_finalize_incomplete(now_unix),
        label="FINALIZE_INCOMPLETE",
    )


async def do_run_finalize_incomplete(coord, now_unix: int) -> None:
    """Body of _run_finalize_incomplete — see that method. Always invoked
    through _finalize_with_latch (never call directly)."""
    LOGGER.info(
        "[F5.6.1] _do_finalize_incomplete: giving up on cloud summary; "
        "archiving incomplete session (started_unix=%s, points=%d)",
        coord.live_map.started_unix,
        coord.live_map.total_points(),
    )

    # Build a minimal ArchivedSession from whatever we have.
    # v1.0.0a24: if live_map is empty (session already ended but
    # in_progress.json wasn't promoted because the cloud summary
    # never arrived), fall back to the on-disk in_progress.json.
    # Without this, pressing the "Finalize stuck session" button
    # after a session ended would either silently no-op or write
    # a 0-area / 0-duration bogus entry.
    if coord.live_map.is_active() or coord.live_map.track:
        start_ts = coord.live_map.started_unix or now_unix
        end_ts = now_unix
        area = coord.data.area_mowed_m2 or 0.0
    else:
        # Try the disk fallback.
        try:
            disk_data = await coord.hass.async_add_executor_job(
                coord.session_archive.read_in_progress
            )
        except Exception as ex:
            LOGGER.warning("finalize_incomplete: read_in_progress failed: %s", ex)
            disk_data = None
        if disk_data:
            start_ts = int(disk_data.get("session_start_ts", 0)) or now_unix
            end_ts = int(disk_data.get("last_update_ts", now_unix)) or now_unix
            area = float(disk_data.get("area_mowed_m2", 0.0))
            LOGGER.info(
                "finalize_incomplete: live_map empty; rebuilt from on-disk "
                "in_progress.json (start_ts=%s, end_ts=%s, area=%.1f m²)",
                start_ts, end_ts, area,
            )
        else:
            LOGGER.info(
                "finalize_incomplete: no live session and no on-disk in_progress; "
                "nothing to finalize — exiting"
            )
            return
    duration_min = max(0, (end_ts - start_ts) // 60)

    # Write a minimal JSON to disk so the session isn't silently lost.
    # Uses the same archive() mechanism but with a synthesised summary-like dict.
    incomplete_payload: dict[str, Any] = {
        "start": start_ts,
        "end": end_ts,
        "time": duration_min,
        "areas": area,
        "md5": "(incomplete)",
        "_note": "Cloud summary fetch expired; this entry was generated locally.",
    }
    # v1.0.12a2+: include telemetry sample buffers, legs, and
    # settings_snapshot when present. Delegates to the shared helper
    # in _LidarOssMixin so both paths stay in sync.
    coord._inject_live_map_into_raw_dict(incomplete_payload)

    # Recorder-merge safety net (2026-05-16 spec) — same layer
    # _do_oss_fetch uses, applied to the FINALIZE_INCOMPLETE
    # payload before it gets archived.
    await coord._merge_recorder_into_payload(
        incomplete_payload, label="FINALIZE_INCOMPLETE",
    )

    # Apply smoothing-only classify so incomplete-session archives get role
    # refinement (cloud_track=[] → smoothing still runs on track points).
    try:
        finalize_classify_raw_dict(incomplete_payload, [])
    except Exception:
        LOGGER.debug(
            "[F5.6.1] _do_finalize_incomplete: classify failed; "
            "incomplete archive will have stage-1 roles only"
        )

    # Build a duck-typed proxy that satisfies SessionArchive.archive(summary).
    # We use a SimpleNamespace because class-level attribute assignments can't
    # reference the enclosing function's local variables in Python.
    proxy = _types.SimpleNamespace(
        md5="(incomplete)",
        end_ts=end_ts,
        start_ts=start_ts,
        duration_min=duration_min,
        area_mowed_m2=area,
        map_area_m2=0,
        mode=0,
        result=0,
        stop_reason=0,
    )

    try:
        await coord.hass.async_add_executor_job(
            coord.session_archive.archive, proxy, incomplete_payload,
            coord._resolve_finalize_map_id()
        )
    except Exception as ex:
        LOGGER.warning("[F5.6.1] _do_finalize_incomplete: archive raised: %s", ex)

    # Clear pending state, delete the in-progress entry, fire the
    # mowing-ended event, and end the live_map session. Shared with the
    # cloud path via _post_archive_reset (local path = no extra updates).
    await coord._post_archive_reset(
        now_unix=now_unix,
        area_mowed_m2=area,
        duration_min=(
            int((now_unix - start_ts) / 60)
            if start_ts > 0
            else None
        ),
        completed=False,
    )


async def do_oss_fetch(coord, now_unix: int) -> None:
    """Download + archive the cloud-summary JSON for the pending session.

    The actual work runs inside _finalize_with_latch so concurrent entries
    for the same session de-dupe (single finalize latch, P3e.4). See
    _do_oss_fetch_body for the step-by-step flow.
    """
    await coord._finalize_with_latch(
        lambda: coord._do_oss_fetch_body(now_unix),
        label="OSS-fetch",
    )


async def do_oss_fetch_body(coord, now_unix: int) -> None:
    """Attempt to download and archive the cloud-summary JSON.

    1. call ``cloud_client.get_interim_file_url(object_name)`` to get a
       signed URL (blocking — executor).
    2. call ``cloud_client.get_file(url)`` to download the raw bytes
       (blocking — executor).
    3. Parse via ``protocol.session_summary.parse_session_summary``.
    4. Archive via ``SessionArchive.archive`` (blocking — executor).
    5. On success: clear pending fields, populate latest_session_*, call
       ``live_map.end_session()``.
    6. On failure: increment ``pending_session_attempt_count``.

    All blocking I/O goes through hass.async_add_executor_job per spec §3.
    Always invoked through _finalize_with_latch (never call directly).
    """
    # Photo-fetch + mow-type merge helpers stay in _lidar_oss.py (§2/§3
    # media/gallery concern, deferred to P3.9c); imported here at call time
    # to avoid a top-level domain→coordinator import cycle.
    from ...coordinator._lidar_oss import (
        fetch_photos_from_summary,
        merge_mow_type_fields,
    )

    object_name = coord.data.pending_session_object_name
    if not object_name:
        return

    # Guard: cloud client may not be ready during early boot.
    if not hasattr(coord, "_cloud") or coord._cloud is None:
        LOGGER.warning(
            "[F5.6.1] _do_oss_fetch: cloud client not ready; "
            "object_name=%r — will retry next tick",
            object_name,
        )
        return

    LOGGER.debug(
        "[F5.6.1] _do_oss_fetch: fetching object_name=%r (attempt #%s)",
        object_name,
        (coord.data.pending_session_attempt_count or 0) + 1,
    )

    # Increment attempt count and record last_attempt_unix before the fetch
    # so retries are tracked even if the fetch hangs or raises.
    new_count = (coord.data.pending_session_attempt_count or 0) + 1
    coord.async_set_updated_data(
        dataclasses.replace(
            coord.data,
            pending_session_attempt_count=new_count,
            pending_session_last_attempt_unix=now_unix,
        )
    )

    # Step 1: get signed URL (blocking).
    try:
        signed_url: str | None = await coord.hass.async_add_executor_job(
            coord._cloud.get_interim_file_url, object_name
        )
    except Exception as ex:
        LOGGER.warning(
            "[F5.6.1] _do_oss_fetch: get_interim_file_url raised: %s", ex
        )
        return

    if not signed_url:
        LOGGER.warning(
            "[F5.6.1] _do_oss_fetch: get_interim_file_url returned None "
            "for object_name=%r",
            object_name,
        )
        return

    # Step 2: download raw bytes (blocking).
    try:
        raw_bytes: bytes | None = await coord.hass.async_add_executor_job(
            coord._cloud.get_file, signed_url
        )
    except Exception as ex:
        LOGGER.warning(
            "[F5.6.1] _do_oss_fetch: get_file raised: %s", ex
        )
        return

    if not raw_bytes:
        LOGGER.warning(
            "[F5.6.1] _do_oss_fetch: get_file returned None for url=%r",
            signed_url,
        )
        return

    # Step 3: parse JSON.
    try:
        raw_dict: dict[str, Any] = json.loads(raw_bytes)
    except (json.JSONDecodeError, ValueError) as ex:
        LOGGER.warning(
            "[F5.6.1] _do_oss_fetch: JSON decode failed: %s — raw[:200]=%r",
            ex,
            raw_bytes[:200],
        )
        return

    # F6.4.1: schema-validate the JSON shape. Each novel key fires
    # [NOVEL_KEY/session_summary] WARNING once per process via the
    # registry's record_key gate.
    for key in _SESSION_SUMMARY_CHECK.diff_keys(raw_dict):
        if coord.novel_registry.record_key("session_summary", key, now_unix):
            LOGGER.warning(
                "%s key=%s — JSON shape drift, parser may need an update",
                LOG_NOVEL_KEY_SESSION_SUMMARY, key,
            )

    # v1.0.0a54+: inject locally-tracked fields (legs, WiFi samples,
    # telemetry streams, settings_snapshot) into the raw JSON before
    # archiving. Extracted into _inject_live_map_into_raw_dict so the
    # FINALIZE_INCOMPLETE path can reuse the same logic.
    coord._inject_live_map_into_raw_dict(raw_dict)

    # Album photos (Patrol + AI-obstacle). [dreame-app-implementation-guide-2026-06-09.md]
    try:
        n = await coord.hass.async_add_executor_job(
            lambda: fetch_photos_from_summary(
                coord._cloud, coord._photo_archive, raw_dict, sign=coord._photo_sign_fn
            )
        )
        if n:
            LOGGER.info("[PHOTOS] archived %d album photo(s); total=%d", n, coord._photo_archive.count)
    except Exception as ex:  # noqa: BLE001 — photos never break finalize
        LOGGER.warning("[PHOTOS] fetch failed: %s", ex)

    # Recorder-merge safety net (2026-05-16 spec): fill gaps in the
    # battery/wifi sample arrays from HA's recorder history. Idempotent;
    # any failure leaves the in_progress samples untouched.
    await coord._merge_recorder_into_payload(
        raw_dict, label="OSS-fetch finalize",
    )

    try:
        summary = _session_summary.parse_session_summary(raw_dict)
    except _session_summary.InvalidSessionSummary as ex:
        LOGGER.warning(
            "[F5.6.1] _do_oss_fetch: parse_session_summary failed: %s", ex
        )
        return

    finalize_classify_raw_dict(raw_dict, summary.track_segments)
    merge_mow_type_fields(raw_dict, mode=summary.mode, start_mode=summary.start_mode)

    # Step 4: archive (blocking disk I/O).
    # Stamp the map_id so the replay picker can show [Map N] prefix.
    finalize_map_id = coord._resolve_finalize_map_id()
    try:
        archived_entry: ArchivedSession | None = await coord.hass.async_add_executor_job(
            coord.session_archive.archive, summary, raw_dict, finalize_map_id
        )
    except Exception as ex:
        LOGGER.warning("[F5.6.1] _do_oss_fetch: archive raised: %s", ex)
        return

    LOGGER.debug(
        "[F5.6.1] _do_oss_fetch: archived session md5=%r area=%.1fm² "
        "duration=%dmin (already_exists=%s)",
        summary.md5,
        summary.area_mowed_m2,
        summary.duration_min,
        archived_entry is None,
    )
    # Invalidate the per-map "last-session obstacles" overlay cache
    # for this map, so the next Main-view render picks up the
    # freshly-archived session's obstacles.
    coord._last_session_obstacles_by_map.pop(finalize_map_id, None)
    # v1.0.0a50: when md5 dedup hits we silently land on an
    # already-archived entry — picker will not show a new row.
    # Surface object_name + parsed start/end so the cloud's
    # md5-recycling can be diagnosed and (if needed) the dedup
    # rule reworked to use object_name or start_ts instead.
    if archived_entry is None:
        LOGGER.debug(
            "[F5.6.1] _do_oss_fetch: md5 dedup hit — "
            "object_name=%r start_ts=%s end_ts=%s area=%.1f map_area=%s "
            "(picker will NOT show a new row; cloud reused md5)",
            object_name,
            summary.start_ts,
            summary.end_ts,
            summary.area_mowed_m2,
            summary.map_area_m2,
        )

    # Step 5: update MowerState — clear pending, populate latest_session_*,
    # increment archived_session_count, end the live_map session.
    # The in_progress.json file must be removed too; without that, the
    # picker keeps synthesizing a phantom "in progress" entry from disk
    # alongside the freshly-archived row (same bug v1.0.0a25 fixed for
    # the manual Finalize path; v1.0.0a42 closes the auto-finalize hole).

    # Shared post-archive teardown (delete_in_progress, clear pending op,
    # fire mowing-ended, end live_map, publish MowerState). The cloud path
    # additionally sets latest_session_* / total_lawn_area_m2 / the
    # mow-direction map via extra_updates.
    await coord._post_archive_reset(
        now_unix=now_unix,
        area_mowed_m2=summary.area_mowed_m2,
        duration_min=summary.duration_min,
        completed=True,
        delete_log_tag="_do_oss_fetch",
        extra_updates={
            "latest_session_unix_ts": summary.end_ts,
            "latest_session_area_m2": summary.area_mowed_m2,
            "latest_session_duration_min": summary.duration_min,
            # v1.0.0a22: pull total lawn area from the session
            # summary's `map_area` field. s2.66 (the MQTT push that
            # also carries this value) fires rarely on g2408, so
            # session-summary is the more reliable source of truth.
            # Only update when the summary has a non-zero map_area
            # (some incomplete entries set it to 0).
            "total_lawn_area_m2": (
                float(summary.map_area_m2)
                if summary.map_area_m2 else coord.data.total_lawn_area_m2
            ),
        },
    )

    # A session just finalized — kick a one-shot OSS gallery sync shortly
    # after, so VIDEOS and any gallery media NOT in the summary's photo_list
    # (already fetched above by fetch_photos_from_summary) appear within
    # ~seconds instead of waiting up to the 1h periodic sync. Delayed (not
    # immediate) to give the device's async upload — incl. lazy auto-capture
    # uploads, see api key session_summary_download — time to land on OSS.
    coord._schedule_post_session_gallery_refresh()
