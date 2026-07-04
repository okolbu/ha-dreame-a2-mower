"""Session lifecycle-edge detectors (layer 4) — extracted from
``coordinator/_mqtt_handlers.py:_on_state_update`` in refactor-v2 P3.7
(autopsy #3 scope #2).

``_on_state_update`` was a 375-LOC god-method fusing a dozen concerns: task-state
begin/pause/resume inference, telemetry appends, MowerState session-view sync,
non-mow session-end edge, dock arrival/departure, charging edges, self-shutdown
edge, s2p2 notification synthesis, freshness recording, LiDAR-object trigger, and
the pending-finalize dock-return signal.

This module decomposes it along those exact seams into NAMED functions plus one
orchestrator (:func:`on_state_update`). **The logic is VERBATIM** — the corpus-
validated begin/end inference and every lifecycle-edge branch are preserved
branch-for-branch; ``self`` became ``coord`` and nothing else changed. The
coordinator keeps thin delegating methods for its public/test surface.

Side effects are intentional and preserved: these functions fire lifecycle
events, mutate ``coord.live_map``, advance the ``coord._prev_*`` edge trackers,
and schedule renders/tasks exactly as the pre-split method did. The corpus
IDENTICAL gate + the interleaving/thread-safety/event-entity test suites pin the
behaviour. Purity was NOT pursued where it would have meant reimplementing the
event-firing (which would risk corpus/behaviour drift); genuinely pure predicates
stay inline in the branch conditions they belong to.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from ...const import (
    EVENT_TYPE_CHARGING_COMPLETE,
    EVENT_TYPE_CHARGING_STARTED,
    EVENT_TYPE_DOCK_ARRIVED,
    EVENT_TYPE_DOCK_DEPARTED,
    EVENT_TYPE_MOWING_PAUSED,
    EVENT_TYPE_MOWING_RESUMED,
    EVENT_TYPE_MOWING_STARTED,
    EVENT_TYPE_RAIN_DELAY_STARTED,
    EVENT_TYPE_SELF_SHUTDOWN,
    LOGGER,
)
from ...coordinator._snapshot import build_settings_snapshot_v2
from ...mower.error_codes import S2P2_EVENT_TYPES
from ...state import MowerState
from .signals import capture_session_type_signals


# ---------------------------------------------------------------------------
# Standalone lifecycle-edge fire helpers (were mixin methods).
# ---------------------------------------------------------------------------
def maybe_fire_charging_events(
    coord, charging_status, now_unix: int, battery: int | None
) -> None:
    """Fire charging_started / charging_complete on s3.2 rising edges.

    Distinct from dock_arrived (cloud DOCK connect_status): this is the
    energy-state. The first observation only primes _prev so a charging
    state already active at HA boot doesn't fire spuriously.
    """
    if charging_status is None:
        return
    new_val = (
        charging_status.value
        if hasattr(charging_status, "value")
        else int(charging_status)
    )
    prev = coord._prev_charging_status
    if prev is not None and new_val != prev:
        if new_val == 1:  # ChargingStatus.CHARGING
            coord._fire_lifecycle(
                EVENT_TYPE_CHARGING_STARTED,
                {"at_unix": int(now_unix), "battery_level": battery},
            )
        elif new_val == 2:  # ChargingStatus.CHARGED
            coord._fire_lifecycle(
                EVENT_TYPE_CHARGING_COMPLETE,
                {"at_unix": int(now_unix), "battery_level": battery},
            )
    coord._prev_charging_status = new_val


def fire_rain_delay_started_if_edge(
    coord, *, old: int | None, new: int | None, now_unix: int
) -> None:
    """On the s2p2 rising edge into 56 (rain_protection), record the
    start time and fire rain_delay_started. No rain-END signal exists,
    so the field is cleared elsewhere (dock departure / session end)."""
    if new == 56 and old != 56:
        coord._rain_delay_started_at = int(now_unix)
        coord._fire_lifecycle(
            EVENT_TYPE_RAIN_DELAY_STARTED, {"at_unix": int(now_unix)}
        )


def fire_self_shutdown_if_edge(
    coord, *, old: int | None, new: int | None, now_unix: int
) -> None:
    """Fire self_shutdown on the s2p57 rising edge into 1 (firmware
    self-shutdown — confirmed low-battery protective cutoff 2026-06-14).
    First observation only primes _prev so a value already 1 at boot
    doesn't fire spuriously."""
    if old is None:
        return  # first observation primes _prev (caller sets it)
    if new == 1 and old != 1:
        coord._fire_lifecycle(
            EVENT_TYPE_SELF_SHUTDOWN,
            {"at_unix": int(now_unix), "reason": "low_battery", "value": int(new)},
        )


