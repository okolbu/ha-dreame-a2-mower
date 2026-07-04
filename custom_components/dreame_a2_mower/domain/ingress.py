"""MQTT ingress funnel (layer 4) — extracted from
``coordinator/_mqtt_handlers.py`` in refactor-v2 P3.7 (autopsy #3 scope #1).

Thin MQTT routing: ``on_mqtt_message`` (topic/method routing), the
``handle_property_push`` per-slot dispatch skeleton with its paho→loop hop,
``handle_event_occured`` (OSS object-name capture), and ``apply_mapl`` (active-map
detection).

**P2.9 paho-thread purity is preserved EXACTLY.** ``handle_property_push`` does a
PURE decode on the paho thread and captures only ``(siid, piid, value, now)``; the
``coord.data`` base-read, the ``apply_property_to_state`` call, every state-machine
mutation, and the broadcast all run loop-side inside the ``_deferred`` closure
(R-39/T3-7). The three nested closures (`_record_novel`, `_apply_sm_mutations`,
`_apply`) and their FIFO sequencing via ``call_soon_threadsafe`` are moved
VERBATIM — ``self`` became ``coord`` and nothing else changed.
``tests/coordinator/test_sm_thread_safety.py`` +
``tests/coordinator/test_mqtt_auth_recovery.py`` pin this behaviour; the corpus
IDENTICAL gate pins the decode.

The coordinator keeps thin delegating methods for its public/test surface
(``coord._on_mqtt_message``, ``coord.handle_property_push``,
``coord._handle_event_occured``, ``coord._apply_mapl``).
"""
from __future__ import annotations

import dataclasses
from typing import Any

from ..const import (
    LOG_NOVEL_PROPERTY,
    LOG_NOVEL_VALUE,
    LOGGER,
)
from ..protocol.property_mapping import PROPERTY_MAPPING
from ..mower.state import MowerState
from ..protocol import heartbeat as _heartbeat
from ..state.apply import (
    _BLOB_SLOTS,
    _INVENTORY,
    _SETTINGS_TRIPWIRE_SLOTS,
    _SUPPRESSED_SLOTS,
    _coerce_blob,
    _project_north_east,
    apply_property_to_state,
)
from .session.signals import capture_session_type_signals


def apply_mapl(coord, mapl: Any) -> None:
    """Update _active_map_id from a MAPL response.

    MAPL is a list of rows, each row is `[map_id, is_active, ?, ?, ?]`.
    Sets `_active_map_id` to the row whose col 1 == 1. If no row
    matches (transient), keep the previous value. Bad payloads are
    ignored.

    When `_active_map_id` actually changes, fires `async_update_listeners`
    so camera + select entities push their new state to the frontend
    without waiting for the next full coordinator broadcast.
    """
    if not isinstance(mapl, list):
        return
    prev_active = coord._active_map_id
    for row in mapl:
        if not isinstance(row, list) or len(row) < 2:
            continue
        try:
            if int(row[1]) == 1:
                new_active = int(row[0])
                if new_active != prev_active:
                    coord._active_map_id = new_active
                    # Re-apply cloud_state → MowerState so SETTINGS-keyed
                    # fields (settings_mowing_height, settings_edge_mowing_*,
                    # settings_obstacle_avoidance_*, settings_obstacle_avoidance_ai)
                    # populate now that we know which map is active. On cold
                    # start _refresh_cloud_state runs first and sees
                    # _active_map_id=None, so without this re-apply the
                    # SETTINGS-driven entities stay unavailable until the
                    # next 2-min refresh.
                    if getattr(coord, "cloud_state", None) is not None:
                        coord._apply_cloud_state_to_mower_state()
                    # Re-render the live-map base PNG so DreameA2MapCamera
                    # serves the new active map immediately. Without
                    # this, _base_png stays at the previous map's
                    # render until the next 2-min cloud refresh — observed
                    # as ~1-minute lag between app-side map flip and the
                    # dashboard live-map card updating (2026-05-14). The
                    # md5 in the dedup key differs across maps, so this
                    # always re-renders on a genuine map switch.
                    hass = getattr(coord, "hass", None)
                    if hass is not None:
                        coord._schedule_render_base()
                    # Fire listeners so camera + select push state to the
                    # frontend without waiting for the next coordinator
                    # broadcast.
                    update_listeners = getattr(coord, "async_update_listeners", None)
                    if callable(update_listeners):
                        update_listeners()
                coord._sync_map_subdevices()
                return
        except (TypeError, ValueError):
            continue
    # No row matched; keep previous _active_map_id (do nothing).
    coord._sync_map_subdevices()


