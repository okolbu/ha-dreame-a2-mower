"""core mixin — extracted from coordinator.py 2026-05-15.

See spec docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md.
"""
from __future__ import annotations

import asyncio
import dataclasses
import time
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from ..archive.lidar import LidarArchive
from ..archive.obstacle_markers_log import ObstacleMarkerLog
from ..protocol.obstacle_markers import ObstacleMarker
from ..archive.photos import PhotoArchive
from ..archive.session import SessionArchive
from ..archive.videos import VideoArchive
from ..wifi_archive_store import WifiArchiveEntry, WifiArchiveStore
from ..cloud_client import DreameA2CloudClient
from ..const import (
    CONF_COUNTRY,
    CONF_LIDAR_ARCHIVE_KEEP,
    CONF_LIDAR_ARCHIVE_MAX_MB,
    CONF_MESSAGES_KEEP,
    CONF_PHOTO_ARCHIVE_KEEP,
    CONF_PHOTO_ARCHIVE_MAX_MB,
    CONF_PASSWORD,
    CONF_SESSION_ARCHIVE_KEEP,
    CONF_STATION_BEARING_DEG,
    CONF_USERNAME,
    CONF_VIDEO_ARCHIVE_KEEP,
    CONF_VIDEO_ARCHIVE_MAX_MB,
    CONF_WIFI_ARCHIVE_KEEP,
    DEFAULT_LIDAR_ARCHIVE_KEEP,
    DEFAULT_LIDAR_ARCHIVE_MAX_MB,
    DEFAULT_MESSAGES_KEEP,
    DEFAULT_PHOTO_ARCHIVE_KEEP,
    DEFAULT_PHOTO_ARCHIVE_MAX_MB,
    DEFAULT_PHOTO_ARCHIVE_PER_CATEGORY,
    DEFAULT_SESSION_ARCHIVE_KEEP,
    DEFAULT_VIDEO_ARCHIVE_KEEP,
    DEFAULT_VIDEO_ARCHIVE_MAX_MB,
    DEFAULT_WIFI_ARCHIVE_KEEP,
    DOMAIN,
    LOGGER,
)
from ..live_map.finalize import RETRY_INTERVAL_SECONDS
from ..live_map.state import LiveMapState
from ..mower.state import MowerState
from ..mower.state_machine import MowerStateMachine
from ..mqtt_client import DreameA2MqttClient
from ..observability import FreshnessTracker, NovelObservationRegistry

if TYPE_CHECKING:
    pass  # cross-mixin type imports added as needed