def capture_telemetry_sample(
    coord, key: tuple[int, int], value: Any, now_unix: int
) -> None:
    """Append a raw telemetry value to the matching LiveMapState
    sample buffer. Runs on the event loop (hop done by caller).

    Only the BUFFER append fires while a session is active. The raw int
    wire value is captured verbatim — interpretation (charging-status
    enum, s2p2 notification map) happens at archive-consumer time.
    """
    # Patrol-start latch (UNGATED — runs before the is_active() guard).
    # s2p2=51 (patrol started) is a POINT patrol's only type signal and it
    # arrives AT session start, before begin_session exists; the guard below
    # would otherwise drop it. Latch it so the session is typed patrol even
    # though it never lands in error_samples.
    if key == (2, 2):
        try:
            if int(value) == 51:
                coord._pending_saw_patrol_start = True
                if coord.live_map.is_active():
                    coord.live_map.saw_patrol_start = True
        except (TypeError, ValueError):
            pass
    if not coord.live_map.is_active():
        return
    try:
        v_int = int(value)
    except (TypeError, ValueError):
        return
    lm = coord.live_map
    if key == (3, 1):
        buf = lm.battery_samples
    elif key == (3, 2):
        buf = lm.charging_status_samples
    elif key == (2, 1):
        lm.update_task_state(float(now_unix), v_int)
        coord._live_map_dirty = True
        return
    elif key == (2, 2):
        buf = lm.error_samples
    else:
        return
    if lm.append_telemetry_sample(buf, v_int, now_unix):
        coord._live_map_dirty = True


