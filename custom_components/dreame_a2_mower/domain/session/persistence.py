"""Session persistence service (layer 4) — extracted VERBATIM from
``coordinator/_session.py`` in refactor-v2 P3.9a.

Owns the in_progress.json lifecycle: restore-then-merge on boot
(``restore_in_progress``, including the P2.7 restore×finalize discard guard),
the debounced 30-s persist (``persist_in_progress``, with the T3-12 TOCTOU
``_finalize_lock`` hold), and the pending-op sidecar
(``load_pending_op_from_sidecar`` / ``clear_pending_op``).

Each function takes the coordinator (``coord``) as its first argument. The
persistence state (``_live_map_dirty``, ``_pending_task_op``,
``_pending_saw_patrol_start``, ``_rain_delay_started_at``, ``_prev_task_state``,
``_finalize_lock``, ``_finalizing_start_ts``) still lives on ``_CoreMixin.__init__``
(T2-16 — attrs move with the thin-coordinator collapse in 9e); these functions
read/write it on ``coord``. The coordinator keeps thin ``_SessionMixin``
delegators for its public + test surface.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from ...const import LOGGER


def load_pending_op_from_sidecar(coord) -> None:
    """Restore the pending task op persisted before a boot (no live session
    yet). A reboot AFTER begin_session is covered separately by
    in_progress.json's last_task_op."""
    op = coord.session_archive.read_pending_op()
    if op is not None:
        coord._pending_task_op = op


def clear_pending_op(coord) -> None:
    """Drop the pending type latches (op + patrol-start) + the op sidecar so
    a finished session's signals cannot seed a later one (no-window valve)."""
    coord._pending_task_op = None
    coord._pending_saw_patrol_start = False
    coord.session_archive.delete_pending_op()


async def restore_in_progress(coord) -> None:
    """Restore a live session from sessions/in_progress.json on HA boot.

    Uses restore-then-merge: always reads disk FIRST, merges with the
    current in-memory state (which may already contain MQTT-pushed data
    if a broker-retained push beat us here), then hydrates live_map from
    the merged result. Either side's data survives the race.

    Prior behaviour bailed out when live_map.is_active() was True,
    causing the 2026-05-15 19h-session data-loss: an MQTT push arriving
    before restore left 8.5h of persisted samples silently overwritten
    by the next _persist_in_progress tick.

    Early-return only when disk is empty AND live_map has no session —
    i.e. nothing to restore on either side.
    """
    from ...coordinator._restore_merge import merge_in_progress_payloads

    LOGGER.info("[F5.7.1] _restore_in_progress: starting (restore-then-merge)")

    # Recover the pending task op latched before the previous shutdown,
    # in case the restart straddled the op-echo -> begin_session window.
    coord._load_pending_op_from_sidecar()

    try:
        disk_payload: dict | None = await coord.hass.async_add_executor_job(
            coord.session_archive.read_in_progress
        )
    except Exception as ex:
        LOGGER.warning("[F5.7.1] _restore_in_progress: read_in_progress raised: %s", ex)
        disk_payload = None

    if disk_payload is None and not coord.live_map.is_active():
        LOGGER.debug(
            "[F5.7.1] _restore_in_progress: no disk payload and no live session"
            " — nothing to restore"
        )
        return

    # Snapshot in-memory state as a payload so merge_in_progress_payloads
    # can compare apples-to-apples with the disk payload.
    memory_payload = coord.live_map.dump_to_payload()
    merged = merge_in_progress_payloads(disk=disk_payload, memory=memory_payload)

    # Validate merged result has a usable session_start_ts.
    try:
        merged_start = int(merged.get("session_start_ts", 0) or 0)
    except (TypeError, ValueError):
        merged_start = 0

    if merged_start <= 0:
        LOGGER.warning(
            "[F5.7.1] _restore_in_progress: merged payload has no valid"
            " session_start_ts — discarding"
        )
        return

    # Restore × finalize race guard (P2 Task 7 / T7-19): a finalize can
    # run to completion while this coroutine is suspended in the
    # read_in_progress executor hop above. The finalize archives the
    # session, stamps _finalizing_start_ts (the latch's completion key)
    # and deletes in_progress.json — but we already hold the pre-delete
    # disk payload. Hydrating it back would resurrect the just-archived
    # session as a zombie that a later gate tick re-archives (the
    # "(incomplete)" md5 never matches the cloud md5, so the
    # archive-level dedup cannot catch the duplicate). Same dedup key as
    # _finalize_with_latch: discard when the merged payload IS the
    # finalized session.
    if merged_start == coord.finalizing_start_ts:
        LOGGER.info(
            "[F5.7.1] _restore_in_progress: session start_ts=%s was"
            " finalized while the disk read was in flight — discarding"
            " stale in-progress payload",
            merged_start,
        )
        return

    # Hydrate live_map from the merged payload.
    coord.live_map.hydrate_from_payload(merged)

    # Restore last_telemetry_unix from whichever payload has it.  This
    # field is written to disk as "last_update_ts" by _persist_in_progress
    # (legacy key) — not part of the merge contract, so patch it here.
    for src in (disk_payload, memory_payload):
        if src is None:
            continue
        raw_ts = src.get("last_update_ts", 0)
        try:
            ts = int(raw_ts or 0) or None
        except (TypeError, ValueError):
            ts = None
        if ts is not None:
            if (
                coord.live_map.last_telemetry_unix is None
                or ts > coord.live_map.last_telemetry_unix
            ):
                coord.live_map.last_telemetry_unix = ts

    LOGGER.info(
        "[F5.7.1] _restore_in_progress: restore-merged:"
        " started_unix=%s, track_points=%d,"
        " battery_samples=%d, wifi_samples=%d, state_samples=%d",
        coord.live_map.started_unix,
        coord.live_map.total_points(),
        len(coord.live_map.battery_samples),
        len(coord.live_map.wifi_samples),
        len(coord.live_map.state_samples),
    )

    # Seed state machine: an in_progress.json on disk proves a real
    # mow session was active. Without this, the state machine would
    # stay BETWEEN_SESSIONS until the next start event — which only
    # fires on the NEXT session, not the current one.
    sm = getattr(coord, "state_machine", None)
    if sm is not None:
        try:
            import time as _time
            sm.seed_in_session(now_unix=int(_time.time()))
        except Exception:
            LOGGER.exception(
                "state_machine.seed_in_session failed during restore"
            )

    # Restore the rain-delay context BEFORE arming the finalize gate
    # below. _rain_delay_started_at is coordinator (not live_map) state and
    # is otherwise in-memory only, so it would be lost across a reboot —
    # leaving coordinator.rain_delay_active reading False and the gate with
    # no signal that a docked-charging mower is merely waiting out rain.
    # With it restored, the seeded prev_task_state=0 below no longer drives
    # a premature FINALIZE_INCOMPLETE of a rain-paused session.
    if disk_payload is not None:
        raw_rain = disk_payload.get("rain_delay_started_at")
        try:
            coord._rain_delay_started_at = (
                int(raw_rain) if raw_rain is not None else None
            )
        except (TypeError, ValueError):
            coord._rain_delay_started_at = None

    # Seed _prev_task_state to "running" so the finalize gate's
    # session-end detection (prev ∈ {0,4} → new ∈ {2,None}) fires on
    # the next MQTT tick if the mower has actually gone idle while
    # HA was off. Without this, prev stays None at boot and the
    # idle-while-off case wouldn't trigger FINALIZE_INCOMPLETE.
    coord._prev_task_state = 0

    # Sync MowerState.
    new_state = dataclasses.replace(
        coord.data,
        session_started_unix=merged_start,
        # Single flat segment holding all restored track points — same
        # shape _mqtt_handlers.py emits under the track model.
        session_track_segments=(
            (tuple((p.x_m, p.y_m) for p in coord.live_map.track),)
            if coord.live_map.track else ()
        ),
    )
    coord.async_set_updated_data(new_state)
    LOGGER.info("[F5.7.1] _restore_in_progress: MowerState updated (session restored from disk)")


