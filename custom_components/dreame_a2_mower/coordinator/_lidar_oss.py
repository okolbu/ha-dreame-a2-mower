"""lidar_oss mixin — extracted from coordinator.py 2026-05-15.

See spec docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md.
"""
from __future__ import annotations

import base64
import dataclasses
import json
import math
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from ..archive.lidar import LidarArchive
from ..archive.session import ArchivedSession, SessionArchive
from ..wifi_archive_store import WifiArchiveEntry, WifiArchiveStore
from ..cloud_client import DreameA2CloudClient
from ..const import (
    CONF_COUNTRY,
    CONF_LIDAR_ARCHIVE_KEEP,
    CONF_LIDAR_ARCHIVE_MAX_MB,
    CONF_PASSWORD,
    CONF_SESSION_ARCHIVE_KEEP,
    CONF_STATION_BEARING_DEG,
    CONF_USERNAME,
    DEFAULT_LIDAR_ARCHIVE_KEEP,
    DEFAULT_LIDAR_ARCHIVE_MAX_MB,
    DEFAULT_SESSION_ARCHIVE_KEEP,
    DOMAIN,
    EVENT_TYPE_DOCK_ARRIVED,
    EVENT_TYPE_DOCK_DEPARTED,
    EVENT_TYPE_MOWING_ENDED,
    EVENT_TYPE_MOWING_PAUSED,
    EVENT_TYPE_MOWING_RESUMED,
    EVENT_TYPE_MOWING_STARTED,
    LOG_NOVEL_KEY_SESSION_SUMMARY,
    LOG_NOVEL_PROPERTY,
    LOG_NOVEL_VALUE,
    LOGGER,
)
from ..inventory.loader import load_inventory
from ..live_map.finalize import RETRY_INTERVAL_SECONDS, FinalizeAction
from ..live_map.finalize import decide as _finalize_decide
from ..live_map.state import LiveMapState
from ..mower.actions import ACTION_TABLE, MowerAction
from ..mower.property_mapping import PROPERTY_MAPPING, resolve_field
from ..mower.state import ChargingStatus, MowerState
from ..mower.state_machine import MowerStateMachine
from ..mqtt_client import DreameA2MqttClient
from ..observability.schemas import SCHEMA_SESSION_SUMMARY, SchemaCheck
from ..protocol import photo_meta, session_summary as _session_summary
from ..protocol.photo_category import categorize

from ._property_apply import (
    _BLOB_SLOTS,
    _INVENTORY,
    _SESSION_SUMMARY_CHECK,
    _SETTINGS_TRIPWIRE_SLOTS,
    _SUPPRESSED_SLOTS,
    S2P2_EVENT_TYPES,
    S2P2_UNKNOWN_EVENT_TYPE,
    _apply_consumables,
    _apply_s1p1_heartbeat,
    _apply_s1p4_telemetry,
    _apply_s2p51_settings,
    _coerce_blob,
    _consumable_pct_remaining,
    _project_north_east,
    apply_property_to_state,
)

if TYPE_CHECKING:
    pass  # cross-mixin type imports added as needed


def merge_mow_type_fields(raw_dict: dict, *, mode: int, start_mode: int) -> None:
    """Write mow_type / mow_type_raw / start_mode_label from the OSS summary."""
    from ..protocol.session_summary import mow_type_from_mode, start_mode_label
    label = mow_type_from_mode(mode)
    if label is not None:
        raw_dict["mow_type"] = label
    raw_dict["mow_type_raw"] = mode
    sm = start_mode_label(start_mode)
    if sm is not None:
        raw_dict["start_mode_label"] = sm


def _photo_ts_from_name(name: str) -> int:
    import re
    m = re.match(r"(\d{9,11})", name)
    return int(m.group(1)) if m else 0


def _iso_to_unix(value: Any) -> int | None:
    """Parse a Message.date ISO-8601 string (e.g. '2026-06-15T21:27:59+00:00')
    to a unix timestamp; None on anything unparseable."""
    if not isinstance(value, str) or not value:
        return None
    from datetime import datetime
    try:
        return int(datetime.fromisoformat(value).timestamp())
    except (ValueError, TypeError):
        return None


