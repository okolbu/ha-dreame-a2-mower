"""session mixin — extracted from coordinator.py 2026-05-15.

See spec docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any


from ..const import (
    LOGGER,
)
from ..live_map.finalize import FinalizeAction
from ..domain.session import finalize as _finalize

if TYPE_CHECKING:
    pass  # cross-mixin type imports added as needed


class _SessionMixin:
    """Methods extracted from coordinator.py — see spec for groupings."""

    async def replay_session(self, session_md5: str) -> None:
        """Backwards-compat alias for the Work Log render method.

        Kept so the public dreame_a2_mower.replay_session service (and any
        user automations referencing it) keep working after the rename.
        """
        await self.render_work_log_session(session_md5)

    async def render_work_log_session(self, session_md5: str) -> None:
        """Render an archived session's path into _work_log_png.

        Look up the session by md5 in session_archive, parse its track
        segments via parse_session_summary, then render via
        render_work_log using the archived legs.  Updates
        _work_log_png in-place — the work-log camera entity serves whatever is
        cached, so the replay is immediately visible.

        The replay persists in the work-log camera until the user selects
        the work-log picker's placeholder entry (which sets _work_log_png
        back to None) or the config entry is reloaded.  No periodic refresh
        path touches _work_log_png, so it is not automatically cleared.

        Args:
            session_md5: The md5 string of the archived session.

        Logs a warning and returns early if:
        - The md5 does not match any session in the archive.
        - The raw JSON cannot be loaded from disk.
        - parse_session_summary raises (malformed data).
        - No cloud client is available (not yet initialised).
        """
        import time as _time

        from ..map_decoder import parse_cloud_map
        from ..map_render import render_work_log

        replay_start_unix = _time.monotonic()
        LOGGER.info("[F5.9.1] render_work_log_session: looking up md5=%s", session_md5)

        # --- 1. Find the ArchivedSession entry. The picker passes either:
        #   - the unique filename (post-v1.0.0a53; only key with no
        #     collisions when multiple sessions share an md5), OR
        #   - a 32-char md5 (legacy, also used by the public
        #     dreame_a2_mower.replay_session service). Match either.
        # When multiple entries share an md5 (g2408 reuses md5 across
        # sessions on an unchanged map — see project memo
        # 'g2408 session-archive + target-area quirks'), pick the most
        # recent by end_ts so the user gets the entry they actually
        # see at the top of the picker label list.
        sessions = await self.hass.async_add_executor_job(
            self.session_archive.list_sessions
        )
        by_filename = next(
            (s for s in sessions if s.filename == session_md5), None
        )
        if by_filename is not None:
            entry = by_filename
        else:
            md5_matches = [s for s in sessions if s.md5 == session_md5]
            entry = max(md5_matches, key=lambda s: s.end_ts, default=None)
        if entry is None:
            LOGGER.warning(
                "[F5.9.1] render_work_log_session: no session with key=%s in archive "
                "(%d sessions total)", session_md5, len(sessions)
            )
            return

        # --- 2. Load the raw JSON from disk ---
        raw_dict = await self.hass.async_add_executor_job(
            self.session_archive.load, entry
        )
        if raw_dict is None:
            LOGGER.warning(
                "[F5.9.1] render_work_log_session: failed to load raw JSON for md5=%s "
                "(filename=%s)", session_md5, entry.filename
            )
            return

        # --- 3. Parse the session summary to extract track_segments ---
        from ..protocol import session_summary as _session_summary
        try:
            summary = _session_summary.parse_session_summary(raw_dict)
        except _session_summary.InvalidSessionSummary as ex:
            LOGGER.warning(
                "[F5.9.1] render_work_log_session: parse_session_summary failed for "
                "md5=%s: %s", session_md5, ex
            )
            return

        # --- 3b. Build the picked-session summary dict (T13) ---
        from ..session_card import build_picked_session_summary, format_session_label
        from ..map_render import extract_projection

        try:
            picker_label = format_session_label(entry)
        except Exception:
            picker_label = (
                getattr(entry, "filename", None)
                or getattr(entry, "md5", None)
                or "(unknown)"
            )
        from ..session_card import derive_render_legs
        from ..live_map.state import track_row_to_dict

        track_rows = raw_dict.get("track") or []
        track = [track_row_to_dict(r) for r in track_rows]
        legs_timeline: list[dict] | None = derive_render_legs(track) or None

        # Replay-only overlay: each Obstacle.polygon is already a tuple
        # of (x_m, y_m) pairs (the protocol decoder handled the cm→m
        # conversion). Pass empty list rather than None when the session
        # has none, so the renderer's branch is consistent.
        obstacle_polygons_m: list[list[tuple[float, float]]] = [
            list(o.polygon) for o in summary.obstacles if len(o.polygon) >= 3
        ]

        if not track:
            LOGGER.warning(
                "[F5.9.1] render_work_log_session: key=%s has no track data "
                "(archive pre-dates per-point track)", session_md5
            )
            # Fall through — render_work_log handles empty legs gracefully
            # (produces same output as render_base_map).

        # --- 4. Resolve which map to render against (MM Task 11: cross-map replay).
        # Use the map_id stamped on the archived session so replays from a
        # non-active map render against their own base map, not today's active.
        # Fall back to _active_map_id when map_id is -1 (legacy entries).
        session_map_id = getattr(entry, "map_id", -1)
        target_map_id = (
            session_map_id if session_map_id != -1 else self._active_map_id
        )
        map_data = (
            self.cloud_state.maps_by_id.get(target_map_id)
            if target_map_id is not None
            else None
        )
        if map_data is None and self.cloud_state.maps_by_id:
            # No map for the session's stamped id — fall back to any cached map
            # rather than making the replay entirely black. Log a warning so the
            # user knows the render may be wrong.
            fallback_id = min(self.cloud_state.maps_by_id.keys())
            LOGGER.warning(
                "[F5.9.1] render_work_log_session: map_id=%r not in cache (have: %s); "
                "falling back to map_id=%r",
                target_map_id,
                sorted(self.cloud_state.maps_by_id.keys()),
                fallback_id,
            )
            target_map_id = fallback_id
            map_data = self.cloud_state.maps_by_id[fallback_id]
        if map_data is None:
            # Cache entirely empty — try a live fetch as a last resort (slow).
            if not hasattr(self, "_cloud"):
                LOGGER.warning(
                    "[F5.9.1] render_work_log_session: cloud client not ready yet; "
                    "cannot fetch map for replay"
                )
                return
            cloud_response = await self.hass.async_add_executor_job(
                self._cloud.fetch_map
            )
            if cloud_response is None:
                LOGGER.warning(
                    "[F5.9.1] render_work_log_session: fetch_map returned None; "
                    "cannot render replay for md5=%s", session_md5
                )
                return
            map_data = parse_cloud_map(cloud_response)
            if map_data is None:
                LOGGER.warning(
                    "[F5.9.1] render_work_log_session: parse_cloud_map returned None; "
                    "cannot render replay for md5=%s", session_md5
                )
                return
            # Hydrate the active-map slot so subsequent replays don't re-fetch.
            # cloud_state is the single map store; replace it immutably.
            active_id = self._active_map_id if self._active_map_id is not None else 0
            self.cloud_state = dataclasses.replace(
                self.cloud_state,
                maps_by_id={**self.cloud_state.maps_by_id, active_id: map_data},
            )
            target_map_id = active_id

        # --- 4a. Override with SESSION-TIME no-go zones / spots (Issue 1) ---
        # The replay map's boundary box is stable for a given map, but the
        # exclusion zones / spot areas are user-editable and may have changed
        # since the session ran. Replace the current map's zones with the
        # archived session-time geometry (from the cloud summary's map[]/spot[]
        # layers) so the replay shows what was actually in place during the mow.
        # Trail alignment is unaffected — the boundary box / projection are
        # unchanged; only the overlaid zones differ.
        try:
            from ..map_decoder import apply_session_geometry
            excl_polys = [list(layer.points) for layer in summary.exclusions]
            spot_polys = [list(s.corners) for s in summary.spots]
            if excl_polys or spot_polys:
                map_data = apply_session_geometry(
                    map_data,
                    exclusion_polys_m=excl_polys,
                    spot_polys_m=spot_polys,
                )
        except Exception:
            LOGGER.exception(
                "[F5.9.1] render_work_log_session: session-geometry override "
                "failed for %s — falling back to current-map zones",
                getattr(entry, "filename", "?"),
            )

        # --- 4b. Build the picked-session summary dict (T13) ---
        # Built after map_data is resolved so map_projection can be baked in
        # at construction time (no post-mutation, no transient None state).
        # Per-session photo thumbnails (replay screen). Built separately with its
        # own guard so a signing/IO hiccup degrades to no-photos rather than
        # clearing the whole picked-session summary.
        try:
            session_photos = self.session_photos_manifest(raw_dict)
        except Exception:
            LOGGER.exception(
                "[F5.9.1] render_work_log_session: session_photos_manifest failed "
                "for filename=%s — rendering session without photos",
                getattr(entry, "filename", "?"),
            )
            session_photos = []
        try:
            self._picked_session_summary = build_picked_session_summary(
                raw_dict=raw_dict,
                summary=summary,
                entry=entry,
                picker_label=picker_label,
                map_projection=extract_projection(map_data),
                photos=session_photos,
            )
        except Exception:
            LOGGER.exception(
                "[F5.9.1] render_work_log_session: build_picked_session_summary failed "
                "for filename=%s — clearing picked_session",
                getattr(entry, "filename", "?"),
            )
            self._picked_session_summary = None

        # --- 5. Render and cache ---
        # async_add_executor_job only forwards positional args, so use
        # functools.partial to bake obstacle_polygons_m in as a kwarg.
        from functools import partial

        render_kwargs = {"legs_timeline": legs_timeline} if legs_timeline else {}
        png = await self.hass.async_add_executor_job(
            partial(
                render_work_log,
                map_data,
                obstacle_polygons_m=obstacle_polygons_m,
                trail_width_px=self.data.trail_render_width,
                **render_kwargs,
            )
        )
        self._work_log_png = png

        # Render the no-trail base alongside (for replay card background).
        # The replay card draws the trail itself via animated SVG; if the
        # base image already has the trail painted, the user sees both —
        # the static trail flashes before animation begins. The no-trail
        # variant prevents that.
        # Pass obstacle_polygons_m so the base image includes obstacles
        # at the same z-order as the work-log trail render; the SVG animated trail
        # then draws on top, giving the animated replay visual parity with
        # the static work_log.png (fix for replay card obstacle parity).
        try:
            from ..map_render import render_base_map
            from functools import partial as _partial
            base_png = await self.hass.async_add_executor_job(
                _partial(
                    render_base_map,
                    map_data,
                    lawn_mode="dark",
                    obstacles=obstacle_polygons_m or None,
                )
            )
            self._work_log_base_png = base_png
        except Exception:
            LOGGER.debug(
                "[F5.9.1] render_work_log_session: render_base_map failed for "
                "no-trail base — replay card will fall back to trail variant"
            )
            self._work_log_base_png = None
        elapsed_ms = int((_time.monotonic() - replay_start_unix) * 1000)
        tl_count = len(legs_timeline) if legs_timeline else 0
        total_pts = sum(len(leg["pts"]) for leg in legs_timeline) if legs_timeline else 0
        LOGGER.debug(
            "[F5.9.1] render_work_log_session: rendered work-log PNG (%d bytes) "
            "for key=%s, track_points=%d, legs=%d, total_leg_points=%d, elapsed=%dms",
            len(png) if png else 0,
            session_md5,
            len(track),
            tl_count,
            total_pts,
            elapsed_ms,
        )
        # Tell HA the camera image changed so it triggers an immediate
        # refresh instead of waiting for the next coordinator tick.
        update_listeners = getattr(self, "async_update_listeners", None)
        if callable(update_listeners):
            update_listeners()

    def _resolve_finalize_map_id(self) -> int:
        """Delegates to ``domain.session.finalize.resolve_finalize_map_id`` (P3.9a)."""
        return _finalize.resolve_finalize_map_id(self)

    async def _periodic_session_retry(self) -> None:
        """Delegates to ``domain.session.finalize.periodic_session_retry`` (P3.9a)."""
        await _finalize.periodic_session_retry(self)

    async def _wait_for_dock_return(self, *, timeout_s: int = 300) -> str:
        """Delegates to ``domain.session.finalize.wait_for_dock_return`` (P3.9a).

        Preserves the P2.7 single-flight guard + the P2.8
        ``_pending_finalize_task`` cancellation VERBATIM in the domain module.
        """
        return await _finalize.wait_for_dock_return(self, timeout_s=timeout_s)

    async def _finalize_prior_for_new_command(self, now_unix: int) -> None:
        """Delegates to ``domain.session.finalize.finalize_prior_for_new_command`` (P3.9a)."""
        await _finalize.finalize_prior_for_new_command(self, now_unix)

    async def _finalize_non_mow_immediate(self, now_unix: int, trigger: str) -> None:
        """Delegates to ``domain.session.finalize.finalize_non_mow_immediate`` (P3.9a)."""
        await _finalize.finalize_non_mow_immediate(self, now_unix, trigger)

    def _provisional_session_type(self) -> str:
        """Delegates to ``domain.session.finalize.provisional_session_type`` (P3.9a)."""
        return _finalize.provisional_session_type(self)

    def _provisional_session_is_mow(self) -> bool:
        """Delegates to ``domain.session.finalize.provisional_session_is_mow`` (P3.9a)."""
        return _finalize.provisional_session_is_mow(self)

    def _provisional_session_is_cloud_finalized(self) -> bool:
        """Delegates to ``domain.session.finalize.provisional_session_is_cloud_finalized`` (P3.9a)."""
        return _finalize.provisional_session_is_cloud_finalized(self)

    async def _route_finalize(
        self, now_unix: int, *, dock_wait: bool, trigger: str
    ) -> None:
        """Delegates to ``domain.session.finalize.route_finalize`` (P3.9a)."""
        await _finalize.route_finalize(
            self, now_unix, dock_wait=dock_wait, trigger=trigger
        )

    async def _dispatch_finalize_action(
        self, action: FinalizeAction, now_unix: int
    ) -> None:
        """Delegates to ``domain.session.finalize.dispatch_finalize_action`` (P3.9a)."""
        await _finalize.dispatch_finalize_action(self, action, now_unix)

    async def _finalize_with_latch(
        self, body: Callable[[], Awaitable[None]], *, label: str
    ) -> None:
        """Delegates to ``domain.session.finalize.finalize_with_latch`` (P3.9a)."""
        await _finalize.finalize_with_latch(self, body, label=label)

    async def _merge_recorder_into_payload(
        self, payload: dict[str, Any], *, label: str
    ) -> None:
        """Delegates to ``domain.session.finalize.merge_recorder_into_payload`` (P3.9a)."""
        await _finalize.merge_recorder_into_payload(self, payload, label=label)

    async def _post_archive_reset(
        self,
        *,
        now_unix: int,
        area_mowed_m2: float | None,
        duration_min: int | None,
        completed: bool,
        extra_updates: dict | None = None,
        delete_log_tag: str = "_do_finalize_incomplete",
    ) -> None:
        """Delegates to ``domain.session.finalize.post_archive_reset`` (P3.9a)."""
        await _finalize.post_archive_reset(
            self,
            now_unix=now_unix,
            area_mowed_m2=area_mowed_m2,
            duration_min=duration_min,
            completed=completed,
            extra_updates=extra_updates,
            delete_log_tag=delete_log_tag,
        )

    async def _run_finalize_incomplete(self, now_unix: int) -> None:
        """Delegates to ``domain.session.finalize.run_finalize_incomplete`` (P3.9a).

        The single finalize latch (P3e.4) is preserved VERBATIM in the domain
        module; concurrent same-session entries de-dupe there.
        """
        await _finalize.run_finalize_incomplete(self, now_unix)

    async def _do_run_finalize_incomplete(self, now_unix: int) -> None:
        """Delegates to ``domain.session.finalize.do_run_finalize_incomplete`` (P3.9a).

        Always invoked through _finalize_with_latch (never call directly).
        """
        await _finalize.do_run_finalize_incomplete(self, now_unix)

    def _load_pending_op_from_sidecar(self) -> None:
        """Restore the pending task op persisted before a boot (no live session
        yet). A reboot AFTER begin_session is covered separately by
        in_progress.json's last_task_op."""
        op = self.session_archive.read_pending_op()
        if op is not None:
            self._pending_task_op = op

    def _clear_pending_op(self) -> None:
        """Drop the pending type latches (op + patrol-start) + the op sidecar so
        a finished session's signals cannot seed a later one (no-window valve)."""
        self._pending_task_op = None
        self._pending_saw_patrol_start = False
        self.session_archive.delete_pending_op()

    async def _restore_in_progress(self) -> None:
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
        from ._restore_merge import merge_in_progress_payloads

        LOGGER.info("[F5.7.1] _restore_in_progress: starting (restore-then-merge)")

        # Recover the pending task op latched before the previous shutdown,
        # in case the restart straddled the op-echo -> begin_session window.
        self._load_pending_op_from_sidecar()

        try:
            disk_payload: dict | None = await self.hass.async_add_executor_job(
                self.session_archive.read_in_progress
            )
        except Exception as ex:
            LOGGER.warning("[F5.7.1] _restore_in_progress: read_in_progress raised: %s", ex)
            disk_payload = None

        if disk_payload is None and not self.live_map.is_active():
            LOGGER.debug(
                "[F5.7.1] _restore_in_progress: no disk payload and no live session"
                " — nothing to restore"
            )
            return

        # Snapshot in-memory state as a payload so merge_in_progress_payloads
        # can compare apples-to-apples with the disk payload.
        memory_payload = self.live_map.dump_to_payload()
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
        if merged_start == getattr(self, "_finalizing_start_ts", None):
            LOGGER.info(
                "[F5.7.1] _restore_in_progress: session start_ts=%s was"
                " finalized while the disk read was in flight — discarding"
                " stale in-progress payload",
                merged_start,
            )
            return

        # Hydrate live_map from the merged payload.
        self.live_map.hydrate_from_payload(merged)

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
                    self.live_map.last_telemetry_unix is None
                    or ts > self.live_map.last_telemetry_unix
                ):
                    self.live_map.last_telemetry_unix = ts

        LOGGER.info(
            "[F5.7.1] _restore_in_progress: restore-merged:"
            " started_unix=%s, track_points=%d,"
            " battery_samples=%d, wifi_samples=%d, state_samples=%d",
            self.live_map.started_unix,
            self.live_map.total_points(),
            len(self.live_map.battery_samples),
            len(self.live_map.wifi_samples),
            len(self.live_map.state_samples),
        )

        # Seed state machine: an in_progress.json on disk proves a real
        # mow session was active. Without this, the state machine would
        # stay BETWEEN_SESSIONS until the next start event — which only
        # fires on the NEXT session, not the current one.
        sm = getattr(self, "state_machine", None)
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
                self._rain_delay_started_at = (
                    int(raw_rain) if raw_rain is not None else None
                )
            except (TypeError, ValueError):
                self._rain_delay_started_at = None

        # Seed _prev_task_state to "running" so the finalize gate's
        # session-end detection (prev ∈ {0,4} → new ∈ {2,None}) fires on
        # the next MQTT tick if the mower has actually gone idle while
        # HA was off. Without this, prev stays None at boot and the
        # idle-while-off case wouldn't trigger FINALIZE_INCOMPLETE.
        self._prev_task_state = 0

        # Sync MowerState.
        new_state = dataclasses.replace(
            self.data,
            session_started_unix=merged_start,
            # Single flat segment holding all restored track points — same
            # shape _mqtt_handlers.py emits under the track model.
            session_track_segments=(
                (tuple((p.x_m, p.y_m) for p in self.live_map.track),)
                if self.live_map.track else ()
            ),
        )
        self.async_set_updated_data(new_state)
        LOGGER.info("[F5.7.1] _restore_in_progress: MowerState updated (session restored from disk)")

    async def _persist_in_progress(self, _now: Any = None) -> None:
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
        async with self._finalize_lock:
            if not self.live_map.is_active():
                return
            if not self._live_map_dirty:
                LOGGER.debug("[F5.7.1] _persist_in_progress: live_map not dirty — skipping")
                return

            # The wire-shape payload (session_start_ts, session_ending, track,
            # wifi/battery/charging/state/error samples, charge_at_start,
            # settings_snapshot) is produced by live_map.dump_to_payload().
            # Add the three coordinator-only keys that live on MowerState.
            payload: dict[str, Any] = self.live_map.dump_to_payload()
            payload["area_mowed_m2"] = self.data.area_mowed_m2 or 0.0
            payload["map_area_m2"] = 0
            # Rain-delay context is COORDINATOR state (not live_map state), so
            # it is injected here rather than via dump_to_payload(). Persisting
            # it lets _restore_in_progress rehydrate rain_delay_active across a
            # reboot so the finalize gate can veto a premature finalize of a
            # rain-paused session.
            payload["rain_delay_started_at"] = getattr(
                self, "_rain_delay_started_at", None
            )
            try:
                await self.hass.async_add_executor_job(
                    self.session_archive.write_in_progress, payload
                )
                # Clear the dirty flag only on successful write.
                self._live_map_dirty = False
                LOGGER.debug(
                    "[F5.7.1] _persist_in_progress: wrote in_progress.json "
                    "(started_unix=%s, points=%d)",
                    self.live_map.started_unix,
                    self.live_map.total_points(),
                )
            except Exception as ex:
                # Non-fatal — next tick will retry.
                LOGGER.warning("[F5.7.1] _persist_in_progress: write failed: %s", ex)

