"""rendering mixin — extracted from coordinator.py 2026-05-15.

See spec docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md.
"""
from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
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
    from ..map_render import BackgroundMode


# Backstop cap on the published live-stream snapshot mirror. The camera re-emits
# the WHOLE _track_snapshot in extra_state_attributes on every ~1Hz push, so an
# unbounded list makes per-push WebSocket cost grow with the session length —
# O(n^2) bytes over a full mow. Capping to the most-recent N rows makes per-push
# cost O(N) constant. Trade-off: a browser that JOINS mid-session seeds from this
# snapshot and so sees only the capped tail; that is fine for the LIVE map (recent
# path + current position is the point). The FULL trail is still complete two
# places this cap does not touch: client-side (continuously-connected browsers
# accumulate every latest_point delta into this._trail) and in the archive /
# work-log render (the session source-of-truth is LiveMapState.track, uncapped).
_LIVE_TRACK_SNAPSHOT_MAX = 1000


class _RenderingMixin:
    """Methods extracted from coordinator.py — see spec for groupings."""

    def _current_mower_position(self) -> tuple[float, float] | None:
        """Return the current mower (x_m, y_m) cloud-frame position, or
        None when either coordinate is unset. Used by the live-map
        renders to draw the position marker.

        P4: prefer the state-machine snapshot (persisted across reboot,
        seeded from the last session archive, and updated on every
        s1p4) over live MowerState. MowerState fields go None when
        telemetry stops, which makes the icon disappear from the map
        between sessions. The snapshot retains the last known fix so
        the icon stays put — matching what the Dreame app shows.
        """
        snap = self.state_machine.snapshot()
        sx = snap.position_x_m
        sy = snap.position_y_m
        if sx is not None and sy is not None:
            return (float(sx), float(sy))
        # Fallback to live MowerState in the rare case the snapshot is
        # somehow empty but MowerState has a fix (e.g. older persisted
        # store predating snapshot.position persistence).
        x = self.data.position_x_m
        y = self.data.position_y_m
        if x is None or y is None:
            return None
        return (float(x), float(y))

    def _compute_background_mode(self) -> "BackgroundMode":
        """BackgroundMode for the current state-machine snapshot."""
        from ..map_render import background_mode_for
        snap = self.state_machine.snapshot()
        return background_mode_for(
            mow_session=snap.mow_session,
            current_activity=snap.current_activity,
            action_mode=getattr(self.data, "action_mode", None),
        )

    def _schedule_render_base(self) -> None:
        """Schedule ``_render_base`` on the event loop, safe from ANY thread.

        HA 2026.6 made ``hass.async_create_task`` RAISE when called off the
        event loop. The MQTT message callback runs on paho's background thread,
        so a bare ``async_create_task(self._render_base())`` there raises and
        ABORTS the whole callback — taking out not just the render but any later
        processing in the same message (notably the s2p50 op-echo latch that
        sits right after the activity-transition render trigger). Always hop to
        the loop via ``call_soon_threadsafe`` first; from the loop this is a
        harmless one-tick defer (``_render_base`` is idempotent via its
        (mode, md5) dedup). See docs/TODO.md / the 2026-06-04 patrol trace.
        """
        hass = getattr(self, "hass", None)
        if hass is None:
            return
        hass.loop.call_soon_threadsafe(
            lambda: hass.async_create_task(self._render_base())
        )

    async def _render_base(self) -> None:
        """Render the active map's base PNG, keyed on (background_mode, md5).

        No-ops when neither the mode nor the map md5 changed since the last
        render. This is the ONLY server-side live-map render; trail + icon are
        client-side. Fires on every activity transition (cheap because of the
        dedup) so the stripes->green flip lands within one tick of the state
        machine entering an active activity — ~41s before the first move.
        """
        active_id = self._active_map_id
        if active_id is None:
            return
        map_data = self.cloud_state.maps_by_id.get(active_id)
        if map_data is None:
            return
        mode = self._compute_background_mode()
        md5 = getattr(map_data, "md5", None)
        if (
            self._base_png is not None
            and self._base_png_mode == mode
            and self._base_png_md5 == md5
        ):
            return  # fresh render already cached
        from ..map_render import BackgroundMode
        obstacles = (
            None if mode == BackgroundMode.GREEN
            else await self._load_last_session_obstacles(active_id)
        )
        from functools import partial
        from ..map_render import render_base
        png = await self.hass.async_add_executor_job(
            partial(
                render_base, map_data,
                background_mode=mode, state=self.data,
                map_id=active_id, obstacle_polygons_m=obstacles,
            )
        )
        if png:
            self._base_png = png
            self._base_png_mode = mode
            self._base_png_md5 = md5
            LOGGER.debug(
                "[MAP] base render: bg=%s map=%s md5=%s",
                mode.value, active_id, md5,
            )
            # Map-editor card background: same canvas (bx*/by*/width_px/height_px
            # are decode-time fields, untouched by dataclasses.replace), but with
            # the EDITABLE exclusion zones STRIPPED so the editor's overlays are
            # the ONLY place no-go/ignore line/rect/circle areas are drawn —
            # avoids the double-draw/ghosting while the device→cloud edit
            # propagation lags. DECORATIVE shapes (heart/cloud/etc., shape_type in
            # DECORATIVE_SHAPE_TYPES) are KEPT so they render in the editor base
            # pixel-identically to the live map — they are create+delete (never
            # reshaped in-place), so there is no edit-lag double-draw to avoid,
            # and the card draws only a faint select/delete hit-area over them.
            import dataclasses
            from ..map_render._shape_masks import DECORATIVE_SHAPE_TYPES
            clean_md = dataclasses.replace(
                map_data,
                exclusion_zones=tuple(
                    z for z in map_data.exclusion_zones
                    if z.shape_type in DECORATIVE_SHAPE_TYPES
                ),
            )
            editor_png = await self.hass.async_add_executor_job(
                partial(
                    render_base, clean_md,
                    background_mode=mode, state=self.data,
                    map_id=active_id, obstacle_polygons_m=obstacles,
                )
            )
            if editor_png:
                self._editor_base_png = editor_png
        # Keep the Work Log camera's empty-state CLEAN base fresh too.
        await self._render_active_map_base()

    async def _render_active_map_base(self) -> None:
        """Render the active map's CLEAN base (light lawn, no trail/icon/stripes)
        into ``_active_map_base_png``. Used as the Work Log camera's empty-state
        image. Md5-deduped — the PIL render runs at most once per map version."""
        active_id = self._active_map_id
        if active_id is None:
            return
        map_data = self.cloud_state.maps_by_id.get(active_id)
        if map_data is None:
            return
        current_md5 = getattr(map_data, "md5", None)
        if (
            self._active_map_base_png is not None
            and self._active_map_base_md5 == current_md5
        ):
            return
        from ..map_render import render_base_map
        png = await self.hass.async_add_executor_job(render_base_map, map_data)
        if png:
            self._active_map_base_png = png
            self._active_map_base_md5 = current_md5

    def _begin_live_stream(self) -> None:
        """Reset the published live stream at session begin / cold-start."""
        self._live_point_seq = 0
        self._latest_point = None
        self._track_snapshot = []

    def _publish_live_point(
        self, *, x_m: float, y_m: float, heading_deg: float | None, t: float
    ) -> None:
        """Append one position to the published live stream.

        Heading is whatever MowerState carried (the byte heading on the 99.2%
        of frames that have one; for the rare 8-byte beacon it may be slightly
        stale — acceptable, the client has a motion-vector fallback and the
        flip-convention fix is what actually fixes wrong-facing). Only the
        latest point + seq cross the wire each push; the client accumulates the
        trail. ``_track_snapshot`` is the catch-up payload for a fresh card.
        """
        pt = [float(x_m), float(y_m),
              None if heading_deg is None else float(heading_deg), float(t)]
        self._live_point_seq += 1
        self._latest_point = pt
        if self._track_snapshot is not None:
            self._track_snapshot.append(pt)
            # Bound the catch-up mirror to the most-recent N rows. Keep it a plain
            # list (not a deque): existing tests assert exact list-literal equality.
            # We append exactly one per push, so a single del trims us back to N.
            if len(self._track_snapshot) > _LIVE_TRACK_SNAPSHOT_MAX:
                del self._track_snapshot[0]
        LOGGER.debug(
            "[MAP] publish: seq=%d pt=(%.2f,%.2f) hdg=%s",
            self._live_point_seq, x_m, y_m,
            f"{heading_deg:.1f}(byte)" if heading_deg is not None else "none(vector)",
        )

    async def _load_last_session_obstacles(
        self, map_id: int
    ) -> list[list[tuple[float, float]]] | None:
        """Return the obstacle polygons from the most-recent archived
        session for ``map_id``, or ``None`` if there are none / can't load.

        Cached in ``_last_session_obstacles_by_map`` so the disk read
        only happens once per map (or after a session-finalize
        invalidation). Triangles or larger only — degenerate polygons
        with < 3 points are filtered out (mirrors the work-log replay).
        """
        cached = self._last_session_obstacles_by_map.get(map_id)
        if cached is not None:
            return cached or None

        archive = getattr(self, "session_archive", None)
        if archive is None:
            return None
        # _index is preloaded at boot — but only AFTER ``load_index()`` has
        # run (coordinator setup awaits it). Calls before that finishes
        # (e.g., the MAPL handler kicked off from the first CFG refresh)
        # see an empty ``_index`` and must NOT poison the cache with an
        # empty result. v1.0.11a1 introduced an early render task on
        # active-map change that exposed this race; gate the
        # empty-cache write on the archive being fully loaded.
        if not getattr(archive, "_index_loaded", False):
            LOGGER.info(
                "[obstacles] map_id=%d: archive index not yet loaded — skipping; "
                "next tick will retry.", map_id,
            )
            return None
        index = getattr(archive, "_index", None) or []
        candidates = [s for s in index if getattr(s, "map_id", -1) == map_id]
        if not candidates:
            # Cache the empty result so we don't re-scan on every tick.
            LOGGER.info(
                "[obstacles] map_id=%d: no archived sessions for this map_id "
                "(index has map_ids=%s).", map_id,
                sorted({s.map_id for s in index}),
            )
            self._last_session_obstacles_by_map[map_id] = []
            return None
        entry = max(candidates, key=lambda s: s.end_ts)

        raw_dict = await self.hass.async_add_executor_job(archive.load, entry)
        if raw_dict is None:
            LOGGER.info(
                "[obstacles] map_id=%d: latest session %s failed to load "
                "(archive.load() returned None).",
                map_id, getattr(entry, "filename", "?"),
            )
            self._last_session_obstacles_by_map[map_id] = []
            return None
        from ..protocol import session_summary as _session_summary
        try:
            summary = _session_summary.parse_session_summary(raw_dict)
        except _session_summary.InvalidSessionSummary as e:
            LOGGER.info(
                "[obstacles] map_id=%d: latest session %s failed to parse "
                "(InvalidSessionSummary: %s).",
                map_id, getattr(entry, "filename", "?"), str(e),
            )
            self._last_session_obstacles_by_map[map_id] = []
            return None
        polygons: list[list[tuple[float, float]]] = [
            list(o.polygon) for o in summary.obstacles if len(o.polygon) >= 3
        ]
        self._last_session_obstacles_by_map[map_id] = polygons
        if not polygons:
            LOGGER.info(
                "[obstacles] map_id=%d: latest session %s archived with "
                "0 obstacles (cloud reported none for this run).",
                map_id, getattr(entry, "filename", "?"),
            )
        return polygons or None