def fetch_photos_from_summary(cloud, archive, raw_dict, *, sign) -> int:
    """Fetch every photo_list leaf into the PhotoArchive. Returns count added.

    [dreame-app-implementation-guide-2026-06-09.md] photo_list entries are
    <ts>[_person].jpg leaves; the OSS key is built via protocol/photo_keys.
    `sign(cloud, key)` is the signing endpoint (get_interim_file_url or
    get_file_url) — injected so this stays testable and so the live-confirmed
    endpoint can be swapped in. Cloud I/O here is synchronous; callers run the
    whole coroutine in an executor job.
    """
    from ..protocol.photo_keys import build_photo_object_key, is_person_photo
    names = raw_dict.get("photo_list") or []
    if not isinstance(names, list):
        return 0
    added = 0
    for name in names:
        if not isinstance(name, str) or not name:
            continue
        ts = _photo_ts_from_name(name)
        key = build_photo_object_key(uid=str(cloud._uid), did=str(cloud._did), name=name)
        url = sign(cloud, key)
        if not url:
            continue
        body = cloud.get_file(url)
        if not body:
            continue
        meta = photo_meta.parse_jpeg_com(body)
        category = categorize(name=name, record={"type": "jpg"}, com=meta)
        detections = (meta or {}).get("detections") or []
        entry = archive.archive(
            name=name, unix_ts=ts, data=body, is_person=is_person_photo(name),
            category=category, detections=detections,
        )
        if entry is not None:
            added += 1
    return added


def finalize_classify_raw_dict(raw_dict: dict, cloud_segments) -> None:
    """Smooth raw_dict['track'] roles and store cloud_track verbatim.

    cloud_segments: parsed SessionSummary.track_segments (iterable of legs of
    (x,y)). Stored verbatim under 'cloud_track' for reference. NOTE: the cloud
    track is NOT used to reclassify roles — area-delta (set at capture) is
    authoritative; classify_track only smooths isolated stutters. See
    live_map/classify.py for why cloud-coverage rescue was dropped.
    """
    from ..live_map.classify import classify_track

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