# ---------------------------------------------------------------------------
# _on_state_update seam functions (VERBATIM slices; called in original order).
# ---------------------------------------------------------------------------
def _detect_session_transitions(
    coord, new_state: MowerState, now_unix: int, *, prev, new_task_state
) -> None:
    """Task-state begin / pause / resume inference (corpus-validated)."""
    if new_task_state != prev:
        # v1.0.0a48: bumped to WARNING so the trail is visible in
        # the HA default log without enabling DEBUG. Each mow only
        # produces a handful of these so noise stays low.
        LOGGER.debug(
            "[F5] task_state_code transition %r → %r (live_map.is_active=%s)",
            prev, new_task_state, coord.live_map.is_active(),
        )
    # Begin a session whenever we transition from a non-active code
    # (None=idle, 2=complete) to an active code (0=running,
    # 4=paused). prev=4→new=0 is the recharge-resume case which
    # starts a new leg rather than a new session.
    is_active_now = new_task_state in (0, 4)
    was_active_before = prev in (0, 4)
    if is_active_now and not was_active_before and not coord.live_map.is_active():
        # Skip begin_session when live_map is already active — that
        # means _restore_in_progress repopulated legs/started_unix
        # from disk (mid-mow HA restart). begin_session would clear
        # legs to [[]] and reset started_unix to now_unix, abandoning
        # the pre-restart trail. Just continue appending to the
        # restored leg.
        coord.live_map.begin_session(now_unix)
        # Seed the just-born session's type from the op echo that arrived
        # before it existed (begin_session nulled last_task_op). Fixes the
        # dock-start race where the s2p50 echo / s2p2=51 are lost.
        coord._seed_session_type_from_pending()
        # Reset the published live position stream so the new session's
        # trail starts clean on the client card.
        coord._begin_live_stream()
        # Snapshot battery % at session start so the archive consumer
        # has a cheap start/end SoC pair without scanning the full
        # battery_samples list. None when battery_level isn't known
        # yet — the first s3p1 push will still populate samples.
        if new_state.battery_level is not None:
            try:
                coord.live_map.charge_at_start = int(new_state.battery_level)
            except (TypeError, ValueError):
                pass
        # Snapshot the FULL firmware state at session start (settings_snapshot v2 —
        # per_map + device_wide + peripheral + forensic). Replaces the v1 narrow
        # per-map-only dict; v1 archive consumers continue to read the per_map
        # subsection via the v1-fallback path in session_card.py.
        coord.live_map.settings_snapshot = build_settings_snapshot_v2(
            coord, captured_at_unix=int(now_unix)
        )
        coord._fire_lifecycle(
            EVENT_TYPE_MOWING_STARTED,
            {
                "at_unix": int(now_unix),
                "action_mode": (
                    new_state.action_mode.value
                    if new_state.action_mode is not None
                    else None
                ),
                "target_area_m2": new_state.target_area_m2,
            },
        )
        # Re-poll MAPL so the live trail lands on the firmware's
        # current active map, even if the last 2-min cloud refresh was
        # before the user switched maps.
        hass = getattr(coord, "hass", None)
        if hass is not None:
            hass.async_create_task(coord._refresh_mapl())
    elif (
        new_task_state == 4
        and prev != 4
        and coord.live_map.is_active()
    ):
        # Mid-mow pause. Previously gated on `prev == 0` exactly,
        # but a transient `0 → None` observation (occasional MQTT
        # parse blip; system_log shows "[F5] task_state_code
        # transition 0 → None" entries) overwrites _prev_task_state
        # to None, after which the true `0 → 4` pause arrives as
        # `None → 4` and the strict prev==0 check skips it.
        # Resume still fires (prev becomes 4 when pause finally
        # latches) but the pause event was lost.
        #
        # Generalise: pause fires on any "was-not-already-paused"
        # → "now paused" transition while the live_map is active
        # (i.e., we're genuinely mid-session). Live_map.is_active
        # gates against firing pause when the integration first
        # observes task_state=4 on boot before any session is
        # running.
        #
        # Reason is best-effort: if the current MowerState exposes
        # an obvious cause use it, otherwise "unknown".
        reason = "unknown"
        if new_state.battery_level is not None and new_state.battery_level <= 20:
            reason = "recharge_required"
        coord._fire_lifecycle(
            EVENT_TYPE_MOWING_PAUSED,
            {
                "at_unix": int(now_unix),
                "area_mowed_m2": new_state.area_mowed_m2,
                "reason": reason,
            },
        )
    elif prev == 4 and new_task_state == 0:
        # Recharge-resume. No explicit leg break needed in the track
        # model: the pause→resume time gap naturally creates a pen-up
        # boundary that derive_render_legs() splits on at render time.
        coord._fire_lifecycle(
            EVENT_TYPE_MOWING_RESUMED,
            {
                "at_unix": int(now_unix),
                "area_mowed_m2": new_state.area_mowed_m2,
            },
        )


def _append_session_telemetry(coord, new_state: MowerState, now_unix: int) -> None:
    """Append the current position to the active session's track + publish
    it to the live stream (only when session active + position + changed)."""
    if (
        coord.live_map.is_active()
        and new_state.position_x_m is not None
        and new_state.position_y_m is not None
        and (new_state != coord.data)  # something changed
    ):
        import time as _time
        before_pts = coord.live_map.total_points()
        coord.live_map.append_point(
            t=_time.time(),
            x_m=new_state.position_x_m,
            y_m=new_state.position_y_m,
            area_m2=(new_state.area_mowed_m2 or 0.0),
            heading_deg=new_state.position_heading_deg,
        )
        capture_session_type_signals(
            coord.live_map,
            s2p56_status=None,
            s2p50_op=None,
            area_m2=new_state.area_mowed_m2,
        )
        # Mark dirty if a point was actually added (dedup may have skipped it).
        if coord.live_map.total_points() > before_pts:
            coord._live_map_dirty = True
            # Rehaul: instead of compositing a fresh PNG on every push,
            # publish the new position to the live stream the map camera
            # exposes as attributes, then push listeners so the client
            # card (which draws the trail + icon) picks it up. No throttle:
            # publishing is a list append, not a PIL render.
            coord._publish_live_point(
                x_m=float(new_state.position_x_m),
                y_m=float(new_state.position_y_m),
                heading_deg=(
                    float(new_state.position_heading_deg)
                    if new_state.position_heading_deg is not None else None
                ),
                t=float(now_unix),
            )
            # Push listeners so the map camera entity re-exposes the new
            # live-stream attributes. Defensive getattr/callable guard
            # (mirrors the MAPL trigger) so __init__-bypassing test
            # fixtures that don't set up the DataUpdateCoordinator base
            # don't crash on this append-path side effect.
            _update_listeners = getattr(coord, "async_update_listeners", None)
            if callable(_update_listeners):
                _update_listeners()