async def persist_in_progress(coord, _now: Any = None) -> None:
    """Write the current live_map state to sessions/in_progress.json.

    Scheduled every 30 seconds via async_track_time_interval.  Only
    writes when the session is active AND the dirty flag is set
    (i.e. at least one new point has been appended since the last write).
    This debounces the persist: if the mower is idle no new points arrive
    so no unnecessary disk I/O occurs.

    All blocking I/O goes through hass.async_add_executor_job per spec §3.

    T3-12 (TOCTOU): the whole check-then-write runs under
    ``_finalize_lock`` — the SAME lock ``_finalize_with_latch`` holds for
    the brief archive-write critical section (delete_in_progress +
    end_session, see ``_post_archive_reset``). Before this fix, a persist
    tick landing between a finalize's archive write and its
    ``delete_in_progress`` could resurrect ``in_progress.json`` for an
    already-archived session (a phantom "still running" picker row).
    Acquiring the lock here fully closes the window: either persist runs
    first and finishes before finalize's critical section starts, or it
    blocks until finalize releases the lock — by which point
    ``end_session()`` has already flipped ``live_map.is_active()`` False,
    so the re-checked guard below correctly no-ops. No new lock is
    introduced (see the P2 Task 8 report's lock-order analysis: this
    method never calls into the finalize path, so there is no cycle to
    deadlock on) and the hold time is bounded to one archive write — not
    the multi-minute dock-wait, which runs BEFORE ``_finalize_with_latch``
    acquires the lock (see ``_wait_for_dock_return`` / ``_route_finalize``)
    — so lock contention here costs at most a fraction of a second.
    """
    async with coord._finalize_lock:
        if not coord.live_map.is_active():
            return
        if not coord._live_map_dirty:
            LOGGER.debug("[F5.7.1] _persist_in_progress: live_map not dirty — skipping")
            return

        # The wire-shape payload (session_start_ts, session_ending, track,
        # wifi/battery/charging/state/error samples, charge_at_start,
        # settings_snapshot) is produced by live_map.dump_to_payload().
        # Add the three coordinator-only keys that live on MowerState.
        payload: dict[str, Any] = coord.live_map.dump_to_payload()
        payload["area_mowed_m2"] = coord.data.area_mowed_m2 or 0.0
        payload["map_area_m2"] = 0
        # Rain-delay context is COORDINATOR state (not live_map state), so
        # it is injected here rather than via dump_to_payload(). Persisting
        # it lets _restore_in_progress rehydrate rain_delay_active across a
        # reboot so the finalize gate can veto a premature finalize of a
        # rain-paused session.
        payload["rain_delay_started_at"] = coord.rain_delay_started_at
        try:
            await coord.hass.async_add_executor_job(
                coord.session_archive.write_in_progress, payload
            )
            # Clear the dirty flag only on successful write.
            coord._live_map_dirty = False
            LOGGER.debug(
                "[F5.7.1] _persist_in_progress: wrote in_progress.json "
                "(started_unix=%s, points=%d)",
                coord.live_map.started_unix,
                coord.live_map.total_points(),
            )
        except Exception as ex:
            # Non-fatal — next tick will retry.
            LOGGER.warning("[F5.7.1] _persist_in_progress: write failed: %s", ex)
