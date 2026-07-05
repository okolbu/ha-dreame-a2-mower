"""First-refresh boot orchestration service (layer 4) — refactor-v2 P3.9e.

Moved VERBATIM from ``coordinator/_core.py`` (the ~450-LOC ``_async_update_data``
first-boot body). ``async_first_refresh(coord)`` is the composition root's poll
ORCHESTRATOR: it runs the order-critical restore→init-transports sequence, then
schedules every periodic refresher and seeds the archives. The coordinator keeps
a thin ``_CoreMixin._async_update_data`` delegator.

The body is decomposed here into named seam functions (autopsy #7 seams:
boot-restore, full-refresh orchestration, message restore, freshness/seed
accounting), called by ``async_first_refresh`` in the EXACT original order. The
interleaving is load-bearing and preserved byte-for-byte:

- **P2.2 ConfigEntryNotReady contract (T3-2 / R-5):** the periodic cloud-state
  timer tolerates a failed fetch, but the FIRST ``_refresh_cloud_state_or_raise``
  call raises ``ConfigEntryNotReady`` so HA retries setup rather than forwarding
  platforms with ``cloud_state`` still ``None``.
- **P2.7/P2.9 restore×MQTT race:** ``_restore_in_progress`` runs BEFORE
  ``_init_mqtt`` subscribes, so a retained s2p56 can't clobber the disk-persisted
  legs with the restart timestamp.

``_init_cloud`` / ``_init_mqtt`` STAY on ``_CoreMixin`` (called here via
``coord._init_cloud`` / ``coord._init_mqtt``) — they are directly exercised by
``test_mqtt_auth_recovery`` / the factory / ``test_setup_cloud_blip``. Pinned by
``test_setup_reload_lifecycle`` (real ``__init__`` + real first-refresh wiring),
``test_setup_cloud_blip`` (ConfigEntryNotReady), and
``test_wifi_archive_refresh`` (periodic-archive timer registration).
"""
from __future__ import annotations

import dataclasses
from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from ..const import LOGGER
from ..live_map.finalize import RETRY_INTERVAL_SECONDS
from ..state import MowerState


async def async_first_refresh(coord) -> MowerState:
    """First-refresh path — auth, device discovery, MQTT subscribe.

    Subsequent refreshes are push-driven via the MQTT callback;
    this method only re-runs if the user manually refreshes the
    integration.
    """
    if not hasattr(coord, "_cloud"):
        await _restore_and_init_transports(coord)
        _register_debounce_cancel(coord)
        await _schedule_full_state_and_baseline(coord)
        await _schedule_specialist_refreshers(coord)
        _schedule_session_retry(coord)
        await _load_and_seed_archives(coord)
        _schedule_persist_and_tick(coord)

    return coord.data


async def _restore_and_init_transports(coord) -> None:
    """Order-critical boot-restore + transport init (P2.7/P2.9)."""
    # Restore the state machine from disk before any new signals arrive.
    if coord._state_store is None:
        coord._state_store = Store(
            coord.hass,
            version=1,
            key=f"dreame_a2_mower_state_{coord.entry.entry_id}",
        )
    try:
        await coord.state_machine.load_persisted(coord._state_store)
    except Exception:
        LOGGER.exception(
            "state_machine.load_persisted failed; continuing with initial snapshot"
        )

    await coord._restore_device_messages()

    # Restore the offline last-known read-only snapshot (Task 12a / P6.7) BEFORE
    # the first cloud fetch and before the boot _render_base call below, so
    # read-only entities show last-known values immediately and the restored
    # _active_map_id lets render_base produce the Overview base while offline. A
    # subsequent successful cloud fetch overlays fresh values on top. Guarded
    # inside _restore_last_known so a bad store can never block setup.
    await coord._restore_last_known()

    coord._cloud = await coord.hass.async_add_executor_job(
        coord._init_cloud
    )

    # Restore any in-progress session BEFORE _init_mqtt subscribes
    # to the mower's status topic. If we restored after MQTT, the
    # broker's retained s2p56 message could land between any of the
    # subsequent `await`s, fire begin_session(now_unix), and clobber
    # the disk-persisted legs with the current restart timestamp.
    # See coordinator.py:_restore_in_progress for the full race
    # narrative; pairing this with the `not live_map.is_active()`
    # guard in _on_state_update is the trail-loss-on-restart fix.
    await coord._restore_in_progress()

    # Re-post error-tier persistent notices for faults latched on disk:
    # snapshot.errors is restored above, but _fire_fault_delta won't
    # re-fire them across a restart (no delta vs the restored set), so the
    # banner would be lost. Re-post directly (no spurious fault_detected).
    # Guarded so a notice failure can never abort coordinator setup.
    try:
        coord._repost_active_fault_notices()
    except Exception:
        LOGGER.exception("_repost_active_fault_notices failed during restore")

    await coord.hass.async_add_executor_job(coord._init_mqtt)