def on_mqtt_message(coord, topic: str, payload: dict[str, Any]) -> None:
    """Dispatcher for inbound MQTT messages.

    Handles two method types:
    - ``properties_changed`` — individual property pushes (siid/piid/value).
    - ``event_occured`` — event notifications (siid/eiid + arguments list).
      siid=4 eiid=1 carries the OSS object name in arguments[piid=9].
    """
    method = payload.get("method")
    if method == "properties_changed":
        params = payload.get("params") or []
        for p in params:
            if "siid" in p and "piid" in p:
                coord.handle_property_push(
                    siid=int(p["siid"]),
                    piid=int(p["piid"]),
                    value=p.get("value"),
                )
                import time as _time
                _now_unix = int(_time.time())
                _sm_siid = int(p["siid"])
                _sm_piid = int(p["piid"])
                _sm_value = p.get("value")
                if (_sm_siid, _sm_piid) == (1, 1):
                    # s1p1 heartbeat — PURE decode on the paho thread; the
                    # state_machine.handle_heartbeat mutation + the live_map
                    # wifi-sample append both move onto the event loop (P1.3).
                    _hb = None
                    try:
                        _blob = _coerce_blob(_sm_value, "s1.1")
                        if _blob is not None:
                            _hb = _heartbeat.decode_s1p1(_blob)
                    except Exception:
                        LOGGER.exception("decode_s1p1 failed")

                    if _hb is not None:
                        def _apply_heartbeat(_hb=_hb, _now_unix=_now_unix) -> None:
                            try:
                                coord.state_machine.handle_heartbeat(
                                    hb=_hb, now_unix=_now_unix
                                )
                                # WiFi fingerprint capture (v1.0.10a6+):
                                # pair the heartbeat's wifi_rssi_dbm with
                                # the most recent live position so the
                                # heatmap→map_id matcher has per-session
                                # (x_m, y_m, rssi_dbm, ts) tuples to score
                                # against incoming heatmaps. Gate on
                                # is_active() so we don't pollute the
                                # next session with idle-time samples.
                                try:
                                    _rssi = getattr(_hb, "wifi_rssi_dbm", None)
                                    _px = coord.data.position_x_m
                                    _py = coord.data.position_y_m
                                    if (
                                        _rssi is not None
                                        and _px is not None
                                        and _py is not None
                                        and coord.live_map.is_active()
                                    ):
                                        if coord.live_map.append_wifi_sample(
                                            _px, _py, _rssi, _now_unix
                                        ):
                                            coord._live_map_dirty = True
                                except Exception:
                                    LOGGER.exception("append_wifi_sample failed")
                            except Exception:
                                LOGGER.exception(
                                    "state_machine.handle_heartbeat failed"
                                )

                        coord.hass.loop.call_soon_threadsafe(_apply_heartbeat)
                else:
                    # The whole prev→mutate→new→fire→render→task-op sequence
                    # MUST move onto the loop AS ONE UNIT (P1.3 TRAP #2) — it
                    # mutates state_machine and reads its snapshot deltas, so
                    # it can never straddle the hop. Scheduled AFTER
                    # handle_property_push's own hop, so FIFO preserves the
                    # per-property application order across the message loop.
                    def _apply_dispatch(
                        _sm_siid=_sm_siid,
                        _sm_piid=_sm_piid,
                        _sm_value=_sm_value,
                        _now_unix=_now_unix,
                    ) -> None:
                        # Capture the state-machine activity before/after the
                        # property is applied so ANY activity transition can
                        # trigger a base re-render below. This is the single
                        # general render trigger (rehaul): it subsumes the old
                        # s2p1→REPOSITIONING-specific trigger. The background
                        # mode is a pure function of the snapshot, so the
                        # stripes→green flip lands within one tick of the state
                        # machine entering an active activity — ~41s before the
                        # first s1p4 MOVE, fixing the stripe-lag bug.
                        try:
                            _prev_activity = (
                                coord.state_machine.snapshot().current_activity
                            )
                        except Exception:
                            _prev_activity = None
                        try:
                            _prev_errors = (
                                coord.state_machine.snapshot().errors
                            )
                        except Exception:
                            _prev_errors = frozenset()
                        try:
                            coord.state_machine.handle_mqtt_property(
                                siid=_sm_siid,
                                piid=_sm_piid,
                                value=_sm_value,
                                now_unix=_now_unix,
                            )
                        except Exception:
                            LOGGER.exception("state_machine.handle_mqtt_property failed")
                        try:
                            _new_activity = (
                                coord.state_machine.snapshot().current_activity
                            )
                        except Exception:
                            _new_activity = None
                        try:
                            _new_errors = (
                                coord.state_machine.snapshot().errors
                            )
                        except Exception:
                            _new_errors = frozenset()
                        if _new_errors != _prev_errors:
                            coord._fire_fault_delta(
                                _prev_errors, _new_errors, now_unix=_now_unix
                            )
                        if _new_activity != _prev_activity:
                            LOGGER.debug(
                                "[MAP] activity transition %s → %s — render_base",
                                _prev_activity, _new_activity,
                            )
                            coord._schedule_render_base()
                        if (_sm_siid, _sm_piid) == (2, 50):
                            # Latch the op UNGATED — a patrol/mow commanded from
                            # the dock echoes its op ~40s before begin_session
                            # exists to hold it. _handle_task_op_echo persists it
                            # and (if a session is already active) sets
                            # last_task_op immediately. Already on the loop here.
                            coord._handle_task_op_echo(_sm_value)

                    coord.hass.loop.call_soon_threadsafe(_apply_dispatch)
    elif method == "event_occured":
        # F5.6.1: capture OSS object name from siid=4 eiid=1
        params = payload.get("params") or {}
        siid = int(params.get("siid", 0))
        eiid = int(params.get("eiid", 0))
        if siid == 4 and eiid == 1:
            arguments = params.get("arguments") or []
            coord.hass.loop.call_soon_threadsafe(
                lambda args=arguments: coord.hass.loop.create_task(
                    coord._handle_event_occured(args)
                )
            )