def _sync_session_view(coord, new_state: MowerState) -> MowerState:
    """Sync MowerState's session view from LiveMapState (returns new state)."""
    # session_distance_m is integrated from the track (sum of segment lengths,
    # pen-up gaps excluded) — see LiveMapState.total_distance_m().
    # session_track_segments is a flat tuple of the captured (x_m, y_m) points
    # (one segment) so the session-points sensor has a count to report; the
    # per-leg split now lives in derive_render_legs() at render time.
    # Cleared to None when no session is active so the sensor goes
    # unavailable between mows rather than persisting the last value.
    return dataclasses.replace(
        new_state,
        session_started_unix=coord.live_map.started_unix,
        session_track_segments=(
            tuple((p.x_m, p.y_m) for p in coord.live_map.track),
        ),
        session_distance_m=(
            coord.live_map.total_distance_m() if coord.live_map.is_active() else None
        ),
        target_area_m2=coord._compute_target_area_m2(new_state),
    )


def _detect_non_mow_end_edge(
    coord, new_state: MowerState, now_unix: int, *, prev, new_task_state
) -> None:
    """(B) ROBUSTNESS: non-mow session end via task_state edge 0/4→2/None.

    The edge is visible HERE before _prev_task_state is advanced by the
    orchestrator.  If s2p2=75 was missed (e.g. arrived before session
    began, or MQTT drop) this catches the structural completion signal.
    GUARD: non-cloud-finalized only — mow/patrol sessions must NOT be
    finalized here; they wait for the OSS summary via the periodic retry.
    """
    if (
        prev in (0, 4)
        and new_task_state in (2, None)
        and coord.live_map.is_active()
        and not coord._provisional_session_is_cloud_finalized()
    ):
        LOGGER.debug(
            "[F5] non-mow session end edge %r→%r — scheduling immediate finalize",
            prev, new_task_state,
        )
        _hass = getattr(coord, "hass", None)
        if _hass is not None:
            import time as _time
            _hass.async_create_task(
                coord._finalize_non_mow_immediate(
                    int(_time.time()), "task_state_edge"
                )
            )


def _detect_dock_edges(coord, new_state: MowerState, now_unix: int) -> None:
    """Dock arrival/departure rising/falling edges + _prev_in_dock advance."""
    # Read current dock state from the state machine (SM-14: mower_in_dock
    # removed from MowerState; Location.AT_DOCK is the canonical source).
    # Explicit `is True` / `is False` on _prev_in_dock so the boot-time None
    # doesn't fire a spurious arrived/departed event.
    # Defensive: test fixtures construct via __new__ without __init__,
    # so state_machine may be missing; treat as "not at dock" then.
    from ...state.snapshot import Location as _Location
    _sm = getattr(coord, "state_machine", None)
    _sm_at_dock: bool = (
        _sm is not None and _sm.snapshot().location == _Location.AT_DOCK
    )
    if coord._prev_in_dock is False and _sm_at_dock:
        coord._fire_lifecycle(
            EVENT_TYPE_DOCK_ARRIVED, {"at_unix": int(now_unix)}
        )
        # Bug 2 fix: trigger a render on dock-arrival so the idle pre-start
        # preview (stripes) appears promptly instead of waiting for the next
        # 2-minute cloud refresh.  The live_map session is already over at
        # this point (session-end fires before dock-arrival), so
        # _render_base will compute an idle background mode and render the
        # appropriate preview (stripes for ALL_AREAS/ZONE, edge/spot for
        # EDGE/SPOT). Dock-arrival is also an activity transition, so the
        # general trigger above may already cover it — the md5+mode dedup
        # in _render_base makes a second call a cheap no-op.
        _hass = getattr(coord, "hass", None)
        if _hass is not None:
            coord._schedule_render_base()
    elif coord._prev_in_dock is True and not _sm_at_dock:
        coord._fire_lifecycle(
            EVENT_TYPE_DOCK_DEPARTED, {"at_unix": int(now_unix)}
        )
        coord._rain_delay_started_at = None  # left dock → rain wait over
    coord._prev_in_dock = _sm_at_dock