def _register_debounce_cancel(coord) -> None:
    """Cancel the _device_sync tripwire debounce handle on unload."""
    # Ensure the debounce handle from _device_sync (set by tripwire
    # callbacks via loop.call_later) doesn't fire into a torn-down
    # coordinator after entry unload.
    def _cancel_debounce_handle() -> None:
        handle = coord._cloud_refresh_debounce_handle
        if handle is not None:
            handle.cancel()
            coord._cloud_refresh_debounce_handle = None

    coord.entry.async_on_unload(_cancel_debounce_handle)


async def _schedule_full_state_and_baseline(coord) -> None:
    """Periodic full-state timer + the P2.2 first-refresh-or-raise + notif baseline."""
    # Periodic cloud-state refresh. The MQTT-driven s6p2 tripwire
    # (see _SETTINGS_TRIPWIRE_SLOTS) catches most app-side saves
    # within ~5 s, but some BT-only settings (obstacleAvoidanceHeight,
    # mowing direction, edge mowing toggles, AI bits) don't push
    # any MQTT signal. The periodic poll is the fallback for those.
    # 2 min gives a tight worst-case latency without hammering the
    # cloud — a full refresh costs ~6 RPCs, so 3 RPC/min average.
    async def _periodic_cloud_state(_now: Any) -> None:
        await coord._refresh_cloud_state()

    coord.entry.async_on_unload(
        async_track_time_interval(
            coord.hass, _periodic_cloud_state, timedelta(minutes=2)
        )
    )
    # First-refresh contract (T3-2 / R-5): unlike the periodic timer
    # above (which tolerates a failed fetch), a failure on THIS call
    # raises ConfigEntryNotReady so HA retries setup instead of
    # forwarding platforms with cloud_state still None. See
    # _cloud_state.py:_refresh_cloud_state_or_raise.
    await coord._refresh_cloud_state_or_raise()

    # Cloud-notification baseline (2026-05-26). One-shot, silent —
    # seeds _notif_seen_ids with whatever the cloud's
    # device-messages/v2 holds RIGHT NOW so historical records don't
    # replay as fresh HA events. Subsequent s2p2 transitions kick off
    # the resolver in _NotificationsMixin. Best-effort: failures
    # (cloud down, auth pending) are swallowed; the resolver will
    # retry the baseline on the first real s2p2 transition.
    try:
        await coord._establish_notification_baseline()
    except Exception:
        LOGGER.debug(
            "[notif] baseline at setup failed; will retry on first s2p2",
            exc_info=True,
        )