async def handle_event_occured(coord, arguments: list[dict[str, Any]]) -> None:
    """Handle an event_occured (siid=4 eiid=1) message.

    Extracts the OSS object name from ``arguments[piid=9]`` and stores it
    as ``pending_session_object_name`` + ``pending_session_first_event_unix``
    on MowerState so the periodic retry loop can pick it up.

    Called on the event loop (via call_soon_threadsafe) — safe to call
    async_set_updated_data directly.
    """
    import time as _time
    object_name: str | None = None
    for arg in arguments:
        if int(arg.get("piid", -1)) == 9:
            object_name = str(arg.get("value", "")) or None
            break

    if not object_name:
        LOGGER.warning(
            "[F5.6.1] event_occured (siid=4 eiid=1): no piid=9 argument "
            "or empty value — arguments=%r",
            arguments,
        )
        return

    LOGGER.info(
        "[F5.6.1] event_occured: OSS object_name=%r — scheduling fetch",
        object_name,
    )
    now_unix = int(_time.time())
    new_state = dataclasses.replace(
        coord.data,
        pending_session_object_name=object_name,
        pending_session_first_event_unix=now_unix,
        pending_session_last_attempt_unix=None,
        pending_session_attempt_count=0,
    )
    coord.async_set_updated_data(new_state)