def _detect_self_shutdown_edge(coord, new_state: MowerState, now_unix: int) -> None:
    """s2p57 self-shutdown lifecycle edge. First observation only primes
    _prev_shutdown_trigger so a value already 1 at boot doesn't fire."""
    _new_shutdown = new_state.robot_shutdown_trigger
    if _new_shutdown is not None:
        fire_self_shutdown_if_edge(
            coord,
            old=coord._prev_shutdown_trigger,
            new=_new_shutdown,
            now_unix=now_unix,
        )
        coord._prev_shutdown_trigger = _new_shutdown


def _detect_s2p2_notification(coord, new_state: MowerState, now_unix: int) -> None:
    """F13 — s2p2 notification synthesis. Fire dreame_a2_mower_alert on
    transitions to known notification codes. The first push on HA boot
    is intentionally suppressed (_prev_error_code starts as None so
    the FIRST observed value just primes the tracker without firing
    — we don't want to re-emit a stale alert for whatever code was
    active at restart).

    Critical: only update _prev_error_code when we observe a non-None
    value. s2p2 occasionally goes through transient None states
    (the property push doesn't always carry the slot). If we
    overwrite prev to None during a transient, the next real
    transition (e.g., None → 70) gets suppressed by the
    `old_code is not None` boot-guard. This was the cause of the
    alert event entity having ZERO entries despite 70 firing
    multiple times in the probe log. Same bug pattern as the
    mowing_paused fix in commit 87e2bbe.
    """
    new_error_code = new_state.error_code
    old_error_code = coord._prev_error_code
    if (
        new_error_code is not None
        and new_error_code != old_error_code
        and old_error_code is not None  # suppress first-push-after-boot
    ):
        # 2026-05-26: cloud-driven notification. The hardcoded
        # (event_type, text) tuple is gone — we kick off an async
        # resolver that fetches the authoritative text from
        # /dreame-messaging/user/device-messages/v2 after a short
        # delay (~10s, to let the cloud finish writing its push
        # record) and fires the event ONLY if the cloud actually
        # pushed for this transition. Unknown codes (not in
        # S2P2_EVENT_TYPES) still fire — with slug "unknown_s2p2"
        # — and a WARNING is logged so the maintainer can extend
        # the slug table.
        hass = getattr(coord, "hass", None)
        if hass is not None:
            _resolver_task = hass.async_create_task(
                coord._resolve_s2p2_notification(
                    siid=2, piid=2, value=int(new_error_code),
                    now_unix=now_unix,
                )
            )
            # T3-8: track so async_unload_entry can cancel any resolver
            # still sleeping its ~10s delay at unload time; self-removes
            # from the set on completion (success, error, or cancel).
            tasks = coord.s2p2_resolver_tasks
            if tasks is not None and hasattr(_resolver_task, "add_done_callback"):
                tasks.add(_resolver_task)
                _resolver_task.add_done_callback(tasks.discard)
        # Local fire is the guaranteed floor; the cloud resolver scheduled above may
        # also fire (source="cloud") ~10s later → two activity entries for one
        # unknown-code transition is expected.
        if S2P2_EVENT_TYPES.get(int(new_error_code)) is None:
            coord._fire_local_novel_s2p2(
                code=int(new_error_code), now_unix=now_unix
            )
        fire_rain_delay_started_if_edge(
            coord, old=old_error_code, new=new_error_code, now_unix=now_unix
        )
    if new_error_code is not None:
        coord._prev_error_code = new_error_code