async def _schedule_specialist_refreshers(coord) -> None:
    """Register every fast/slow specialist refresher timer + fire the boot ones."""
    # Schedule GPS refresh every 60 seconds via getRecords; also fire
    # one immediately so position_lat/lon are populated at startup.
    # This is the sole mower-position source (the legacy LOCN
    # routed-action path was retired).
    async def _periodic_gps(_now: Any) -> None:
        await coord._refresh_gps()

    coord.entry.async_on_unload(
        async_track_time_interval(
            coord.hass, _periodic_gps, timedelta(seconds=60)
        )
    )
    await coord._refresh_gps()

    # AIOBS live obstacle markers: poll every 2 min, but _refresh_aiobs
    # itself early-returns unless a mow session is active (mow-gated,
    # NOT background). No immediate fire — no session active at boot.
    async def _periodic_aiobs(_now: Any) -> None:
        await coord._refresh_aiobs()

    coord.entry.async_on_unload(
        async_track_time_interval(
            coord.hass, _periodic_aiobs, timedelta(minutes=2)
        )
    )

    # Schedule REMOTE refresh every 6 hours; also fire one immediately
    # so 4G SIM status (left_days, card_id, etc.) is populated at startup.
    async def _periodic_remote(_now: Any) -> None:
        await coord._refresh_remote()

    coord.entry.async_on_unload(
        async_track_time_interval(
            coord.hass, _periodic_remote, timedelta(hours=6)
        )
    )
    await coord._refresh_remote()

    # Schedule message-record refresh every hour; also fire one immediately
    # so service/system unread counts are populated at startup.
    async def _periodic_messages(_now: Any) -> None:
        await coord._refresh_messages()

    coord.entry.async_on_unload(
        async_track_time_interval(
            coord.hass, _periodic_messages, timedelta(hours=1)
        )
    )
    await coord._refresh_messages()

    # Schedule OSS gallery sync every hour; also fire one immediately
    # so album photos and videos are populated at startup (Phase D).
    async def _periodic_oss_gallery(_now: Any) -> None:
        await coord._refresh_oss_gallery()

    coord.entry.async_on_unload(
        async_track_time_interval(
            coord.hass, _periodic_oss_gallery, timedelta(hours=1)
        )
    )
    # Boot: full backfill (page to natural exhaustion — list_oss_media
    # stops at the first short page). The hourly periodic call stays at
    # the default, smaller cap.
    await coord._refresh_oss_gallery(max_pages=400)

    # Schedule DEV refresh every 6 hours; also fire one immediately
    # so the hardware serial / firmware version land at startup
    # (the s1p5 fallback path mostly returns 80001).
    async def _periodic_dev(_now: Any) -> None:
        await coord._refresh_dev()

    coord.entry.async_on_unload(
        async_track_time_interval(
            coord.hass, _periodic_dev, timedelta(hours=6)
        )
    )
    await coord._refresh_dev()

    # Schedule NET refresh every hour; also fire one immediately
    # so wifi_ssid / wifi_ip / wifi_rssi_dbm have values at boot
    # (otherwise the RSSI sensor sits Unknown for ~45 s waiting
    # for the first s1p1 heartbeat).
    async def _periodic_net(_now: Any) -> None:
        await coord._refresh_net()

    coord.entry.async_on_unload(
        async_track_time_interval(
            coord.hass, _periodic_net, timedelta(hours=1)
        )
    )
    await coord._refresh_net()

    # Schedule DOCK refresh every 60s; mower-in-dock is the
    # most useful field and benefits from quicker updates so
    # automations can trigger on dock arrival/departure.
    async def _periodic_dock(_now: Any) -> None:
        await coord._refresh_dock()

    coord.entry.async_on_unload(
        async_track_time_interval(
            coord.hass, _periodic_dock, timedelta(seconds=60)
        )
    )
    await coord._refresh_dock()

    # Seed the WiFi archive picker cache so select.wifi_archive has
    # options immediately (before the user presses any refresh button).
    # Best-effort: failures are non-fatal; the picker stays empty and
    # the user can trigger a refresh manually.
    try:
        await coord.refresh_wifi_archive()
    except Exception as _ex:
        LOGGER.debug("Initial WiFi archive fetch failed: %s", _ex)

    # Re-list BOTH archives every 6h so a long-running integration picks
    # up new wifimap / 3dmap objects without waiting for a restart. WiFi
    # is poll-only (no MQTT push) and LiDAR's s99.20 fires only on an app
    # "View LiDAR Map" tap; the boot backfill covers the down-then-restart
    # case, this timer covers the up-but-idle case. 6h matches _periodic_dev.
    async def _periodic_archive(_now: Any) -> None:
        await coord._periodic_archive_refresh()

    coord.entry.async_on_unload(
        async_track_time_interval(
            coord.hass, _periodic_archive, timedelta(hours=6)
        )
    )


def _schedule_session_retry(coord) -> None:
    """Register the 60s session-finalize retry timer."""
    # Schedule session-finalize retry every RETRY_INTERVAL_SECONDS (60s).
    # Consults finalize.decide() each tick; dispatches AWAIT_OSS_FETCH /
    # FINALIZE_INCOMPLETE / NOOP as appropriate.
    async def _periodic_session(_now: Any) -> None:
        await coord._periodic_session_retry()

    coord.entry.async_on_unload(
        async_track_time_interval(
            coord.hass,
            _periodic_session,
            timedelta(seconds=RETRY_INTERVAL_SECONDS),
        )
    )

    # _poll_slow_properties + its hourly timer were removed 2026-05-26.
    # s6.3 (cloud_connected, rssi) was the 80001 source at :01 and is
    # redundant with heartbeat-fresh wifi_rssi_dbm + MQTT-up; s1.5
    # serial is owned by DEV. See coordinator/_refreshers.py for the
    # full rationale and docs/research/app-api-surface-2026-05-25.md.


