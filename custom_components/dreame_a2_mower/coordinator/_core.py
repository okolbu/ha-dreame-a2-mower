"""core mixin — extracted from coordinator.py 2026-05-15.

See spec docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from ..archive.lidar import LidarArchive
from ..archive.obstacle_markers_log import ObstacleMarkerLog
from ..protocol.obstacle_markers import ObstacleMarker
from ..archive.photos import PhotoArchive
from ..archive.session import SessionArchive
from ..archive.videos import VideoArchive
from ..wifi_archive_store import WifiArchiveEntry, WifiArchiveStore
from ..cloud_client import DreameA2CloudClient
from ..domain import boot as _boot
from ..domain import mqtt_lifecycle as _mqtt_lifecycle
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

    # T3-9: minimum spacing between MQTT rc=5 (auth-rejected) relogin
    # attempts. Without this, a broker that keeps rejecting the refreshed
    # credentials (e.g. genuinely bad creds, or a flapping broker) would
    # hammer the cloud login endpoint on every reconnect attempt.
    #
    # P2-inherit (P3.8): the cooldown now ESCALATES with consecutive failures
    # — a broker that keeps rejecting even freshly-refreshed creds shouldn't
    # keep retrying every 30s forever. Effective spacing is
    # ``base * 2**consecutive_failures`` capped at ``_RC5_RELOGIN_COOLDOWN_MAX_S``;
    # a successful re-login resets the counter back to the base spacing.
    _RC5_RELOGIN_COOLDOWN_S = 30
    _RC5_RELOGIN_COOLDOWN_MAX_S = 480

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

        # ==================================================================
        # Attr hub (T2-16 shipped shape). _CoreMixin.__init__ is the SOLE
        # owner of the coordinator's shared private state. The refactor-v2
        # verdict (T2-16, target-architecture §1) did NOT adopt standalone
        # attr-bundling: the domain services extracted in P3.9a-9e take the
        # coordinator (`coord`) as an explicit argument and read/write these
        # attrs on it (attrs-on-coord + service-functions), so this init stays
        # the identifiable home for each service's state. The sections below
        # group the attrs by their OWNING domain service so ownership is
        # legible; the code order is unchanged from the pre-9e init (grouping
        # is by comment, not by reordering — several blocks have construction-
        # order dependencies, e.g. archive-then-set_retention).
        # ==================================================================

        # Initialize empty MowerState — fields fill in as MQTT pushes arrive
        self.data = MowerState()

        # --- Session / live-map lifecycle state (domain/session/*, live_map,
        #     domain/ingress, domain/faults) ---
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

        # --- Cloud-notification resolver state (domain/notifications) ---
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

        # --- On-disk archives (archive/*; served by domain/session,
        #     domain/media/gallery, domain/lidar, domain/wifi) ---
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

        # --- Live-map render caches (domain/render) ---
        # Live-map base PNG cache (rehaul). The composited live PNG is gone:
        # the server renders only the base, keyed on background mode + map md5.
        # Trail + mower icon are drawn client-side from the published stream.
        self._base_png: bytes | None = None
        self._base_png_mode: object | None = None    # BackgroundMode of _base_png
        self._base_png_md5: str | None = None         # MapData.md5 of _base_png
        self._base_png_marker_fp: int | None = None   # live obstacle marker count at last render
        self._base_png_direction: int | None = None   # settings_mowing_direction at last render (T3-4)
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
        # --- Writes + active-map + wifi/lidar render selection
        #     (domain/writes, domain/wifi, domain/lidar, domain/device_sync) ---
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

        # --- Observability (observability/) ---
        # Novel-observation registry (F6.2.1).
        # Tracks first-sightings of unknown protocol tokens so the watchdog
        # WARNING fires only once per token per process lifetime.
        self.novel_registry = NovelObservationRegistry()
        # Per-field freshness tracker (F6.6.1).
        # Records the last unix timestamp each MowerState field changed.
        self.freshness = FreshnessTracker()

        # --- Availability gate + cloud-poll accounting (domain/boot poll
        #     orchestrator + _note_cloud_fetch) ---
        # Cloud-poll availability gate (Phase 1.1). Counts CONSECUTIVE
        # full-state poll (`_refresh_cloud_state`) failures; cloud-sourced
        # entities go unavailable once it reaches _CLOUD_UNAVAIL_THRESHOLD.
        # Reset to 0 on the first success. Kept separate from
        # DataUpdateCoordinator.last_update_success on purpose: frequent MQTT
        # pushes call async_set_updated_data (→ last_update_success=True), which
        # would otherwise mask a cloud-read outage while the device link is up.
        self._consecutive_cloud_failures = 0

        # --- State machine + persistence stores + finalize dock-wait
        #     (state/machine, domain/boot restore, domain/session) ---
        # Multi-dimensional state machine — canonical source of behavioural
        # state (activity, location, session). Entities read from
        # state_machine.snapshot().
        self.state_machine = MowerStateMachine()
        self._state_store: Store | None = None  # initialised in _async_update_data
        self._device_messages_store: Store | None = None  # initialised in _async_update_data
        # Pending-finalize wait (dock-return capture).
        # Set to an asyncio.Event by _wait_for_dock_return; cleared in its
        # finally block so stale signals from subsequent MQTT pushes are
        # harmless. _pending_finalize_task holds the Task wrapping the
        # actual Event.wait() (set/cleared by _wait_for_dock_return itself,
        # T3-8) so async_unload_entry can cancel an in-flight ≤10-min dock
        # wait instead of letting it sleep into a torn-down coordinator.
        self._pending_finalize_task: "asyncio.Task | None" = None
        self._pending_finalize_done: "asyncio.Event | None" = None
        self._pending_finalize_done_reason: str | None = None

        # --- MQTT rc=5 auth-recovery guard state (domain/mqtt_lifecycle) ---
        # T3-9: MQTT rc=5 (auth-rejected) recovery state. Guards against a
        # tight relogin loop — see _handle_mqtt_auth_error.
        self._rc5_relogin_in_progress: bool = False
        self._rc5_last_attempt_unix: float = 0.0
        # P2-inherit (P3.8): consecutive relogin failures drive the cooldown
        # escalation; reset to 0 on a successful re-login.
        self._rc5_consecutive_failures: int = 0

        # T3-8: outstanding s2p2-notification resolver tasks (each sleeps
        # ~_FETCH_DELAY_S before fetching device-messages). Fire-and-forget
        # by design (one per s2p2 transition, self-removing on completion via
        # the done-callback below), but tracked so async_unload_entry can
        # cancel any still in flight instead of letting them fire into a
        # torn-down cloud client after reload/unload.
        self._s2p2_resolver_tasks: "set[asyncio.Task]" = set()

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

    # ------------------------------------------------------------------
    # Transitional accessors (P3.2 string-getattr burn-down, T2-16
    # pre-step). Each replaces one or more
    # ``getattr(coordinator, "_foo", default)`` call sites that used to
    # live in the entity/camera/service layers (track-2 §d2 census). A
    # string getattr on a coordinator-private attr silently returns the
    # default instead of raising when the attr is renamed or moved — the
    # exact "silent breakage" trap the P3.8 domain-service extraction
    # would otherwise walk into. These properties are the TRANSITIONAL
    # home: each preserves the exact default/None semantics of the
    # getattr(s) it replaces, and moves together with its backing attr
    # when that attr is extracted into its owning service in P3.8.
    # ------------------------------------------------------------------

    @property
    def cloud(self) -> DreameA2CloudClient | None:
        """The cloud client, or None before `_init_cloud` has run.

        transitional accessor (P3.2) — moves to the transport service in P3.8.
        """
        return self._cloud if hasattr(self, "_cloud") else None

    @property
    def mqtt(self) -> DreameA2MqttClient | None:
        """The MQTT client, or None before `_init_mqtt` has run.

        transitional accessor (P3.2) — moves to the transport service in P3.8.
        """
        return self._mqtt if hasattr(self, "_mqtt") else None

    @property
    def active_map_id(self) -> int | None:
        """The currently-active map id (from MAPL), or None.

        transitional accessor (P3.2) — moves to the map/session service in P3.8.
        """
        return self._active_map_id if hasattr(self, "_active_map_id") else None

    @property
    def render_base(self):
        """Bound `_render_base` render coroutine, or None if not yet set up.

        transitional accessor (P3.2) — moves to the render service in P3.8.
        """
        return self._render_base if hasattr(self, "_render_base") else None

    @property
    def s2p2_resolver_tasks(self):
        """Set of in-flight s2p2 notification resolver tasks, or None.

        transitional accessor (P3.2) — moves to the notifications service in
        P3.8. Read by domain/session/lifecycle_events.py after the P3.7 ingress
        split; preserves the ``getattr(coord, "_s2p2_resolver_tasks", None)``
        None-default it replaced.
        """
        return (
            self._s2p2_resolver_tasks if hasattr(self, "_s2p2_resolver_tasks") else None
        )

    @property
    def pending_finalize_done(self):
        """The dock-return wait's completion Event while a finalize is pending,
        or None when no wait is active.

        transitional accessor (P3.2) — moves to the session/finalize service in
        P3.8. Read by domain/session/lifecycle_events.py after the P3.7 ingress
        split; preserves the ``getattr(coord, "_pending_finalize_done", None)``
        None-default it replaced.
        """
        return (
            self._pending_finalize_done if hasattr(self, "_pending_finalize_done") else None
        )

    @property
    def wifi_archive_index(self) -> list:
        """The in-memory WiFi heatmap archive index.

        transitional accessor (P3.2) — moves to the wifi-archive service in P3.8.
        """
        return self._wifi_archive_index if hasattr(self, "_wifi_archive_index") else []

    @property
    def finalizing_start_ts(self) -> int | None:
        """The start_ts of the session last finalized to completion (the finalize
        latch's completion key), or None.

        transitional accessor (P3.2) — moves to the session/finalize service in
        9e. Read by domain/session/persistence.py's restore×finalize discard
        guard; preserves the ``getattr(coord, "_finalizing_start_ts", None)``
        None-default it replaced.
        """
        return (
            self._finalizing_start_ts if hasattr(self, "_finalizing_start_ts") else None
        )

    @property
    def rain_delay_started_at(self) -> int | None:
        """Unix ts the current rain-delay pause started, or None.

        transitional accessor (P3.2) — moves to the session service in 9e. Read
        by domain/session/persistence.py when persisting the in-progress payload;
        preserves the ``getattr(coord, "_rain_delay_started_at", None)``
        None-default it replaced.
        """
        return (
            self._rain_delay_started_at if hasattr(self, "_rain_delay_started_at") else None
        )

    @property
    def wifi_archive_store(self):
        """The on-disk WiFi heatmap archive store, or None.

        transitional accessor (P3.2) — moves to the wifi-archive service in P3.8.
        """
        return (
            self._wifi_archive_store if hasattr(self, "_wifi_archive_store") else None
        )

    @property
    def wifi_archive_last_refresh(self) -> dict:
        """Detail of the most recent WiFi-archive refresh attempt.

        transitional accessor (P3.2) — moves to the wifi-archive service in P3.8.
        """
        return (
            self._wifi_archive_last_refresh
            if hasattr(self, "_wifi_archive_last_refresh")
            else {}
        )

    @property
    def last_notification(self) -> dict | None:
        """Most recent app-style notification synthesized from s2p2 transitions.

        transitional accessor (P3.2) — moves to the notifications service in P3.8.
        """
        return (
            self._last_notification if hasattr(self, "_last_notification") else None
        )

    @property
    def obstacle_markers(self) -> list:
        """Live AIOBS obstacle markers for the current session.

        transitional accessor (P3.2) — moves to the AI-obstacle service in P3.8.
        """
        return self._obstacle_markers if hasattr(self, "_obstacle_markers") else []

    @property
    def obstacle_marker_log(self):
        """The archived obstacle-marker log, or None.

        transitional accessor (P3.2) — moves to the AI-obstacle service in P3.8.
        """
        return (
            self._obstacle_marker_log
            if hasattr(self, "_obstacle_marker_log")
            else None
        )

    @property
    def base_png_mode(self):
        """`BackgroundMode` of the cached base-map PNG, or None.

        transitional accessor (P3.2) — moves to the render service in P3.8.
        """
        return self._base_png_mode if hasattr(self, "_base_png_mode") else None

    @property
    def picked_session_summary(self) -> dict | None:
        """The archived-session summary picked in the work-log selector, or None.

        transitional accessor (P3.2) — moves to the session service in P3.8.
        """
        return (
            self._picked_session_summary
            if hasattr(self, "_picked_session_summary")
            else None
        )

    @property
    def novel_log_handler(self):
        """The NOVEL log-line ring-buffer handler installed by `__init__.py`, or None.

        Genuinely optional: assigned post-construction by the integration's
        `async_setup_entry` (not by `_CoreMixin.__init__`), so it can be
        absent on a coordinator that never finished setup.

        transitional accessor (P3.2) — moves to the notifications service in P3.8.
        """
        return (
            self._novel_log_handler if hasattr(self, "_novel_log_handler") else None
        )

    @property
    def cancel_lifecycle_background_tasks(self):
        """Bound `_cancel_lifecycle_background_tasks` method, or None.

        transitional accessor (P3.2) — moves to the session service in P3.8.
        """
        return (
            self._cancel_lifecycle_background_tasks
            if hasattr(self, "_cancel_lifecycle_background_tasks")
            else None
        )

    def _cancel_lifecycle_background_tasks(self) -> None:
        """T3-8: cancel the in-flight dock-wait task (if any) and every
        outstanding s2p2-notification resolver task.

        Called from ``async_unload_entry`` BEFORE transport teardown so none
        of them wakes into a coordinator whose MQTT/cloud links are already
        gone (a ≤10-min dock wait or a ~10s resolver otherwise keeps running
        past unload and either raises against dead transports or silently
        no-ops into a torn-down instance). ``cancel()`` on an already-done
        Task is a no-op, so this is safe to call unconditionally.
        """
        task = getattr(self, "_pending_finalize_task", None)
        if task is not None and not task.done():
            task.cancel()
        for resolver_task in list(getattr(self, "_s2p2_resolver_tasks", ())):
            if not resolver_task.done():
                resolver_task.cancel()

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
        """Delegates to ``domain.boot.async_first_refresh`` (P3.9e).

        The ~450-LOC first-boot poll body (state restore, transport init,
        every periodic-refresher timer registration, archive seeding) moved
        VERBATIM to ``domain/boot.py``, decomposed into ordered seam functions.
        The P2.2 ConfigEntryNotReady contract + the P2.7/P2.9 restore×MQTT
        ordering are preserved there byte-for-byte. ``_init_cloud`` /
        ``_init_mqtt`` / ``_restore_device_messages`` stay here (below) and are
        called by the boot orchestrator via ``coord._init_cloud`` etc.
        """
        return await _boot.async_first_refresh(self)

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

        def _on_auth_error() -> None:
            # T3-9: fires on the paho network thread (mqtt_client's
            # _on_disconnect callback) — hop to the event loop before
            # touching coordinator/cloud-client state.
            self.hass.loop.call_soon_threadsafe(self._handle_mqtt_auth_error)

        self._mqtt.register_auth_error_callback(_on_auth_error)
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

    @callback
    def _handle_mqtt_auth_error(self) -> None:
        """Delegates to ``domain.mqtt_lifecycle.handle_mqtt_auth_error`` (P3.9d).

        Kept ``@callback`` + named here so the ``_init_mqtt`` paho-thread
        ``call_soon_threadsafe(self._handle_mqtt_auth_error)`` wiring and the
        ``test_mqtt_auth_recovery`` surface are unchanged. The rc=5 escalation
        LOGIC moved VERBATIM to the domain layer; the guard-state attrs stay on
        ``_CoreMixin`` (read via ``coord._rc5_*``) for the 9e attr-shrink.
        """
        _mqtt_lifecycle.handle_mqtt_auth_error(self)

    async def _async_recover_mqtt_auth(self) -> None:
        """Delegates to ``domain.mqtt_lifecycle.async_recover_mqtt_auth`` (P3.9d)."""
        await _mqtt_lifecycle.async_recover_mqtt_auth(self)