class _CoreMixin:
    """Methods extracted from coordinator.py — see spec for groupings."""

    # Consecutive full-state cloud-poll failures before cloud-sourced entities
    # go unavailable (Phase 1.1). 2 cycles ≈ 4-6 min — long enough to ride out a
    # transient blip, short enough to surface a real cloud outage promptly.
    _CLOUD_UNAVAIL_THRESHOLD = 2

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        wifi_index: "list[WifiArchiveEntry] | None" = None,
    ) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=None,  # push-based; we don't poll
        )
        self.entry = entry
        self._username = entry.data[CONF_USERNAME]
        self._password = entry.data[CONF_PASSWORD]
        self._country = entry.data[CONF_COUNTRY]

        # Initialize empty MowerState — fields fill in as MQTT pushes arrive
        self.data = MowerState()

        # Live session state machine (F5.3.1).
        self.live_map = LiveMapState()
        self._prev_task_state: int | None = None
        # True once we've seen a real task_state_code value from MQTT
        # since boot. Used by the finalize gate to distinguish a
        # genuine "task_state observed as idle/complete" from
        # "MowerState's default None because no MQTT push has landed
        # yet" — without this, a restart inside an MQTT-quiet window
        # combined with `_restore_in_progress`'s prev=0 seed would
        # falsely fire FINALIZE_INCOMPLETE on a still-active session
        # (see 2026-05-15 rain-stop incident).
        self._real_task_state_observed: bool = False
        # Event-entity refs populated by event.py's async_setup_entry.
        # Coordinator's _fire_lifecycle dispatcher calls these to surface
        # transitions to HA. None until the platform setup completes;
        # _fire_lifecycle race-skips with a DEBUG log when not yet wired.
        self._lifecycle_event: Any = None
        self._notification_event: Any = None
        # Tracks the previous mower_in_dock value for rising/falling edge
        # detection of dock_arrived / dock_departed events. None at
        # startup; explicit `is True` / `is False` comparisons in
        # _on_state_update mean the first push doesn't fire spuriously.
        self._prev_in_dock: bool | None = None
        self._prev_charging_status: int | None = None
        # Tracks the previous s2p57 robot_shutdown_trigger value for the
        # self_shutdown lifecycle edge-fire. None at startup so a value
        # already 1 at boot only primes and doesn't fire spuriously.
        self._prev_shutdown_trigger: int | None = None
        # Unix timestamp when the rain-protection delay started (s2p2→56
        # rising edge). None when no rain delay is active. Cleared on dock
        # departure (mower retried after the rain wait) and on session end.
        self._rain_delay_started_at: int | None = None
        # Tracks the previous s2p2 / error_code value for notification-event
        # synthesis. Fires dreame_a2_mower_alert events on transitions to
        # known codes (S2P2_EVENT_TYPES). None at startup so the first
        # push doesn't fire spuriously on HA boot.
        self._prev_error_code: int | None = None
        # (c) new-task-command boundary: tracks whether the last-seen s2p56
        # `status` list was empty `[]`. The firmware drops s2p56 to `[]`
        # between two DISTINCT task commands (e.g. an abandoned manual run,
        # then a mow started from the same spot with no dock between). A
        # queued multi-target run keeps ONE non-empty s2p56 list across its
        # per-target arrivals, so it never trips this. None until the first
        # s2p56 push is observed (so the first command doesn't false-split).
        self._prev_s2p56_empty: bool | None = None
        # Pending task op (s2p50 echo) latched ungated by session-active so a
        # patrol/mow/etc. commanded from the dock is recorded before
        # begin_session exists to hold it. Seeded into live_map.last_task_op at
        # begin_session; persisted via the pending_task_op sidecar. See
        # docs/superpowers/specs/2026-06-04-patrol-session-type-recording-design.md
        self._pending_task_op: int | None = None
        # Pending patrol-start (s2p2=51) latched ungated by session-active. A
        # POINT patrol's only type signal is s2p2=51, which arrives AT session
        # start — before begin_session, so _capture_telemetry_sample's
        # is_active() guard drops it from error_samples. Latch it here so
        # _seed_session_type_from_pending can stamp live_map.saw_patrol_start at
        # begin (the op-echo path covers edge patrols, which DO emit op=108).
        self._pending_saw_patrol_start: bool = False
        # Optimistic patrol-config writes. CRUISE.0 (the cloud device-data the
        # cruise config is read from) propagates with significant lag after a
        # CRUISED write, so a poll right after a successful write returns the
        # STALE value and would revert the user's change in the UI. Keyed by
        # (map_id, point_id) -> {"cycles", "auto_capture", "ts"}; overlaid onto
        # cruise_config_by_map at each cloud_state apply until the poll confirms
        # the new value (cleared) or _PENDING_CRUISE_TTL elapses (give up).
        # See coordinator/_cloud_state.py:_apply_pending_cruise_overlay.
        self._pending_cruise_writes: dict[tuple[int, int], dict] = {}
        # Single finalize latch (P3e.4). Serializes ALL finalize entries
        # (gate path, new-command boundary, non-mow immediate, manual button)
        # and de-dupes by the session's start_ts. Both terminal archive writers
        # (_do_oss_fetch, _run_finalize_incomplete) run their body inside
        # _finalize_with_latch, which acquires _finalize_lock, no-ops if the
        # session's start_ts was already finalized (== _finalizing_start_ts),
        # records it, runs the body, and releases in a finally. This subsumes
        # the old ad-hoc _non_mow_finalize_in_progress bool and closes the
        # s2p2=75-vs-task_state-edge double-fire race more robustly (it covers
        # cross-path concurrency, not just the two non-mow triggers). The
        # archive-level (md5, start_ts) dedup stays as the backstop.
        self._finalize_lock: asyncio.Lock = asyncio.Lock()
        # Single sentinel (the last-finalized start_ts), NOT a set: two real
        # sessions cannot begin in the same wall-clock second, and this is
        # in-memory so it can't survive a reboot to collide with a restored
        # session — so a same-second start_ts reuse false-no-op is unreachable.
        self._finalizing_start_ts: int | None = None
        # Stores the most-recent fired notification for sensor.last_notification.
        # Shape: {"event_type": str, "text": str, "code": int, "fired_at": int}
        self._last_notification: dict | None = None

        # Cloud-driven notification resolver state (2026-05-26). All
        # in-memory only — restart wipes them by design; the baseline
        # task re-seeds seen_ids on next startup so old records don't
        # replay as events.
        # See coordinator/_notifications.py for the full flow.
        import collections as _collections
        self._notif_text_cache: dict[tuple[int, int, int], str] = {}
        self._notif_seen_ids: _collections.OrderedDict[str, Any] = (
            _collections.OrderedDict()
        )
        self._notif_baseline_done: bool = False

        # Session archive — persists completed sessions to disk (F5.4.1, F5.6.1).
        # <config>/dreame_a2_mower/sessions/ — matches legacy layout.
        sessions_dir = hass.config.path(DOMAIN, "sessions")
        self.session_archive = SessionArchive(Path(sessions_dir))
        # F7.7.1: apply retention from options (if set), else use default.
        opts = getattr(entry, "options", {}) or {}
        session_keep = int(
            opts.get(CONF_SESSION_ARCHIVE_KEEP, DEFAULT_SESSION_ARCHIVE_KEEP)
        )
        if hasattr(self.session_archive, "set_retention"):
            self.session_archive.set_retention(session_keep)

        # F7.2.2: LiDAR archive — persists PCD scans announced via s99p20.
        # Layout: <config>/dreame_a2_mower/lidar/<map_id>/  (per-map subdirs).
        # F7.7.1: retention and max_bytes read from entry.options at startup.
        # T12: per-map archive dict; lazy-init via lidar_archive_for(map_id).
        lidar_dir = hass.config.path(DOMAIN, "lidar")
        self._lidar_archive_root: Path = Path(lidar_dir)
        self._lidar_archive_root.mkdir(parents=True, exist_ok=True)
        self._lidar_archive_retention: int = int(
            opts.get(CONF_LIDAR_ARCHIVE_KEEP, DEFAULT_LIDAR_ARCHIVE_KEEP)
        )
        self._lidar_archive_max_bytes: int = (
            int(opts.get(CONF_LIDAR_ARCHIVE_MAX_MB, DEFAULT_LIDAR_ARCHIVE_MAX_MB))
            * 1024 * 1024
        )
        # dict[int, LidarArchive] — populated lazily by lidar_archive_for().
        self.lidar_archives: dict[int, LidarArchive] = {}
        self._last_lidar_object_name: str | None = None
        # One-shot startup LiDAR backfill from the 3dmap OBJ list (so fresh
        # installs don't wait for the next s99.20 "View LiDAR Map" push). Set
        # True after the first successful 3dmap list (even if empty).
        self._lidar_backfill_done: bool = False

        # Album photos (Patrol + AI-obstacle). [dreame-app-implementation-guide-2026-06-09.md]
        # Layout: <config>/dreame_a2_mower/photos/  (flat — not per-map; see PhotoArchive docs).
        photo_dir = Path(hass.config.path(DOMAIN, "photos"))
        self._photo_archive: PhotoArchive = PhotoArchive(
            photo_dir,
            retention=int(opts.get(CONF_PHOTO_ARCHIVE_KEEP, DEFAULT_PHOTO_ARCHIVE_KEEP)),
            max_bytes=int(opts.get(CONF_PHOTO_ARCHIVE_MAX_MB, DEFAULT_PHOTO_ARCHIVE_MAX_MB)) * 1024 * 1024,
        )
        # The signing endpoint for photo OSS keys. LIVE-VERIFIED 2026-06-09
        # (tools/probes/oss_photo_probe.py): get_interim_file_url is correct — it
        # prepends `oss/media/000000/oss/` to the bare object_name from
        # protocol/photo_keys.build_photo_object_key, and a real photo downloaded
        # as a 57 KB JPEG. (get_file_url is wrong: 479D path + leading-char strip.)
        self._photo_sign_fn = lambda c, k: c.get_interim_file_url(k)

        # Phase D: set per-category retention on the photo archive so each
        # detection type (obstacle / person / patrol) keeps at most
        # DEFAULT_PHOTO_ARCHIVE_PER_CATEGORY images on disk.
        self._photo_archive.set_per_category_retention(DEFAULT_PHOTO_ARCHIVE_PER_CATEGORY)

        # Gallery manifest (newest-first list of photo/video items with signed
        # media URLs) — rebuilt by _refresh_oss_gallery and read by the
        # sensor.dreame_a2_mower_photo_gallery / the gallery dashboard card.
        self._photo_gallery: list[dict] = []

        # AIOBS live obstacle markers (volatile — current session only).
        # Layout: <config>/dreame_a2_mower/obstacle_markers/  (sibling of photos/).
        self._obstacle_markers: list[ObstacleMarker] = []
        obstacle_markers_dir = Path(hass.config.path(DOMAIN, "obstacle_markers"))
        self._obstacle_marker_log: ObstacleMarkerLog = ObstacleMarkerLog(
            obstacle_markers_dir
        )

        # Video archive — persists patrol/AI-obstacle MP4 clips + thumbs.
        # Layout: <config>/dreame_a2_mower/videos/  (flat — not per-map).
        # Retention and byte cap mirror the photo archive pattern.
        video_dir = Path(hass.config.path(DOMAIN, "videos"))
        self._video_archive: VideoArchive = VideoArchive(
            video_dir,
            retention=int(opts.get(CONF_VIDEO_ARCHIVE_KEEP, DEFAULT_VIDEO_ARCHIVE_KEEP)),
            max_bytes=int(opts.get(CONF_VIDEO_ARCHIVE_MAX_MB, DEFAULT_VIDEO_ARCHIVE_MAX_MB)) * 1024 * 1024,
        )

        # WiFi archive — persists heatmap objects fetched from OSS.
        # Layout: <config>/dreame_a2_mower/wifi_archive/
        # Store is created here; index is loaded via executor in async_setup_entry
        # (pattern a) and passed as `wifi_index` to avoid a blocking disk read
        # inside __init__.  Falls back to [] when not supplied (should not happen
        # in normal HA startup, but guards test / programmatic construction).
        wifi_archive_dir = Path(hass.config.path(DOMAIN, "wifi_archive"))
        self._wifi_archive_store: WifiArchiveStore = WifiArchiveStore(wifi_archive_dir)
        # Per-map keep-newest-N cap (enforced after tagging in
        # refresh_wifi_archive). 0 = unlimited. Bounds the picker + disk.
        self._wifi_archive_store.set_retention(
            int(opts.get(CONF_WIFI_ARCHIVE_KEEP, DEFAULT_WIFI_ARCHIVE_KEEP))
        )
        self._wifi_archive_index: list[WifiArchiveEntry] = (
            wifi_index if wifi_index is not None else []
        )

        # Unified cloud state — populated by _refresh_cloud_state every 2 min.
        # All cloud-fetched data (maps, settings, schedule, mow paths, etc.)
        # lives here as the single source of truth.
        self.cloud_state: Any = None  # CloudState | None — actual import deferred

        # Live-map base PNG cache (rehaul). The composited live PNG is gone:
        # the server renders only the base, keyed on background mode + map md5.
        # Trail + mower icon are drawn client-side from the published stream.
        self._base_png: bytes | None = None
        self._base_png_mode: object | None = None    # BackgroundMode of _base_png
        self._base_png_md5: str | None = None         # MapData.md5 of _base_png
        self._base_png_marker_fp: int | None = None   # live obstacle marker count at last render
        self._editor_base_png: bytes | None = None    # clean base (no exclusions) for the map-editor card
        # Live position stream published on the map camera entity (Task 5).
        self._live_point_seq: int = 0
        self._latest_point: list | None = None        # [x_m, y_m, heading|None, t]
        # Cold-start backfill cache: (len(live_map.track), derived rows). The
        # snapshot is derived on demand from live_map.track (live_track_snapshot)
        # — no per-push mirror — so it survives a mid-session restart for free.
        self._track_snapshot_cache: tuple[int, list] | None = None
        # Remaining PNG cache slots, one per render pipeline:
        #   _static_map_pngs_by_id — per-map static base + M_PATH (cumulative)
        #   _work_log_png          — picker-selected archived session
        # Each slot is owned by one render path; no shared mutability.
        self._work_log_png: bytes | None = None
        # No-trail variant of _work_log_png — same map, no trail painted.
        # Used by the replay card as its animation base so the SVG-animated
        # trail doesn't double up on a pre-painted static trail.
        self._work_log_base_png: bytes | None = None
        # Active map's CLEAN base render (light lawn, no trail/icon/stripes/
        # green) — the Work Log camera's empty-state image. Distinct from the
        # live `_base_png` (which carries the active background mode). Fed by
        # `_render_active_map_base`, called at the end of `_render_base`.
        self._active_map_base_png: bytes | None = None
        self._active_map_base_md5: str | None = None
        self._picked_session_summary: dict[str, Any] | None = None
        """Flat attribute dict for sensor.dreame_a2_mower_picked_session.
        Set by render_work_log_session; cleared by the work_log select
        when the placeholder is picked."""
        # Per-map cache of last-session obstacle polygons (cloud-frame metres).
        # Populated lazily on first `_render_base` per map_id by reading
        # the most-recent ArchivedSession for that map from disk; invalidated
        # to None whenever a new session is archived so the next render picks
        # up fresh obstacles. Value of `[]` means "loaded, but no obstacles" —
        # distinct from `None` ("not yet loaded"). The renderer treats both
        # the same, but the sentinel avoids re-loading disk on every tick.
        self._last_session_obstacles_by_map: dict[
            int, list[list[tuple[float, float]]]
        ] = {}
        # Single coordinator-wide mutex serializing all chunked-batch
        # cloud writes (SETTINGS / SCHEDULE / AI_HUMAN). Each per-domain
        # helper acquires this around the read-modify-write sequence so
        # two near-simultaneous entity writes can't race on the same blob.
        # Hold time per write is sub-second; cross-blob writes are rare
        # so a single mutex (vs per-blob) keeps reasoning simple.
        self._chunked_write_lock: asyncio.Lock = asyncio.Lock()
        # Monotonic txn id for the SCHD*V3 schedule write (shared across a
        # write's header+chunks); _next_schedule_txn_id bumps it.
        self._last_schedule_txn_id: int = 0
        # Debounce timer for tripwire-driven cloud refreshes.
        # When the firmware pushes a "settings-saved" MQTT slot
        # (see _SETTINGS_TRIPWIRE_SLOTS), we schedule a deferred
        # _refresh_cloud_state. Bursts coalesce: each fresh tripwire
        # cancels any pending fire and pushes the deadline back, so
        # one final refresh runs after the burst settles.
        self._cloud_refresh_debounce_handle: asyncio.TimerHandle | None = None
        self._static_map_pngs_by_id: dict[int, bytes] = {}
        self._last_map_md5_by_id: dict[int, str] = {}
        # Active map (from MAPL polling). None until first MAPL response.
        self._active_map_id: int | None = None
        # Cross-map LiDAR archive selection — drives DreameA2LidarSelectedCamera.
        # Tuple of (map_id, filename) — None means "show latest scan from active map".
        self._lidar_render_entry: tuple[int, str] | None = None
        # WiFi archive selection — drives DreameA2WifiSelectedCamera.
        # Tuple of (map_id, object_name) — None means "latest from active map".
        self._wifi_render_entry: tuple[int, str] | None = None
        # Last archive refresh result — updated by refresh_wifi_archive.
        self._wifi_archive_last_refresh: dict = {}
        # Decoded wifi-body cache — keyed by object_name.
        # Populated asynchronously by _async_load_wifi_body() which is
        # scheduled via async_create_task in set_wifi_render_entry.
        # The camera's available/async_camera_image reads from here so the
        # disk read never happens on the event loop.
        self._wifi_body_cache: dict[str, Any | None] = {}
        # Dirty flag for in-progress persistence (F5.7.1).
        # Set by _on_state_update after every append_point; cleared by
        # _persist_in_progress after a successful disk write.
        self._live_map_dirty: bool = False

        # Novel-observation registry (F6.2.1).
        # Tracks first-sightings of unknown protocol tokens so the watchdog
        # WARNING fires only once per token per process lifetime.
        self.novel_registry = NovelObservationRegistry()
        # Per-field freshness tracker (F6.6.1).
        # Records the last unix timestamp each MowerState field changed.
        self.freshness = FreshnessTracker()

        # Cloud-poll availability gate (Phase 1.1). Counts CONSECUTIVE
        # full-state poll (`_refresh_cloud_state`) failures; cloud-sourced
        # entities go unavailable once it reaches _CLOUD_UNAVAIL_THRESHOLD.
        # Reset to 0 on the first success. Kept separate from
        # DataUpdateCoordinator.last_update_success on purpose: frequent MQTT
        # pushes call async_set_updated_data (→ last_update_success=True), which
        # would otherwise mask a cloud-read outage while the device link is up.
        self._consecutive_cloud_failures = 0

        # Multi-dimensional state machine — canonical source of behavioural
        # state (activity, location, session). Entities read from
        # state_machine.snapshot().
        self.state_machine = MowerStateMachine()
        self._state_store: Store | None = None  # initialised in _async_update_data
        self._device_messages_store: Store | None = None  # initialised in _async_update_data
        # Pending-finalize wait (dock-return capture).
        # Set to an asyncio.Event by _wait_for_dock_return; cleared in its
        # finally block so stale signals from subsequent MQTT pushes are
        # harmless. Task slot reserved for future cancellation support.
        self._pending_finalize_task: "asyncio.Task | None" = None
        self._pending_finalize_done: "asyncio.Event | None" = None
        self._pending_finalize_done_reason: str | None = None

    @property
    def sn(self) -> str | None:
        """Hardware serial number — preferred over `entry_id` for stable HA identifiers.

        Two sources, in priority order:
          1. `_cloud.serial_number` — set by `_handle_device_info` if the
             cloud's device-info response carried `sn`. Reliable when the
             device-info call returns the field, which `get_devices()`
             frequently does NOT.
          2. `data.hardware_serial` — set by `_refresh_dev()` from the
             routed-action s2.50 `{m:'g', t:'DEV'}` payload, which
             *always* carries `sn` on g2408. This runs synchronously
             during `async_config_entry_first_refresh`, so it's
             reliably populated by the time the migration retry checks.
        """
        client = self._cloud if hasattr(self, "_cloud") else None
        from_cloud = getattr(client, "serial_number", None) if client is not None else None
        if from_cloud:
            return from_cloud
        data = getattr(self, "data", None)
        return getattr(data, "hardware_serial", None) if data is not None else None

    @property
    def station_bearing_deg(self) -> float | None:
        """Compass bearing (degrees CW from north) of the dock's local X axis.

        User-set via config flow options. ``None`` when unset, in which
        case the N/E projection is skipped (position_north_m /
        position_east_m sensors stay Unknown).

        CFG.DOCK.yaw is unreliable on this firmware (drifts even when the
        dock has not physically moved), so we don't read it from the
        device — this option is the canonical source.
        """
        val = self.entry.options.get(CONF_STATION_BEARING_DEG)
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    @property
    def rain_resume_at_unix(self) -> int | None:
        """Projected unix time the mower retries after a rain delay."""
        started = self._rain_delay_started_at
        if started is None:
            return None
        hours = self.data.rain_protection_resume_hours
        if not hours:
            return None
        return int(started) + int(hours) * 3600

    @property
    def rain_delay_active(self) -> bool:
        """True while the mower is waiting out the rain-protection timer."""
        # getattr default: some test fixtures build the coordinator via __new__
        # without __init__, so the attribute may not exist.
        if getattr(self, "_rain_delay_started_at", None) is None:
            return False
        resume_at = self.rain_resume_at_unix
        if resume_at is None:
            return True
        return time.time() < resume_at

    # ------------------------------------------------------------------
    # Per-source availability signals (Phase 1.1)
    # ------------------------------------------------------------------
    @property
    def cloud_is_fresh(self) -> bool:
        """False once the full-state cloud poll has failed enough consecutive
        times that cloud-sourced entities should report unavailable."""
        # getattr default: __new__-built test fixtures may skip __init__.
        return (
            getattr(self, "_consecutive_cloud_failures", 0)
            < self._CLOUD_UNAVAIL_THRESHOLD
        )

    @property
    def mqtt_is_fresh(self) -> bool:
        """Whether the MQTT-sourced entities should report *available* (todo8 #1).

        This is a TRANSPORT check, not a device-liveness inference. The entity is
        available whenever we can still receive data — i.e. our MQTT client holds
        a live broker connection (so any push WILL reach us) OR the cloud poll is
        succeeding. It is deliberately NOT gated on heartbeat freshness: the
        device backs its whole telemetry radio off to a multi-minute (docked:
        multi-hour) cadence whenever it is not actively mowing, so heartbeat
        silence is normal and must not flap the entity. Like the Dreame app, we
        then keep showing last-known state — including error states, which the
        firmware reports as data before a battery-dead shutdown.

        Genuine unavailable = we have lost BOTH links (broker disconnected AND
        cloud failing) and truly cannot get this entity's data. The 90s
        connectivity STALE flip survives only as the informational
        ``mqtt_connectivity`` sensor; it no longer gates availability."""
        mqtt = getattr(self, "_mqtt", None)
        if mqtt is not None:
            try:
                if mqtt.is_connected:
                    return True
            except AttributeError as ex:
                # Only a partially-shaped stand-in lacking the attribute can
                # land here (the real client always has the property; a
                # missing _mqtt is handled by the getattr above). Anything
                # else must propagate — the old broad `except Exception`
                # swallow is exactly what hid the is_connected() TypeError
                # for months (R-4 / T3-1).
                LOGGER.debug(
                    "mqtt_is_fresh: _mqtt not fully initialised: %s", ex
                )
        return self.cloud_is_fresh

    def _note_cloud_fetch(self, *, ok: bool) -> None:
        """Record the outcome of a full-state cloud poll for the availability
        gate. Success resets the streak; failure increments it."""
        if ok:
            self._consecutive_cloud_failures = 0
        else:
            self._consecutive_cloud_failures = (
                getattr(self, "_consecutive_cloud_failures", 0) + 1
            )

    async def _restore_device_messages(self) -> None:
        """Seed MowerState.device_messages from the persisted store on boot so
        the sensor shows retained history immediately and it becomes the merge
        base for the first fetch. Tolerates a missing/corrupt store."""
        if self._device_messages_store is None:
            self._device_messages_store = Store(
                self.hass,
                version=1,
                key=f"dreame_a2_mower_device_messages_{self.entry.entry_id}",
            )
        try:
            stored = await self._device_messages_store.async_load()
        except Exception:
            LOGGER.exception("device_messages restore failed; continuing empty")
            return
        if isinstance(stored, list) and stored:
            cap = int(
                self.entry.options.get(CONF_MESSAGES_KEEP, DEFAULT_MESSAGES_KEEP)
            )
            self.data.device_messages = stored[:cap]

    async def _async_update_data(self) -> MowerState:
        """First-refresh path — auth, device discovery, MQTT subscribe.

        Subsequent refreshes are push-driven via the MQTT callback;
        this method only re-runs if the user manually refreshes the
        integration.
        """
        if not hasattr(self, "_cloud"):
            # Restore the state machine from disk before any new signals arrive.
            if self._state_store is None:
                self._state_store = Store(
                    self.hass,
                    version=1,
                    key=f"dreame_a2_mower_state_{self.entry.entry_id}",
                )
            try:
                await self.state_machine.load_persisted(self._state_store)
            except Exception:
                LOGGER.exception(
                    "state_machine.load_persisted failed; continuing with initial snapshot"
                )

            await self._restore_device_messages()

            self._cloud = await self.hass.async_add_executor_job(
                self._init_cloud
            )

            # Restore any in-progress session BEFORE _init_mqtt subscribes
            # to the mower's status topic. If we restored after MQTT, the
            # broker's retained s2p56 message could land between any of the
            # subsequent `await`s, fire begin_session(now_unix), and clobber
            # the disk-persisted legs with the current restart timestamp.
            # See coordinator.py:_restore_in_progress for the full race
            # narrative; pairing this with the `not live_map.is_active()`
            # guard in _on_state_update is the trail-loss-on-restart fix.
            await self._restore_in_progress()

            # Re-post error-tier persistent notices for faults latched on disk:
            # snapshot.errors is restored above, but _fire_fault_delta won't
            # re-fire them across a restart (no delta vs the restored set), so the
            # banner would be lost. Re-post directly (no spurious fault_detected).
            # Guarded so a notice failure can never abort coordinator setup.
            try:
                self._repost_active_fault_notices()
            except Exception:
                LOGGER.exception("_repost_active_fault_notices failed during restore")

            await self.hass.async_add_executor_job(self._init_mqtt)

            # Ensure the debounce handle from _device_sync (set by tripwire
            # callbacks via loop.call_later) doesn't fire into a torn-down
            # coordinator after entry unload.
            def _cancel_debounce_handle() -> None:
                handle = self._cloud_refresh_debounce_handle
                if handle is not None:
                    handle.cancel()
                    self._cloud_refresh_debounce_handle = None

            self.entry.async_on_unload(_cancel_debounce_handle)

            # Periodic cloud-state refresh. The MQTT-driven s6p2 tripwire
            # (see _SETTINGS_TRIPWIRE_SLOTS) catches most app-side saves
            # within ~5 s, but some BT-only settings (obstacleAvoidanceHeight,
            # mowing direction, edge mowing toggles, AI bits) don't push
            # any MQTT signal. The periodic poll is the fallback for those.
            # 2 min gives a tight worst-case latency without hammering the
            # cloud — a full refresh costs ~6 RPCs, so 3 RPC/min average.
            async def _periodic_cloud_state(_now: Any) -> None:
                await self._refresh_cloud_state()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_cloud_state, timedelta(minutes=2)
                )
            )
            await self._refresh_cloud_state()

            # Cloud-notification baseline (2026-05-26). One-shot, silent —
            # seeds _notif_seen_ids with whatever the cloud's
            # device-messages/v2 holds RIGHT NOW so historical records don't
            # replay as fresh HA events. Subsequent s2p2 transitions kick off
            # the resolver in _NotificationsMixin. Best-effort: failures
            # (cloud down, auth pending) are swallowed; the resolver will
            # retry the baseline on the first real s2p2 transition.
            try:
                await self._establish_notification_baseline()
            except Exception:
                LOGGER.debug(
                    "[notif] baseline at setup failed; will retry on first s2p2",
                    exc_info=True,
                )

            # Schedule GPS refresh every 60 seconds via getRecords; also fire
            # one immediately so position_lat/lon are populated at startup.
            # This is the sole mower-position source (the legacy LOCN
            # routed-action path was retired).
            async def _periodic_gps(_now: Any) -> None:
                await self._refresh_gps()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_gps, timedelta(seconds=60)
                )
            )
            await self._refresh_gps()

            # AIOBS live obstacle markers: poll every 2 min, but _refresh_aiobs
            # itself early-returns unless a mow session is active (mow-gated,
            # NOT background). No immediate fire — no session active at boot.
            async def _periodic_aiobs(_now: Any) -> None:
                await self._refresh_aiobs()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_aiobs, timedelta(minutes=2)
                )
            )

            # Schedule REMOTE refresh every 6 hours; also fire one immediately
            # so 4G SIM status (left_days, card_id, etc.) is populated at startup.
            async def _periodic_remote(_now: Any) -> None:
                await self._refresh_remote()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_remote, timedelta(hours=6)
                )
            )
            await self._refresh_remote()

            # Schedule message-record refresh every hour; also fire one immediately
            # so service/system unread counts are populated at startup.
            async def _periodic_messages(_now: Any) -> None:
                await self._refresh_messages()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_messages, timedelta(hours=1)
                )
            )
            await self._refresh_messages()

            # Schedule OSS gallery sync every hour; also fire one immediately
            # so album photos and videos are populated at startup (Phase D).
            async def _periodic_oss_gallery(_now: Any) -> None:
                await self._refresh_oss_gallery()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_oss_gallery, timedelta(hours=1)
                )
            )
            # Boot: full backfill (page to natural exhaustion — list_oss_media
            # stops at the first short page). The hourly periodic call stays at
            # the default, smaller cap.
            await self._refresh_oss_gallery(max_pages=400)

            # Schedule DEV refresh every 6 hours; also fire one immediately
            # so the hardware serial / firmware version land at startup
            # (the s1p5 fallback path mostly returns 80001).
            async def _periodic_dev(_now: Any) -> None:
                await self._refresh_dev()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_dev, timedelta(hours=6)
                )
            )
            await self._refresh_dev()

            # Schedule NET refresh every hour; also fire one immediately
            # so wifi_ssid / wifi_ip / wifi_rssi_dbm have values at boot
            # (otherwise the RSSI sensor sits Unknown for ~45 s waiting
            # for the first s1p1 heartbeat).
            async def _periodic_net(_now: Any) -> None:
                await self._refresh_net()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_net, timedelta(hours=1)
                )
            )
            await self._refresh_net()

            # Schedule DOCK refresh every 60s; mower-in-dock is the
            # most useful field and benefits from quicker updates so
            # automations can trigger on dock arrival/departure.
            async def _periodic_dock(_now: Any) -> None:
                await self._refresh_dock()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_dock, timedelta(seconds=60)
                )
            )
            await self._refresh_dock()

            # Seed the WiFi archive picker cache so select.wifi_archive has
            # options immediately (before the user presses any refresh button).
            # Best-effort: failures are non-fatal; the picker stays empty and
            # the user can trigger a refresh manually.
            try:
                await self.refresh_wifi_archive()
            except Exception as _ex:
                LOGGER.debug("Initial WiFi archive fetch failed: %s", _ex)

            # Re-list BOTH archives every 6h so a long-running integration picks
            # up new wifimap / 3dmap objects without waiting for a restart. WiFi
            # is poll-only (no MQTT push) and LiDAR's s99.20 fires only on an app
            # "View LiDAR Map" tap; the boot backfill covers the down-then-restart
            # case, this timer covers the up-but-idle case. 6h matches _periodic_dev.
            async def _periodic_archive(_now: Any) -> None:
                await self._periodic_archive_refresh()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_archive, timedelta(hours=6)
                )
            )

            # Schedule session-finalize retry every RETRY_INTERVAL_SECONDS (60s).
            # Consults finalize.decide() each tick; dispatches AWAIT_OSS_FETCH /
            # FINALIZE_INCOMPLETE / NOOP as appropriate.
            async def _periodic_session(_now: Any) -> None:
                await self._periodic_session_retry()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass,
                    _periodic_session,
                    timedelta(seconds=RETRY_INTERVAL_SECONDS),
                )
            )

            # _poll_slow_properties + its hourly timer were removed 2026-05-26.
            # s6.3 (cloud_connected, rssi) was the 80001 source at :01 and is
            # redundant with heartbeat-fresh wifi_rssi_dbm + MQTT-up; s1.5
            # serial is owned by DEV. See coordinator/_refreshers.py for the
            # full rationale and docs/research/app-api-surface-2026-05-25.md.

            # Load obstacle-marker log from disk (non-blocking via executor).
            await self.hass.async_add_executor_job(self._obstacle_marker_log.load)

            # Load session archive index from disk (non-blocking via executor).
            await self.hass.async_add_executor_job(self.session_archive.load_index)
            archived_count = self.session_archive.count
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
            self._base_png = None
            await self._render_base()
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
                    sessions = await self.hass.async_add_executor_job(
                        self.session_archive.list_sessions
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
                if first_ts is not None and self.data.first_mowing_date is None:
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
                self.data = dataclasses.replace(self.data, **seed_updates)

            # F7.2.2: same pattern for the LiDAR archive.
            # Load index for all existing per-map subdirs so the count
            # sensor populates on first refresh.
            # iterdir() does blocking scandir under the hood — must run in
            # an executor or HA logs a "blocking call inside event loop"
            # warning at every startup.
            def _list_lidar_subdirs() -> list[tuple[int, "Path"]]:
                out: list[tuple[int, "Path"]] = []
                for sub in self._lidar_archive_root.iterdir():
                    if sub.is_dir() and sub.name.isdigit():
                        try:
                            out.append((int(sub.name), sub))
                        except ValueError:
                            pass
                return out
            _lidar_count = 0
            try:
                _subdirs = await self.hass.async_add_executor_job(
                    _list_lidar_subdirs
                )
            except (OSError, FileNotFoundError):
                _subdirs = []
            for _map_id, _sub in _subdirs:
                try:
                    _arch = self.lidar_archive_for(_map_id)
                    await self.hass.async_add_executor_job(_arch.load_index)
                    _lidar_count += _arch.count
                except Exception as _ex:
                    LOGGER.debug(
                        "[LIDAR] startup index load failed for %s: %s", _sub, _ex
                    )
            if _lidar_count:
                self.data = dataclasses.replace(
                    self.data, archived_lidar_count=_lidar_count
                )

            # _restore_in_progress already ran above (before _init_mqtt).

            # Schedule 30-second debounced persist of the in-progress trail.
            # Only writes when live_map is active AND dirty (new point appended).
            async def _periodic_persist(_now: Any) -> None:
                await self._persist_in_progress(_now)

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass,
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
                    self.state_machine.tick(now_unix=now_unix)
                except Exception:
                    LOGGER.exception("state_machine.tick failed")
                # Cold-boot telemetry reconciliation. MQTT properties_changed
                # only fires on change, so a mid-session integration restart
                # never receives the start events. Use continuous telemetry
                # (area_mowed + live_map) to infer the mow session/activity.
                # (Location is NOT reconciled here — s2p1 is its sole authority.)
                try:
                    data = self.data
                    self.state_machine.reconcile_from_telemetry(
                        live_map_active=self.live_map.is_active(),
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
                    from ..mower.state import ChargingStatus
                    snap_charging = self.state_machine.snapshot().charging
                    inferred = (
                        ChargingStatus.CHARGING if snap_charging
                        else ChargingStatus.NOT_CHARGING
                    )
                    if self.data.charging_status != inferred:
                        self.async_set_updated_data(
                            dataclasses.replace(
                                self.data, charging_status=inferred,
                            )
                        )
                except Exception:
                    LOGGER.exception("charging_status sync failed")
                # Debounced save: only write if dirty and store is ready.
                if self.state_machine.is_dirty() and self._state_store is not None:
                    self.hass.async_create_task(
                        self.state_machine.save_persisted(self._state_store)
                    )

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass,
                    _state_machine_tick,
                    timedelta(seconds=10),
                )
            )

        return self.data

    def _init_cloud(self) -> DreameA2CloudClient:
        """Authenticate with the Dreame cloud and pick up device info."""
        client = DreameA2CloudClient(
            username=self._username,
            password=self._password,
            country=self._country,
        )
        client.login()
        # Discover and pin the g2408 in the cloud device list. Without
        # this _did is None and get_device_info()'s API call returns no
        # data → _host stays None → mqtt_host_port() raises.
        client.select_first_g2408()
        client.get_device_info()  # refreshes _host with OTC info
        host, port = client.mqtt_host_port()
        self._mqtt_host = host
        self._mqtt_port = port
        LOGGER.info(
            "Cloud auth ok; device %s model=%s host=%s",
            client.device_id,
            client.model,
            self._mqtt_host,
        )
        return client

    def _init_mqtt(self) -> None:
        """Open the MQTT connection and subscribe to the mower's status topic."""
        self._mqtt = DreameA2MqttClient()
        self._mqtt.register_callback(self._on_mqtt_message)
        # Raw-MQTT archive intentionally NOT attached here.
        #
        # We empirically confirmed (2026-05-12) that the integration sees
        # exactly the same MQTT stream as the external probe_a2_mqtt.py —
        # same topic, same slots, byte-identical payloads in side-by-side
        # samples. Having both write the same data to disk doubles I/O
        # for no analytic value. The MqttArchive class is kept (see
        # protocol/mqtt_archive.py) and the .attach_archive hook is kept;
        # re-enable here only for short debug windows when probe is off.
        # See docs/research/gps-tracking-todo.md "What we already know
        # NOT to be the path" for the parity check.
        username, password = self._cloud.mqtt_credentials()
        client_id = self._cloud.mqtt_client_id()
        topic = self._cloud.mqtt_topic()
        # MQTT bootstrap diagnostics — v1.0.0a8 originally fired persistent
        # notifications for these to make early-bring-up debugging visible
        # without HA log access. Now that the integration is stable, demoted
        # to DEBUG-level log lines so the notification panel stays clean for
        # actual user-visible events (e.g. emergency_stop). Re-enable as
        # `LOGGER.warning(...)` plus `_pn.create(...)` if you need to
        # diagnose an MQTT-bringup regression on a fresh install.
        LOGGER.debug(
            "MQTT bootstrap: host=%s:%s client_id=%s "
            "username_len=%d password_len=%d topic=%s "
            "did_set=%s uid_set=%s model=%r",
            self._mqtt_host, self._mqtt_port, client_id,
            len(username) if username else 0,
            len(password) if password else 0,
            topic,
            self._cloud._did is not None,
            self._cloud._uid is not None,
            self._cloud._model,
        )

        def _on_first_inbound(topic: str) -> None:
            LOGGER.debug(
                "MQTT first inbound: topic=%r (subscribed=%r)",
                topic, self._cloud.mqtt_topic(),
            )

        def _on_broker_connected() -> None:
            LOGGER.debug("MQTT CONNACK accepted by broker for topic=%s", topic)
        self._mqtt.register_connected_callback(_on_broker_connected)
        self._mqtt._on_first_message = _on_first_inbound
        self._mqtt.connect(
            host=self._mqtt_host,
            port=self._mqtt_port,
            username=username,
            password=password,
            client_id=client_id,
        )
        # subscribe() now caches the topic; the actual paho subscribe
        # fires from _on_connect after CONNACK (v1.0.0a6 fix).
        self._mqtt.subscribe(topic)
        LOGGER.info("Subscribed to %s", topic)