async def _load_and_seed_archives(coord) -> None:
    """Load the on-disk archives + seed session-summary / lidar-count fields."""
    # Load obstacle-marker log from disk (non-blocking via executor).
    await coord.hass.async_add_executor_job(coord._obstacle_marker_log.load)

    # Load session archive index from disk (non-blocking via executor).
    await coord.hass.async_add_executor_job(coord.session_archive.load_index)
    archived_count = coord.session_archive.count
    # Re-render the live map now that the archive is available so
    # the last-session obstacle overlay appears immediately. The
    # earlier _refresh_cloud_state passes already
    # rendered _base_png but at that point
    # _load_last_session_obstacles short-circuited on the unloaded
    # archive (returning None without caching, per the guard added
    # in v1.0.11a2). The md5+mode dedup in _render_base means this
    # forces a fresh render only because the obstacle set just changed
    # — but the obstacle cache is keyed separately, so invalidate the
    # base cache first so the dedup doesn't skip the re-render.
    coord._base_png = None
    await coord._render_base()
    if archived_count:
        # v1.0.0a22 / a23: seed total_lawn_area_m2 from the most
        # recent archived session's map_area_m2 so the user sees
        # a value at boot (s2.66 pushes rarely on g2408). Run
        # list_sessions through the executor — it touches
        # in_progress.json synchronously and would otherwise trip
        # HA's blocking-I/O detector and silently raise. (a22
        # called it from the event loop and the seed never fired.)
        seed_lawn = None
        seed_latest_md5: str | None = None
        seed_latest_unix: int | None = None
        seed_latest_area: float | None = None
        seed_latest_duration: int | None = None
        # v1.0.0a42: seed first_mowing_date from the local
        # archive at boot. mowing_count / total_mowing_time_min
        # / total_mowed_area_m2 are now provided by MIHIS via
        # _apply_cloud_state_to_mower_state (Task 17); the
        # lifetime accumulators for those three were dropped.
        # first_mowing_date has no MIHIS equivalent so it
        # remains archive-sourced here.
        #   - first_mowing_date (unix ts)
        first_ts: int | None = None
        try:
            sessions = await coord.hass.async_add_executor_job(
                coord.session_archive.list_sessions
            )
            for s in sorted(sessions, key=lambda x: x.end_ts, reverse=True):
                if seed_lawn is None and getattr(s, "map_area_m2", 0):
                    seed_lawn = float(s.map_area_m2)
                # Pick the most-recent NON in-progress entry to seed
                # Latest session area / duration / time. Without this
                # seed those entities go Unknown after every HA
                # reload until the next session finalizes.
                if (
                    seed_latest_md5 is None
                    and not getattr(s, "still_running", False)
                    and getattr(s, "md5", "")
                ):
                    seed_latest_md5 = str(s.md5)
                    seed_latest_unix = int(s.end_ts)
                    seed_latest_area = float(s.area_mowed_m2 or 0.0)
                    seed_latest_duration = int(s.duration_min or 0)
                # Track first non-in-progress session start for
                # first_mowing_date (no cloud equivalent — keep
                # local-archive sourcing). MIHIS now provides
                # mowing_count / total_mowing_time_min /
                # total_mowed_area_m2 via _apply_cloud_state_to_mower_state
                # at startup, so the lifetime accumulators were
                # dropped in Task 17.
                if not getattr(s, "still_running", False):
                    start_ts = int(getattr(s, "start_ts", 0) or 0)
                    if start_ts > 0 and (first_ts is None or start_ts < first_ts):
                        first_ts = start_ts
        except Exception as _ex:
            LOGGER.warning(
                "Could not seed session-summary fields from archive: %s", _ex
            )
        seed_updates: dict[str, Any] = {
            "archived_session_count": archived_count,
        }
        if seed_lawn is not None:
            seed_updates["total_lawn_area_m2"] = seed_lawn
        if seed_latest_md5 is not None:
            # `seed_latest_md5` is used purely as a "we found a
            # finalized session" sentinel; the md5 itself is no
            # longer surfaced (latest_session_md5 was pruned in
            # F10 — see docs/research/state-machines/orphan-fields.md).
            seed_updates["latest_session_unix_ts"] = seed_latest_unix
            seed_updates["latest_session_area_m2"] = seed_latest_area
            seed_updates["latest_session_duration_min"] = seed_latest_duration
        if first_ts is not None and coord.data.first_mowing_date is None:
            # Field is typed `str | None` and surfaced as a sensor
            # value. Format as a local-tz YYYY-MM-DD so users see a
            # date rather than a raw unix timestamp.
            from datetime import datetime
            try:
                seed_updates["first_mowing_date"] = (
                    datetime.fromtimestamp(first_ts).strftime("%Y-%m-%d")
                )
            except (OSError, OverflowError, ValueError):
                pass
        coord.data = dataclasses.replace(coord.data, **seed_updates)

    # F7.2.2: same pattern for the LiDAR archive.
    # Load index for all existing per-map subdirs so the count
    # sensor populates on first refresh.
    # iterdir() does blocking scandir under the hood — must run in
    # an executor or HA logs a "blocking call inside event loop"
    # warning at every startup.
    def _list_lidar_subdirs() -> list[tuple[int, "Path"]]:
        out: list[tuple[int, "Path"]] = []
        for sub in coord._lidar_archive_root.iterdir():
            if sub.is_dir() and sub.name.isdigit():
                try:
                    out.append((int(sub.name), sub))
                except ValueError:
                    pass
        return out
    _lidar_count = 0
    try:
        _subdirs = await coord.hass.async_add_executor_job(
            _list_lidar_subdirs
        )
    except (OSError, FileNotFoundError):
        _subdirs = []
    for _map_id, _sub in _subdirs:
        try:
            _arch = coord.lidar_archive_for(_map_id)
            await coord.hass.async_add_executor_job(_arch.load_index)
            _lidar_count += _arch.count
        except Exception as _ex:
            LOGGER.debug(
                "[LIDAR] startup index load failed for %s: %s", _sub, _ex
            )
    if _lidar_count:
        coord.data = dataclasses.replace(
            coord.data, archived_lidar_count=_lidar_count
        )

    # _restore_in_progress already ran above (before _init_mqtt).