def _detect_lidar_object_name(coord, new_state: MowerState, now_unix: int) -> None:
    """F7.2.2: kick off LiDAR fetch when object_name flips to a new key."""
    prev_lidar = getattr(coord.data, "latest_lidar_object_name", None)
    if (
        new_state.latest_lidar_object_name is not None
        and new_state.latest_lidar_object_name != prev_lidar
    ):
        coord.hass.async_create_task(
            coord._handle_lidar_object_name(
                new_state.latest_lidar_object_name, now_unix
            )
        )


def _detect_dock_return_signal(coord, new_state: MowerState) -> None:
    """Pending-finalize dock-return signal.

    If _wait_for_dock_return is currently blocking, check whether
    this state update represents the mower physically docking.
    Signal fires ONLY when:
      - charging_status == ChargingStatus.CHARGING (value 1, docked+charging)
    We deliberately do NOT fire on task_idle (task_state_code is None):
    that condition becomes true the instant the session ends, before the
    mower drives home — firing there would cut off dock-return capture.
    The wait therefore completes only on physical dock (charging) or
    timeout. The event is cleared to None by _wait_for_dock_return's
    finally block so this guard is harmless outside of an active wait.
    """
    done_event = coord.pending_finalize_done
    if done_event is not None and not done_event.is_set():
        is_charging = False
        cs = new_state.charging_status
        if cs is not None:
            # ChargingStatus is IntEnum; .value extracts the int.
            cs_val = cs.value if hasattr(cs, "value") else int(cs)
            is_charging = cs_val == 1  # ChargingStatus.CHARGING
        if is_charging:
            coord._pending_finalize_done_reason = "charging"
            done_event.set()


def on_state_update(coord, new_state: MowerState, now_unix: int) -> MowerState:
    """Hook fired after apply_property_to_state. Updates LiveMapState
    based on s2p56 transitions and appends s1p4 positions to the
    current leg.

    Returns a possibly-modified MowerState (with session_active /
    session_started_unix / session_track_segments synced from LiveMapState).

    Orchestrator — calls the seam detectors above in the EXACT original order.
    """
    new_task_state = new_state.task_state_code
    prev = coord._prev_task_state

    # Mark that we've now seen a real task_state from MQTT so the
    # finalize gate can distinguish "task is genuinely idle/end"
    # from "task_state_code defaulted to None because we just
    # booted into an MQTT-quiet window". Latches once observed —
    # subsequent transitions to None are then legitimately a
    # session-end signal.
    if new_task_state is not None:
        coord._real_task_state_observed = True

    # v1.0.0a18: task_state_code semantics changed when the s2.56
    # extract_value was fixed to read status[0][1] (the sub-state).
    # New mapping: 0 = running, 4 = paused-pending-resume,
    # None = no task (status: []). begin_session fires on any
    # transition from None to a non-None task; the 4 → 0 recharge
    # resume just continues appending to the track (the pause→resume
    # time gap becomes a pen-up boundary at render/finalize time).
    _detect_session_transitions(
        coord, new_state, now_unix, prev=prev, new_task_state=new_task_state
    )

    # Telemetry append: if session is active and a position is available
    # and something changed this tick, append the current position.
    _append_session_telemetry(coord, new_state, now_unix)

    # Sync MowerState's session view from LiveMapState.
    new_state = _sync_session_view(coord, new_state)

    _detect_non_mow_end_edge(
        coord, new_state, now_unix, prev=prev, new_task_state=new_task_state
    )

    coord._prev_task_state = new_task_state

    _detect_dock_edges(coord, new_state, now_unix)
    maybe_fire_charging_events(
        coord, new_state.charging_status, now_unix, new_state.battery_level
    )

    _detect_self_shutdown_edge(coord, new_state, now_unix)

    _detect_s2p2_notification(coord, new_state, now_unix)

    # F6 review fix #1: record freshness AFTER all derivations so
    # session-derived fields (session_active, session_started_unix,
    # session_track_segments) are stamped with accurate timestamps.
    coord.freshness.record(coord.data, new_state, now_unix=now_unix)

    _detect_lidar_object_name(coord, new_state, now_unix)

    _detect_dock_return_signal(coord, new_state)

    return new_state