def handle_property_push(coord, siid: int, piid: int, value: Any) -> None:
    """Apply a property push and notify entities. Called from the
    MQTT message callback (which runs on paho's background thread).

    Per spec §3 async-first commitment: state updates must reach
    HA's coordinator on the event loop. We hop the thread boundary
    via call_soon_threadsafe; the actual async_set_updated_data
    call lands on the event loop's next iteration.

    The paho thread captures only ``(siid, piid, value, now)`` —
    the ``coord.data`` base-read, the pure decode, and every mutation
    run inside the loop-side hop (R-39/T3-7: a paho-thread base-read
    raced loop-side ``coord.data`` replacements and reverted them).
    """
    import time as _time
    now = int(_time.time())

    # Novelty checks BEFORE the early-return: unmapped slots produce
    # `new_state == coord.data` (no field touched), so they must be
    # logged here or they'd be silently dropped. Blob-payload slots
    # (s1.1, s1.4, s2.51) are dispatched in apply_property_to_state
    # via dedicated handlers; treat them as known to avoid the
    # per-tick novelty noise their varying payloads would generate.
    key = (int(siid), int(piid))
    if key in _SETTINGS_TRIPWIRE_SLOTS:
        # Firmware-saved-settings tripwire (s6p2 etc.) — schedule a
        # debounced cloud refresh so app/BT-side edits surface in HA
        # within seconds instead of waiting for the next 2-min poll.
        # Continues into the normal mapping path below: tripwire
        # slots also carry decoded state (e.g. s6p2 frame elements).
        coord.hass.loop.call_soon_threadsafe(
            lambda k=key: coord._schedule_cloud_refresh(
                reason=f"s{k[0]}p{k[1]}"
            ),
        )
    # Telemetry-stream capture (v1.0.12a2+). Accumulate the four
    # scalar streams that aren't otherwise persisted alongside the
    # session trail (battery_level, charging_status, mower-state,
    # error_code) so the finalized archive can reconstruct the
    # SoC + state curves without correlating against HA's entity
    # history. Capture must run BEFORE the early-return paths
    # below: s2p1 (state) is a state-machine no-op in
    # apply_property_to_state so it never reaches the _apply hop,
    # and same-value re-emits on s3p1/s3p2/s2p2 dedup against
    # coord.data and likewise short-circuit. Hop to the loop because
    # LiveMapState lists must not be mutated from paho's bg thread.
    if key in {(3, 1), (3, 2), (2, 1), (2, 2)}:
        coord.hass.loop.call_soon_threadsafe(
            lambda k=key, v=value, t=now: coord._capture_telemetry_sample(k, v, t),
        )
    if key in _SUPPRESSED_SLOTS:
        # s1p50 is the firmware's "something changed" empty-ping. For
        # multi-map, every map-swap fires it (confirmed 2026-05-07).
        # Treat it as a MAPL-repoll trigger so active-map detection has
        # sub-second latency instead of waiting for the next 2-min
        # cloud refresh. Other s1p50 cases (zone-edits, maintenance saves)
        # benefit from the cheap re-poll too — MAPL is a ~100 ms RPC.
        if key == (1, 50):
            coord.hass.loop.call_soon_threadsafe(
                lambda: coord.hass.async_create_task(coord._refresh_mapl())
            )
        return  # echo of our own command; nothing to record

    # Run order is assembled in _deferred() at the bottom of this method:
    # _record_novel -> base-read + decode -> (early-return on unchanged
    # state) -> _apply_sm_mutations -> _apply. The three nested defs below
    # are declared here but sequenced there — ALL of it on the event loop.
    def _record_novel() -> None:
        # Thread-safety (P1.3): novelty recording MUTATES novel_registry, so
        # it must run on the event loop, NOT on paho's bg thread. It also
        # must run on EVERY push — including the unchanged-state early-return
        # case below — because unmapped/no-op slots (the common case) produce
        # new_state == coord.data, and dropping their novelty here would
        # silently lose first-observation tracking. Hence it is the FIRST
        # thing the deferred hop does, before the equality short-circuit.
        if key in _BLOB_SLOTS:
            pass  # handled by dedicated blob applier; suppress novelty
        elif key in PROPERTY_MAPPING:
            if coord.novel_registry.record_value(siid, piid, value, now):
                # First-time value for an already-mapped slot is informational
                # (e.g. s1p53 bluetooth_connected toggling True for the first time
                # after install); the slot is recognised so there is nothing
                # for the user to action. Keep [NOVEL/property] at WARN since
                # that one signals a protocol gap.
                LOGGER.info(
                    "%s siid=%s piid=%s value=%r — first-time value for known slot",
                    LOG_NOVEL_VALUE, siid, piid, value,
                )
        elif key in _INVENTORY.apk_known_never_seen:
            # The slot is in the inventory as APK-KNOWN but seen_on_wire:false.
            # Now that we've observed it, prompt the contributor to upgrade the
            # inventory row to seen_on_wire:true. Logged at INFO since the slot
            # is "known" in the data sense — the contributor action is to
            # update the row, not to file a new protocol gap.
            if coord.novel_registry.saw_property(siid, piid):
                LOGGER.info(
                    "[PROTOCOL_NOVEL/apk-confirmed] siid=%s piid=%s value=%r "
                    "— APK-known slot now observed on wire; consider upgrading "
                    "inventory row to seen_on_wire:true",
                    siid, piid, value,
                )
        else:
            if coord.novel_registry.record_property(siid, piid, now):
                LOGGER.warning(
                    "%s siid=%s piid=%s value=%r — unmapped slot, please file a protocol gap",
                    LOG_NOVEL_PROPERTY, siid, piid, value,
                )

        # Catalog-miss check runs regardless of whether the slot is mapped or
        # apk-known: any property with a value_catalog in the inventory should
        # have its observed values cross-checked. Misses log at WARNING since
        # they likely indicate a protocol gap (firmware emitting a value the
        # catalog hasn't enumerated yet).
        catalog = _INVENTORY.value_catalogs.get(key)
        if catalog is not None and value not in catalog:
            if coord.novel_registry.record_value(siid, piid, value, now):
                LOGGER.warning(
                    "[NOVEL/value/catalog-miss] siid=%s piid=%s value=%r "
                    "— not in catalog %r; please file a protocol gap",
                    siid, piid, value, sorted(catalog.keys()),
                )

    # NOTE (R-39/T3-7): the paho thread does NO decode at all. It captures
    # only (siid, piid, value, now); the coord.data base-read + the pure
    # apply_property_to_state call run inside _deferred, ON THE LOOP.
    # apply_property_to_state itself is side-effect-free, but its BASE
    # argument is loop-owned: reading coord.data here (paho thread) opened
    # a stale-base window — any loop-side coord.data replacement
    # (optimistic-write broadcast, cloud-refresh apply, an EARLIER queued
    # push's own hop) landing before this push's hop was clobbered by the
    # full-replace broadcast of the stale-base decode.

    def _apply_sm_mutations(new_state: MowerState) -> None:
        # Thread-safety (P1.3): every state_machine mutation below moves onto
        # the event loop. The paho thread only decoded new_state (pure); these
        # SM writes — and the snapshot.errors delta read + _fire_fault_delta —
        # run here as one unit so they never race the loop's 10s tick.
        #
        # SM-mutator (R6): persist position across reboot. s1p4 is the only
        # slot that writes position_x_m/position_y_m on MowerState; route
        # those writes through the state machine so the StateSnapshot
        # cold-boot restore picks up the last-known pose.
        # Position-fix P3: project dock-frame (x_m, y_m) into compass-frame
        # (north_m, east_m) using the user-set station_bearing_deg option.
        # When the option is unset, _project_north_east returns (None, None)
        # and handle_position no-ops those fields, leaving the N/E sensors
        # Unknown.
        if (int(siid), int(piid)) == (1, 4):
            sm = getattr(coord, "state_machine", None)
            if sm is not None and new_state.position_x_m is not None:
                x_m = new_state.position_x_m
                y_m = new_state.position_y_m
                north_m, east_m = _project_north_east(
                    x_m, y_m, coord.station_bearing_deg,
                )
                try:
                    _prev_errors = sm.snapshot().errors
                except Exception:
                    _prev_errors = frozenset()
                try:
                    sm.handle_position(
                        x_m=x_m,
                        y_m=y_m,
                        north_m=north_m,
                        east_m=east_m,
                        heading_deg=new_state.position_heading_deg,
                        now_unix=now,
                    )
                except Exception:
                    LOGGER.exception("state_machine.handle_position failed")
                try:
                    _new_errors = sm.snapshot().errors
                except Exception:
                    _new_errors = frozenset()
                if _new_errors != _prev_errors:
                    coord._fire_fault_delta(_prev_errors, _new_errors, now_unix=now)

        # Persist mowing_phase / task_state_code / slam_task_label in the
        # snapshot so they survive HA restart (per user feedback: showing
        # last-known is more useful than Unknown). Read whichever fields
        # this slot's apply_property_to_state may have updated.
        if (int(siid), int(piid)) in {(1, 4), (2, 56), (2, 65)}:
            sm = getattr(coord, "state_machine", None)
            if sm is not None:
                try:
                    sm.handle_misc_persisted(
                        mowing_phase=new_state.mowing_phase,
                        task_state_code=new_state.task_state_code,
                        slam_task_label=new_state.slam_task_label,
                        now_unix=now,
                    )
                except Exception:
                    LOGGER.exception("state_machine.handle_misc_persisted failed")

        # Per-map shadow update: s6.2 carries the active map's full PRE
        # profile at the moment of save in the Dreame app. Tag with
        # current active map_id (from MAPL poll cache). See
        # `docs/research/g2408-protocol.md` § s6.2 for the per-map model.
        if (int(siid), int(piid)) == (6, 2):
            sm = getattr(coord, "state_machine", None)
            active_map = coord.active_map_id
            if sm is not None and active_map is not None:
                try:
                    sm.handle_pre_shadow_update(
                        map_id=int(active_map),
                        mowing_height_mm=new_state.pre_mowing_height_mm,
                        mowing_efficiency=new_state.pre_mowing_efficiency,
                        edgemaster=new_state.pre_edgemaster,
                        now_unix=now,
                    )
                except Exception:
                    LOGGER.exception("state_machine.handle_pre_shadow_update failed")

    def _apply(new_state: MowerState) -> None:
        # _on_state_update mutates live_map (legs, started_unix, etc.) and
        # updates _prev_task_state / _live_map_dirty.  It must run on the
        # event loop so those shared objects are never mutated from paho's
        # background thread while the loop is iterating them.
        #
        # (A) TO-POINT ARRIVAL: s2p2=75 (arrived_at_maintenance_point).
        # op=109 (cruise-to-point) sessions complete in ~40s and emit
        # s2p2=75 at arrival. The s2p56 0→2 edge is consumed by
        # _prev_task_state before the 60s retry fires (root cause of the
        # stuck-session bug). Finalize here immediately — no dock-wait
        # needed for non-mow sessions; the return drive should NOT be
        # captured as part of the to-point session.
        # GUARD HARD: only fires for non-cloud-finalized sessions
        # (mow/patrol always skip this path).
        if key == (2, 2) and value == 75:
            if (
                coord.live_map.is_active()
                and not coord._provisional_session_is_cloud_finalized()
            ):
                LOGGER.debug(
                    "[F5] s2p2=75 (arrived_at_maintenance_point) with non-mow "
                    "session active — scheduling immediate finalize"
                )
                coord.hass.async_create_task(
                    coord._finalize_non_mow_immediate(now, "s2p2=75")
                )
                # Fall through to _on_state_update so the AT_POINT state
                # is applied (SM already handled it) and the state is
                # broadcast to entities.

        # (c) NEW-TASK-COMMAND BOUNDARY. The firmware drops s2p56 `status`
        # to `[]` between two DISTINCT task commands; a queued multi-target
        # run keeps ONE non-empty list across its per-target arrivals. So a
        # `[] → non-empty` transition while a prior session is STILL active
        # (with captured points) means the user started a new run without
        # docking — finalize the prior session FIRST, then let the next push
        # begin the new one. We defer this tick's _on_state_update until the
        # split completes (it runs in an async task because finalize does
        # executor I/O); the next s1p4/s2p56 push re-begins cleanly.
        if key == (2, 56):
            status = value.get("status") if isinstance(value, dict) else None
            now_empty = not status  # [] / None
            if (
                coord._prev_s2p56_empty is True
                and not now_empty
                and coord.live_map.is_active()
                and coord.live_map.total_points() > 0
                and not coord._provisional_session_is_cloud_finalized()
            ):
                coord._prev_s2p56_empty = now_empty
                LOGGER.debug(
                    "[F5] new-command boundary (s2p56 []→active) while a "
                    "prior session is still open — finalizing prior session "
                    "before starting the new one"
                )
                coord.hass.async_create_task(
                    coord._finalize_prior_for_new_command(now)
                )
                return
            coord._prev_s2p56_empty = now_empty
            if coord.live_map.is_active():
                capture_session_type_signals(
                    coord.live_map,
                    s2p56_status=status,
                    s2p50_op=None,
                    area_m2=None,
                )
        hopped = coord._on_state_update(new_state, now)
        # Surface the persistent_notification banner that mirrors the
        # Dreame app's modal popup. Fires on emergency_stop transition
        # (byte[3] bit 7), the load-bearing PIN-required latch.
        coord._handle_emergency_stop_transition(
            coord.data.emergency_stop, hopped.emergency_stop,
        )
        coord.async_set_updated_data(hopped)
        # Command-time render trigger: s2p50 task-start echo.
        # After the op echo the state machine has already set location=ON_LAWN
        # and the correct activity. Without a render trigger the camera entity
        # keeps showing the idle stripe preview (pre-start) until s1p4 position
        # telemetry resumes ~45s later. Fire _render_base immediately so
        # the stripe preview is replaced with the trail-mode (dark-green base)
        # as soon as the command is acknowledged.
        # Scope: task-start ops only (100-103 mow, 108 patrol, 109 cruise).
        # NOTE: for the ops that change current_activity (mow/cruise) this is
        # largely REDUNDANT with the general activity-transition trigger in
        # `_on_mqtt_message` — the (mode, md5) dedup in _render_base makes the
        # second call a cheap no-op. It is retained as a command-time-latency
        # hedge (renders at ack rather than at the next activity push) and to
        # cover op=108 patrol, which does not flip activity.
        if key == (2, 50):
            _s2p50_op: int | None = None
            if isinstance(value, dict):
                _s2p50_d = value.get("d")
                if isinstance(_s2p50_d, dict):
                    _raw_op = _s2p50_d.get("o")
                    if isinstance(_raw_op, int):
                        _s2p50_op = _raw_op
            _TASK_START_OPS_RENDER = frozenset({100, 101, 102, 103, 108, 109})
            if _s2p50_op in _TASK_START_OPS_RENDER:
                _s2p50_status = bool(
                    _s2p50_d.get("status", True)  # type: ignore[union-attr]
                    if isinstance(value.get("d"), dict)  # type: ignore[union-attr]
                    else True
                )
                if _s2p50_status:
                    LOGGER.debug(
                        "[MAP] s2p50 task-start echo op=%d — triggering render "
                        "to replace idle stripe preview at command-time",
                        _s2p50_op,
                    )
                    coord._schedule_render_base()
        # NOTE: render triggers no longer live in this `_apply()` closure
        # for activity transitions / between-session movement. Activity
        # changes fire _render_base from `_on_mqtt_message` (right after
        # handle_mqtt_property, where the snapshot reflects the transition).
        # Between-session mower movement no longer needs a server render at
        # all: the icon + trail move CLIENT-side from the published position
        # stream (see _publish_live_point), so the return-to-dock drive
        # advances the icon without a PIL re-render.

    def _deferred() -> None:
        # Single loop hop (P1.3): runs ALL mutations for this push, in the
        # same order as the old paho-thread code, on the event loop.
        #   1. novel recording (must run on EVERY push, even no-op-state)
        #   2. base-read + pure decode (R-39/T3-7: the base MUST be read
        #      HERE, on the loop, so it always includes every loop-side
        #      update — cloud-refresh applies, optimistic-write
        #      broadcasts, and earlier queued pushes' own hops)
        #   3. unchanged-state short-circuit (no broadcast) — but novelty
        #      above already happened, fixing TRAP #1
        #   4. state-machine mutations (position / misc / pre-shadow)
        #   5. the _apply body (_on_state_update + broadcast + render)
        #
        # Ordering: call_soon_threadsafe preserves FIFO for callbacks
        # scheduled from the same thread, so same-thread sequential
        # pushes still decode+apply in arrival order — each against the
        # then-current coord.data, never a shared stale snapshot.
        _record_novel()
        new_state = apply_property_to_state(coord.data, siid, piid, value)
        if new_state == coord.data:
            return
        _apply_sm_mutations(new_state)
        _apply(new_state)

    # Zero-arg closure so the run-inline test mock `lambda fn: fn()` works.
    coord.hass.loop.call_soon_threadsafe(_deferred)