def _schedule_persist_and_tick(coord) -> None:
    """Register the 30s in-progress persist + 10s state-machine tick timers."""
    # Schedule 30-second debounced persist of the in-progress trail.
    # Only writes when live_map is active AND dirty (new point appended).
    async def _periodic_persist(_now: Any) -> None:
        await coord._persist_in_progress(_now)

    coord.entry.async_on_unload(
        async_track_time_interval(
            coord.hass,
            _periodic_persist,
            timedelta(seconds=30),
        )
    )

    # Schedule state-machine tick every 10 seconds. Handles HB
    # staleness checks, s2p2=71 disambiguation, and debounced persist.
    @callback
    def _state_machine_tick(_now: Any) -> None:
        import time as _time
        now_unix = int(_time.time())
        try:
            coord.state_machine.tick(now_unix=now_unix)
        except Exception:
            LOGGER.exception("state_machine.tick failed")
        # Cold-boot telemetry reconciliation. MQTT properties_changed
        # only fires on change, so a mid-session integration restart
        # never receives the start events. Use continuous telemetry
        # (area_mowed + live_map) to infer the mow session/activity.
        # (Location is NOT reconciled here — s2p1 is its sole authority.)
        try:
            data = coord.data
            coord.state_machine.reconcile_from_telemetry(
                live_map_active=coord.live_map.is_active(),
                area_mowed_m2=getattr(data, "area_mowed_m2", None),
                now_unix=now_unix,
            )
        except Exception:
            LOGGER.exception("state_machine.reconcile_from_telemetry failed")
        # Sync snapshot.charging back to coord.data.charging_status
        # so the charging_status sensor reflects the state machine's
        # inferred state (e.g. battery-rise → charging=True after a
        # reload that missed the explicit s3p2 push).
        try:
            from ..state import ChargingStatus
            snap_charging = coord.state_machine.snapshot().charging
            inferred = (
                ChargingStatus.CHARGING if snap_charging
                else ChargingStatus.NOT_CHARGING
            )
            if coord.data.charging_status != inferred:
                coord.async_set_updated_data(
                    dataclasses.replace(
                        coord.data, charging_status=inferred,
                    )
                )
        except Exception:
            LOGGER.exception("charging_status sync failed")
        # Debounced save: only write if dirty and store is ready.
        if coord.state_machine.is_dirty() and coord._state_store is not None:
            coord.hass.async_create_task(
                coord.state_machine.save_persisted(coord._state_store)
            )

    coord.entry.async_on_unload(
        async_track_time_interval(
            coord.hass,
            _state_machine_tick,
            timedelta(seconds=10),
        )
    )