class _LidarOssMixin:
    """Methods extracted from coordinator.py — see spec for groupings."""

    def _inject_live_map_into_raw_dict(self, raw_dict: dict[str, Any]) -> None:
        """Add LiveMapState-tracked fields to a cloud-OSS raw_dict before archive.

        Mutates raw_dict in place. Called from _do_oss_fetch and from the
        FINALIZE_INCOMPLETE path. Skips fields whose source is empty so
        older cloud blobs aren't polluted with empty arrays.
        """
        if self.live_map.track:
            raw_dict["track"] = [
                [p.t, p.x_m, p.y_m, p.area_m2, p.heading_deg, p.task_state, p.role]
                for p in self.live_map.track
            ]
        if self.live_map.wifi_samples:
            raw_dict["wifi_samples"] = [
                [float(x), float(y), int(r), int(t)]
                for (x, y, r, t) in self.live_map.wifi_samples
            ]
        if self.live_map.battery_samples:
            raw_dict["battery_samples"] = [
                [int(t), int(v)] for (t, v) in self.live_map.battery_samples
            ]
        if self.live_map.charging_status_samples:
            raw_dict["charging_status_samples"] = [
                [int(t), int(v)] for (t, v) in self.live_map.charging_status_samples
            ]
        if self.live_map.state_samples:
            raw_dict["state_samples"] = [
                [int(t), int(v)] for (t, v) in self.live_map.state_samples
            ]
        if self.live_map.error_samples:
            raw_dict["error_samples"] = [
                [int(t), int(v)] for (t, v) in self.live_map.error_samples
            ]
        if self.live_map.charge_at_start is not None:
            raw_dict["charge_at_start"] = int(self.live_map.charge_at_start)
        if self.live_map.settings_snapshot is not None:
            raw_dict["settings_snapshot"] = dict(self.live_map.settings_snapshot)
        from ..live_map.classify import classify_session_type
        lm = self.live_map
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

    def lidar_archive_for(self, map_id: int) -> LidarArchive:
        """Return (or lazily create) the LidarArchive for *map_id*.

        Creates a new :class:`LidarArchive` under
        ``<_lidar_archive_root>/<map_id>/`` on first access and caches it
        in :attr:`lidar_archives`.  The per-archive retention and size caps
        are inherited from the coordinator's option values.
        """
        if map_id not in self.lidar_archives:
            self.lidar_archives[map_id] = LidarArchive(
                self._lidar_archive_root,
                retention=self._lidar_archive_retention,
                max_bytes=self._lidar_archive_max_bytes,
                map_id=map_id,
            )
        return self.lidar_archives[map_id]

    @property
    def photo_archive(self):
        """Return the shared PhotoArchive (album photos — not map-scoped)."""
        return self._photo_archive

    @property
    def video_archive(self):
        """Return the shared VideoArchive (patrol/AI-obstacle video clips)."""
        return self._video_archive

    def list_lidar_archive_entries(self) -> list[tuple[int, Any]]:
        """Aggregate all LiDAR scans across maps, newest first.

        Returns list of (map_id, ArchivedLidarScan) tuples. Used by the
        cross-map LiDAR archive picker (``select.dreame_a2_mower_lidar_archive``).
        """
        out: list[tuple[int, Any]] = []
        for map_id, archive in self.lidar_archives.items():
            for entry in archive.entries():
                out.append((map_id, entry))
        out.sort(key=lambda x: x[1].unix_ts, reverse=True)
        return out

    def set_lidar_render_entry(self, map_id: int | None, filename: str | None) -> None:
        """Set which LiDAR scan the selected-camera renders. None resets to default."""
        if map_id is None or filename is None:
            self._lidar_render_entry = None
        else:
            self._lidar_render_entry = (map_id, filename)
        update_listeners = getattr(self, "async_update_listeners", None)
        if callable(update_listeners):
            update_listeners()

    def _build_map_extents(self) -> dict[int, tuple[float, float, float, float]]:
        """Build map_id → (bx1, by1, bx2, by2) in cm for all cached maps.

        Used by refresh_wifi_archive to pass geometry hints to
        cloud_client.list_wifi_candidates for cross-map heatmap matching.
        Falls back to empty dict when no maps are cached or extent fields
        are unavailable.
        """
        extents: dict[int, tuple[float, float, float, float]] = {}
        for map_id, map_data in self.cloud_state.maps_by_id.items():
            try:
                bx1 = float(getattr(map_data, "bx1", 0.0))
                by1 = float(getattr(map_data, "by1", 0.0))
                bx2 = float(getattr(map_data, "bx2", 0.0))
                by2 = float(getattr(map_data, "by2", 0.0))
                extents[map_id] = (bx1, by1, bx2, by2)
            except (TypeError, ValueError, AttributeError):
                continue
        return extents

    def _get_wifi_body_cached(self, object_name: str) -> "dict | None":
        """Return the cached decoded wifi-body for ``object_name``, or None.

        Never touches the disk; callers that need the body to be present
        should await ``_async_load_wifi_body`` first, or rely on the
        task scheduled by ``set_wifi_render_entry``.
        """
        return self._wifi_body_cache.get(object_name)

    async def _async_load_wifi_body(self, object_name: str) -> None:
        """Executor-side load of a wifi body; populates ``_wifi_body_cache``.

        Safe to call multiple times for the same object_name — the cache
        acts as a dedup guard.  After loading, notifies all listeners so
        the camera's ``available`` property re-evaluates with the new data.
        """
        store = getattr(self, "_wifi_archive_store", None)
        if store is None:
            return
        body = await self.hass.async_add_executor_job(
            store.load_body, object_name
        )
        self._wifi_body_cache[object_name] = body
        update_listeners = getattr(self, "async_update_listeners", None)
        if callable(update_listeners):
            update_listeners()

    def set_wifi_render_entry(
        self, map_id: int | None, object_name: str | None
    ) -> None:
        """Set which WiFi heatmap the archive camera renders.

        ``object_name`` is the only identity used now (since the
        archive picker always passes ``map_id=None``: heatmap →
        map_id correlation is unsolved — see
        ``docs/research/wifi-heatmap-todo.md``). Pass
        ``object_name=None`` to clear the selection.

        If the body for ``object_name`` is not yet cached, schedules an
        async load via ``hass.async_create_task``.  The camera's
        ``available`` returns False until the load completes; a subsequent
        listener notification makes it True.
        """
        if object_name is None:
            self._wifi_render_entry = None
        else:
            self._wifi_render_entry = (map_id, object_name)
            # Pre-warm the body cache if not already present.
            if object_name not in self._wifi_body_cache:
                self.hass.async_create_task(
                    self._async_load_wifi_body(object_name)
                )
        update_listeners = getattr(self, "async_update_listeners", None)
        if callable(update_listeners):
            update_listeners()

    async def _handle_lidar_object_name(
        self, object_name: str, now_unix: int
    ) -> None:
        """Fetch and archive a LiDAR PCD scan announced via s99p20.

        Called from `_on_state_update` whenever
        `MowerState.latest_lidar_object_name` flips to a new key.
        Idempotent: caches the last-handled object_name to avoid
        re-fetching while the property re-asserts.

        Failures are logged at WARNING and swallowed — observability
        never breaks telemetry, and the user can re-trigger the upload
        from the app.
        """
        if not object_name or object_name == self._last_lidar_object_name:
            return
        self._last_lidar_object_name = object_name
        LOGGER.info("[LIDAR] s99p20 announced object_name=%r", object_name)

        # T12: route to the per-map archive for the currently active map.
        active_id = getattr(self, "_active_map_id", None)
        if active_id is None:
            LOGGER.debug(
                "[LIDAR] push received but _active_map_id unknown — dropping %s",
                object_name,
            )
            return

        cloud = getattr(self, "_cloud", None)
        if cloud is None:
            LOGGER.warning(
                "[LIDAR] fetch skipped (no cloud client): %s", object_name
            )
            return

        try:
            url = await self.hass.async_add_executor_job(
                cloud.get_interim_file_url, object_name
            )
        except Exception as ex:
            LOGGER.warning(
                "[LIDAR] get_interim_file_url failed for %s: %s",
                object_name, ex,
            )
            return
        if not url:
            LOGGER.warning(
                "[LIDAR] get_interim_file_url returned None for %s",
                object_name,
            )
            return

        try:
            raw = await self.hass.async_add_executor_job(cloud.get_file, url)
        except Exception as ex:
            LOGGER.warning(
                "[LIDAR] get_file failed for %s: %s", object_name, ex
            )
            return
        if not raw:
            LOGGER.warning(
                "[LIDAR] get_file returned empty for %s", object_name
            )
            return

        archive = self.lidar_archive_for(active_id)

        entry = await self.hass.async_add_executor_job(
            archive.archive, object_name, now_unix, raw
        )
        if entry is None:
            LOGGER.debug(
                "[LIDAR] dedup hit (md5 already archived): %s", object_name
            )
            return

        LOGGER.info(
            "[LIDAR] archived %s (%d bytes) in map %d, total=%d",
            entry.filename, entry.size_bytes, active_id, archive.count,
        )
        # Update archived_lidar_count on the state for the count sensor.
        self.async_set_updated_data(
            dataclasses.replace(
                self.data, archived_lidar_count=archive.count
            )
        )

    async def _backfill_lidar_from_3dmap(self, now_unix: int) -> None:
        """One-shot startup LiDAR backfill from the `3dmap` OBJ list.

        The live LiDAR path (`_handle_lidar_object_name`) only fires when the
        mower pushes s99.20 — which happens when the user taps "View LiDAR Map"
        in the app, i.e. rarely (observed: 3 in ~3 weeks). A fresh install would
        therefore show no LiDAR scans for potentially weeks. This pulls the
        cloud's currently-available PCD objects (the SAME `.0550.bin` files,
        listed via `s2.50 OBJ type=3dmap` — see inventory.yaml § s99p20) once per
        session and archives any not already present.

        Runs at most once per session (`_lidar_backfill_done`), and only after
        the active map is known. A relay 80001 (list → None) leaves the flag
        unset so the next `_refresh_cloud_state` retries; an accepted-but-empty
        list marks it done (nothing to fetch, don't retry forever). Dedup is by
        object_name BEFORE download, so already-archived scans aren't re-fetched.

        Failures are logged and swallowed — backfill never breaks the refresh.

        Single-map note: the 3dmap object_name doesn't encode a map_id, so all
        backfilled scans route to the CURRENT active map. Correct for the common
        single-map / fresh-install case; on multi-map setups the live s99.20 path
        (which routes per active map at scan time) remains the source of truth.
        """
        if self._lidar_backfill_done:
            return
        active_id = getattr(self, "_active_map_id", None)
        if active_id is None:
            return  # defer until the active map is known (next refresh)
        cloud = getattr(self, "_cloud", None)
        if cloud is None:
            return
        try:
            names = await self.hass.async_add_executor_job(cloud.list_3dmap_objects)
        except Exception as ex:  # noqa: BLE001
            LOGGER.warning("[LIDAR] 3dmap backfill list failed: %s", ex)
            return
        if names is None:
            return  # relay 80001 / failure — retry on the next refresh
        # The list call succeeded (possibly empty) — don't retry it this session.
        self._lidar_backfill_done = True
        if not names:
            return

        archive = self.lidar_archive_for(active_id)
        archived_names = {s.object_name for s in archive.entries()}
        new_count = 0
        for object_name in names:
            if not object_name or object_name in archived_names:
                continue
            try:
                url = await self.hass.async_add_executor_job(
                    cloud.get_interim_file_url, object_name
                )
            except Exception as ex:  # noqa: BLE001
                LOGGER.warning(
                    "[LIDAR] backfill get_interim_file_url failed for %s: %s",
                    object_name, ex,
                )
                continue
            if not url:
                continue
            try:
                raw = await self.hass.async_add_executor_job(cloud.get_file, url)
            except Exception as ex:  # noqa: BLE001
                LOGGER.warning(
                    "[LIDAR] backfill get_file failed for %s: %s", object_name, ex
                )
                continue
            if not raw:
                continue
            entry = await self.hass.async_add_executor_job(
                archive.archive, object_name, now_unix, raw
            )
            if entry is not None:
                new_count += 1
                LOGGER.info(
                    "[LIDAR] backfilled %s (%d bytes) into map %d",
                    entry.filename, entry.size_bytes, active_id,
                )
        if new_count:
            self.async_set_updated_data(
                dataclasses.replace(self.data, archived_lidar_count=archive.count)
            )
            LOGGER.info(
                "[LIDAR] 3dmap backfill: %d new scan(s) archived (map %d, total=%d)",
                new_count, active_id, archive.count,
            )

    async def _do_oss_fetch(self, now_unix: int) -> None:
        """Download + archive the cloud-summary JSON for the pending session.

        The actual work runs inside _finalize_with_latch so concurrent entries
        for the same session de-dupe (single finalize latch, P3e.4). See
        _do_oss_fetch_body for the step-by-step flow.
        """
        await self._finalize_with_latch(
            lambda: self._do_oss_fetch_body(now_unix),
            label="OSS-fetch",
        )

    async def _do_oss_fetch_body(self, now_unix: int) -> None:
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
        object_name = self.data.pending_session_object_name
        if not object_name:
            return

        # Guard: cloud client may not be ready during early boot.
        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning(
                "[F5.6.1] _do_oss_fetch: cloud client not ready; "
                "object_name=%r — will retry next tick",
                object_name,
            )
            return

        LOGGER.debug(
            "[F5.6.1] _do_oss_fetch: fetching object_name=%r (attempt #%s)",
            object_name,
            (self.data.pending_session_attempt_count or 0) + 1,
        )

        # Increment attempt count and record last_attempt_unix before the fetch
        # so retries are tracked even if the fetch hangs or raises.
        new_count = (self.data.pending_session_attempt_count or 0) + 1
        self.async_set_updated_data(
            dataclasses.replace(
                self.data,
                pending_session_attempt_count=new_count,
                pending_session_last_attempt_unix=now_unix,
            )
        )

        # Step 1: get signed URL (blocking).
        try:
            signed_url: str | None = await self.hass.async_add_executor_job(
                self._cloud.get_interim_file_url, object_name
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
            raw_bytes: bytes | None = await self.hass.async_add_executor_job(
                self._cloud.get_file, signed_url
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
            if self.novel_registry.record_key("session_summary", key, now_unix):
                LOGGER.warning(
                    "%s key=%s — JSON shape drift, parser may need an update",
                    LOG_NOVEL_KEY_SESSION_SUMMARY, key,
                )

        # v1.0.0a54+: inject locally-tracked fields (legs, WiFi samples,
        # telemetry streams, settings_snapshot) into the raw JSON before
        # archiving. Extracted into _inject_live_map_into_raw_dict so the
        # FINALIZE_INCOMPLETE path can reuse the same logic.
        self._inject_live_map_into_raw_dict(raw_dict)

        # Album photos (Patrol + AI-obstacle). [dreame-app-implementation-guide-2026-06-09.md]
        try:
            n = await self.hass.async_add_executor_job(
                lambda: fetch_photos_from_summary(
                    self._cloud, self._photo_archive, raw_dict, sign=self._photo_sign_fn
                )
            )
            if n:
                LOGGER.info("[PHOTOS] archived %d album photo(s); total=%d", n, self._photo_archive.count)
        except Exception as ex:  # noqa: BLE001 — photos never break finalize
            LOGGER.warning("[PHOTOS] fetch failed: %s", ex)

        # Recorder-merge safety net (2026-05-16 spec): fill gaps in the
        # battery/wifi sample arrays from HA's recorder history. Idempotent;
        # any failure leaves the in_progress samples untouched.
        await self._merge_recorder_into_payload(
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
        finalize_map_id = self._resolve_finalize_map_id()
        try:
            archived_entry: ArchivedSession | None = await self.hass.async_add_executor_job(
                self.session_archive.archive, summary, raw_dict, finalize_map_id
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
        self._last_session_obstacles_by_map.pop(finalize_map_id, None)
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
        await self._post_archive_reset(
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
                    if summary.map_area_m2 else self.data.total_lawn_area_m2
                ),
            },
        )

        # A session just finalized — kick a one-shot OSS gallery sync shortly
        # after, so VIDEOS and any gallery media NOT in the summary's photo_list
        # (already fetched above by fetch_photos_from_summary) appear within
        # ~seconds instead of waiting up to the 1h periodic sync. Delayed (not
        # immediate) to give the device's async upload — incl. lazy auto-capture
        # uploads, see api key session_summary_download — time to land on OSS.
        self._schedule_post_session_gallery_refresh()

    # Delay before the post-finalize gallery sync. Long enough for the device's
    # async media upload to land on OSS, short enough to beat the hourly cycle.
    _POST_SESSION_GALLERY_DELAY_S = 60

    def _schedule_post_session_gallery_refresh(self) -> None:
        """Schedule a single OSS gallery sync ``_POST_SESSION_GALLERY_DELAY_S``
        after a session finalizes. Bounded (one per finalize) and idempotent
        (``_refresh_oss_gallery`` dedups by name/id), so it is safe even if it
        overlaps the hourly sync. No-op when hass is unavailable."""
        hass = getattr(self, "hass", None)
        if hass is None:
            return

        async def _run(_now: Any) -> None:
            try:
                await self._refresh_oss_gallery()
            except Exception:  # noqa: BLE001 — a sync failure must not propagate
                LOGGER.exception("post-session OSS gallery refresh failed")

        async_call_later(hass, self._POST_SESSION_GALLERY_DELAY_S, _run)

    async def _refresh_oss_gallery(self, max_pages: int = 20) -> None:
        """Canonical OSS media sync: archive new photos (categorized via COM
        metadata) + videos, and update quota. Runs hourly + at startup (the
        per-session photo_list fetch remains the immediate session-end path).

        ``max_pages`` caps how deep ``list_oss_media`` pages into the cloud's
        media history. The hourly call uses the default (recent items, cheap);
        the boot call passes a large value (full backfill) — ``list_oss_media``
        stops at the first short page, so the cap is just a ceiling.
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            return
        import json as _json
        from datetime import datetime, timezone

        def _ts(rec):
            ut = rec.get("uploadTime")
            try:
                return int(datetime.strptime(ut, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
            except (TypeError, ValueError):
                return 0

        def _leaf(url):
            # the OSS object leaf, e.g. ".../ali_dreame/1780952775_person.jpg?Expires=..."
            base = (url or "").split("?", 1)[0]
            return base.rsplit("/", 1)[-1] if base else ""

        # --- photos ---
        photos = await self.hass.async_add_executor_job(
            lambda: self._cloud.list_oss_media("jpg", max_pages=max_pages)
        )
        for rec in (photos or []):
            name = _leaf(rec.get("filepath"))
            if not name or self._photo_archive.has_name(name):
                continue
            data = await self.hass.async_add_executor_job(self._cloud.get_file, rec.get("filepath"))
            if not data:
                continue
            # Guard against corrupt/non-JPEG downloads (observed: OSS occasionally
            # returns garbage bytes). Archiving them produces a broken thumbnail
            # in the gallery; skip so the next sync can retry cleanly.
            if data[:2] != b"\xff\xd8":
                LOGGER.warning(
                    "[PHOTOS] skipping non-JPEG download for %s (%d bytes, magic=%s)",
                    name, len(data), data[:4].hex(),
                )
                continue
            meta = photo_meta.parse_jpeg_com(data)
            is_person = name.lower().endswith("_person.jpg")
            category = categorize(name=name, record=rec, com=meta)
            detections = (meta or {}).get("detections") or []
            await self.hass.async_add_executor_job(
                lambda d=data, n=name, t=_ts(rec), ip=is_person, c=category, det=detections:
                self._photo_archive.archive(name=n, unix_ts=t, data=d, is_person=ip, category=c, detections=det))

        # --- videos ---
        videos = await self.hass.async_add_executor_job(
            lambda: self._cloud.list_oss_media("thumb", max_pages=max_pages)
        )
        for rec in (videos or []):
            vid = str(rec.get("id") or rec.get("key") or "")
            if not vid or self._video_archive.has(vid):
                continue
            thumb = await self.hass.async_add_executor_job(self._cloud.get_file, rec.get("filepath"))
            mp4 = await self.hass.async_add_executor_job(self._cloud.get_file, rec.get("videoPath"))
            if not mp4 or not thumb:
                continue
            try:
                duration = int(_json.loads(rec.get("ext") or "{}").get("duration") or 0)
            except (ValueError, TypeError):
                duration = 0
            await self.hass.async_add_executor_job(
                lambda v=vid, m=mp4, th=thumb, t=_ts(rec), du=duration:
                self._video_archive.archive(video_id=v, mp4=m, thumb=th, unix_ts=t, duration=du))

        # --- quota ---
        quota = await self.hass.async_add_executor_job(self._cloud.fetch_oss_quota)
        if quota:
            import dataclasses
            new = dataclasses.replace(self.data, oss_storage_used=quota.get("used"),
                                      oss_storage_total=quota.get("total"))
            if new != self.data:
                self.async_set_updated_data(new)

        # --- gallery manifest (newest-first, signed media URLs) ---
        self._rebuild_photo_gallery()

    def _sign_media_path(self, path: str) -> str:
        """Sign a local media API path so an ``<img>``/``<video>`` tag can load
        it without an auth header.

        ``PhotoFileView`` / ``VideoFileView`` / ``VideoThumbView`` are
        ``requires_auth = True`` (the JPEGs contain people), so the gallery card
        needs a signed URL. ``async_sign_path`` is a MODULE-LEVEL function taking
        ``hass`` first (NOT a method on ``hass.http`` — that attribute does not
        exist and raised AttributeError, leaving the manifest empty). The
        manifest is built in a background task with no request/websocket context,
        so ``use_content_user=True`` signs with HA's content user (the same path
        camera ``entity_picture`` uses) and validates for all frontend sessions.
        """
        # async_sign_path lives in http.auth and is NOT re-exported at the
        # http package level (importing from `homeassistant.components.http`
        # raises ImportError on 2026.6).
        from homeassistant.components.http.auth import async_sign_path
        return async_sign_path(
            self.hass, path, timedelta(days=7), use_content_user=True
        )

    def _rebuild_photo_gallery(self) -> None:
        """Rebuild ``self._photo_gallery`` from the photo + video archives.

        Each item is a self-describing dict the gallery card consumes — see the
        manifest shape in docs/superpowers/specs/2026-06-12-photo-gallery.md.
        URLs are signed via ``_sign_media_path`` (the module-level
        ``homeassistant.components.http.async_sign_path``, content-user signed)
        with a 7-day window; the manifest is rebuilt hourly so the signatures are
        always fresh. Wrapped in try/except so a signing or index-IO hiccup never
        breaks the OSS sync.
        """
        from datetime import datetime

        def _date(ts: int) -> str:
            try:
                return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")
            except (OverflowError, OSError, ValueError):
                return ""

        try:
            items: list[dict[str, Any]] = []
            for p in self._photo_archive.list_photos():
                url = self._sign_media_path("/api/dreame_a2_mower/photo/" + p.filename)
                items.append({
                    "type": "photo",
                    "id": p.filename,
                    "ts": int(p.unix_ts),
                    "date": _date(p.unix_ts),
                    "category": p.category,
                    "detections": p.detections or [],
                    "url": url,
                    "thumb_url": url,
                })
            for v in self._video_archive.list_videos():
                items.append({
                    "type": "video",
                    "id": v.video_id,
                    "ts": int(v.unix_ts),
                    "date": _date(v.unix_ts),
                    "category": "video",
                    "duration": int(v.duration),
                    "url": self._sign_media_path("/api/dreame_a2_mower/video/" + v.video_id),
                    "thumb_url": self._sign_media_path("/api/dreame_a2_mower/video_thumb/" + v.video_id),
                })
            items.sort(key=lambda it: it["ts"], reverse=True)
            self._photo_gallery = items
        except Exception as ex:  # noqa: BLE001 — manifest never breaks the sync
            LOGGER.warning("[PHOTOS] gallery manifest build failed: %s", ex)
        # The OSS sync runs outside the coordinator's push cycle (and the quota
        # push above fires BEFORE this rebuild), so notify entities explicitly
        # or the gallery sensor never reflects the freshly-built manifest.
        update = getattr(self, "async_update_listeners", None)
        if callable(update):
            update()
        LOGGER.debug(
            "[PHOTOS] manifest rebuilt: %d items", len(self._photo_gallery),
        )

    def session_photos_manifest(self, raw_dict: dict) -> list[dict]:
        """Signed thumbnails for ONE session's photos, for the replay screen.

        Matching is photo_list-only for now: the session summary's authoritative
        per-session filenames (covers patrol + 'to point' auto-capture). Matches
        by CAPTURE TIMESTAMP (shared by the bare `<ts>.jpg` photo_list name and the
        `<ts>_person.jpg` gallery variant) so md5-dedup storing either name still
        links. AI-obstacle photos that fall OUTSIDE photo_list are NOT included
        yet — a timestamp-window union is the planned follow-up (todo6 #6) once
        their appearance relative to photo_list is understood.

        Returns ``[{id, ts, category, detections, url, thumb_url}]`` (oldest-first)
        — the same item shape the gallery card consumes; empty on any problem.
        """
        names = raw_dict.get("photo_list") or []
        archive = getattr(self, "_photo_archive", None)
        if not isinstance(names, list) or not names or archive is None:
            return []
        by_ts: dict[int, list] = {}
        for p in archive.list_photos():
            by_ts.setdefault(int(p.unix_ts), []).append(p)
        seen: set[str] = set()
        items: list[dict] = []
        for name in names:
            if not isinstance(name, str) or not name:
                continue
            ts = int(_photo_ts_from_name(name))
            for p in by_ts.get(ts, ()):  # >1 only on same-second captures
                if p.filename in seen:
                    continue
                seen.add(p.filename)
                items.append(self._signed_photo_thumb(p))
        items.sort(key=lambda it: it["ts"])
        return items

    def _signed_photo_thumb(self, p) -> dict:
        """One archived photo → a signed gallery item dict (thumb == full URL)."""
        url = self._sign_media_path("/api/dreame_a2_mower/photo/" + p.filename)
        return {
            "id": p.filename,
            "ts": int(p.unix_ts),
            "category": p.category,
            "detections": p.detections or [],
            "url": url,
            "thumb_url": url,
        }

    # A "View snapshots in the app." notification carries no photo reference —
    # only its timestamp; the AI-detection photo lands a few seconds LATER
    # (e.g. a human-detection alert at T had its ai_human photo at T+5s,
    # app-mitm corpus 2026-06-15). So link by a timestamp window over the
    # AI-detection categories (NOT patrol, which has its own "view work log"
    # notification and its own per-session linkage).
    _SNAPSHOT_MARKER = "view snapshots"
    _SNAPSHOT_CATEGORIES = ("ai_human", "obstacle", "person")
    _SNAPSHOT_WINDOW_BEFORE_S = 120
    _SNAPSHOT_WINDOW_AFTER_S = 600

    @classmethod
    def _is_snapshot_message(cls, msg: dict) -> bool:
        return cls._SNAPSHOT_MARKER in str(msg.get("title") or "").lower()

    def link_message_snapshot_photos(self, messages: list[dict]) -> None:
        """Attach matched snapshot thumbnails (signed) to device-message dicts
        IN PLACE, as ``msg['photos']``. Messages without the "View snapshots in
        the app." marker, or with no photo in the time window, are left
        untouched (no ``photos`` key). Matching is timestamp-window over the
        AI-detection photo categories — see the class constants above."""
        archive = getattr(self, "_photo_archive", None)
        if archive is None or not messages:
            return
        if not any(self._is_snapshot_message(m) for m in messages):
            return  # avoid the archive read when nothing needs linking
        det_photos = [
            p for p in archive.list_photos()
            if p.category in self._SNAPSHOT_CATEGORIES
        ]
        if not det_photos:
            return
        for m in messages:
            if not self._is_snapshot_message(m):
                continue
            ts = _iso_to_unix(m.get("date"))
            if ts is None:
                continue
            lo = ts - self._SNAPSHOT_WINDOW_BEFORE_S
            hi = ts + self._SNAPSHOT_WINDOW_AFTER_S
            matched = sorted(
                (p for p in det_photos if lo <= int(p.unix_ts) <= hi),
                key=lambda p: int(p.unix_ts),
            )
            if matched:
                m["photos"] = [self._signed_photo_thumb(p) for p in matched]
