"""rendering mixin — extracted from coordinator.py 2026-05-15.

See spec docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md.
"""
from __future__ import annotations

from typing import TYPE_CHECKING


from ..const import (
    LOGGER,
)

if TYPE_CHECKING:
    from ..map_render import BackgroundMode


# Wire budget for the cold-start backfill snapshot. The camera re-emits the WHOLE
# snapshot in extra_state_attributes on every ~5s push, so it must stay bounded.
# When the session's authoritative trail (live_map.track) exceeds this, the
# snapshot is DECIMATED (every Nth point, first + last always kept) rather than
# truncated-from-the-front — so a browser joining mid-session sees the FULL extent
# of the path at reduced resolution, not just a recent tail. A polyline at ~2000
# points is visually indistinguishable from one at 5000. The full-resolution trail
# still lives uncapped in live_map.track (the archive / work-log source of truth)
# and in continuously-connected browsers (which accumulate every latest_point).
LIVE_TRACK_SNAPSHOT_MAX = 2000


def _decimate(rows: list, max_points: int) -> list:
    """Return at most ``max_points`` (+1) rows spanning the full extent of
    ``rows``: every Nth row plus a guaranteed final row. Preserves the first and
    last points so the trail's start and its hand-off to ``latest_point`` are
    never lost. Returns a shallow copy when under budget."""
    n = len(rows)
    if n <= max_points:
        return list(rows)
    stride = -(-n // max_points)  # ceil(n / max_points)
    out = rows[::stride]
    if out[-1] is not rows[-1]:
        out.append(rows[-1])
    return out


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

    def _live_obstacle_polygons(self) -> "list[list[tuple[float, float]]]":
        """Current live AIOBS markers as render-ready polygons (metres, ≥3 pts)."""
        out = []
        for m in getattr(self, "_obstacle_markers", []) or []:
            pts = [(float(x), float(y)) for x, y in m.polygon_m]
            if len(pts) >= 3:
                out.append(pts)
        return out

    async def _render_base(self) -> None:
        """Render the active map's base PNG, keyed on (background_mode, md5, marker_fp).

        No-ops when neither the mode, the map md5, nor the live-marker count
        changed since the last render. This is the ONLY server-side live-map
        render; trail + icon are client-side. Fires on every activity
        transition (cheap because of the dedup) so the stripes->green flip
        lands within one tick of the state machine entering an active activity
        — ~41s before the first move. A new AIOBS marker also triggers a
        re-render because marker_fp changes.
        """
        active_id = self._active_map_id
        if active_id is None:
            return
        map_data = self.cloud_state.maps_by_id.get(active_id)
        if map_data is None:
            return
        mode = self._compute_background_mode()
        md5 = getattr(map_data, "md5", None)
        from ..map_render import BackgroundMode
        live = self._live_obstacle_polygons()
        if mode == BackgroundMode.GREEN:
            obstacles = live or None
        else:
            obstacles = await self._load_last_session_obstacles(active_id)
        marker_fp = hash(tuple(tuple(poly) for poly in live))
        # T3-4: settings_mowing_direction drives the STRIPES-mode stripe angle
        # (see map_render/main_view.py:_render_pre_start_with_stripes) but was
        # missing from the dedup key — a direction-only change (no mode/md5/
        # marker change) was silently deduped away, serving the stale-angle
        # PNG until an unrelated render trigger fired.
        direction = getattr(self.data, "settings_mowing_direction", None)
        if (
            self._base_png is not None
            and self._base_png_mode == mode
            and self._base_png_md5 == md5
            and getattr(self, "_base_png_marker_fp", None) == marker_fp
            and getattr(self, "_base_png_direction", None) == direction
        ):
            return  # fresh render already cached
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
            self._base_png_marker_fp = marker_fp
            self._base_png_direction = direction
            LOGGER.debug(
                "[MAP] base render: bg=%s map=%s md5=%s",
                mode.value, active_id, md5,
            )
            # Map-editor card background: same canvas (bx*/by*/width_px/height_px
            # are decode-time fields, untouched by dataclasses.replace), but the
            # editor base = LAWN + DECORATIVE shapes ONLY. Every object that the
            # card can reshape / move / delete is stripped from the server PNG and
            # drawn ONLY as a card overlay, so optimistic edit/delete works (no
            # double-draw, no bg-vs-overlay offset while the device→cloud edit
            # propagation lags):
            #   - EDITABLE exclusion zones (no-go/ignore line/rect/circle) stripped.
            #   - spot_zones / maintenance_points / patrol_points emptied — they
            #     used to be baked into the server background, so a hard refresh
            #     (which wipes the card's optimistic state) would show the stale
            #     cloud object through. Now they're card-overlay-only.
            # DECORATIVE shapes (heart/cloud/etc., shape_type in
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
                spot_zones=(),
                maintenance_points=(),
                patrol_points=(),
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
        self._track_snapshot_cache = None

    def _publish_live_point(
        self, *, x_m: float, y_m: float, heading_deg: float | None, t: float
    ) -> None:
        """Publish one position to the incremental live stream.

        Heading is whatever MowerState carried (the byte heading on the 99.2%
        of frames that have one; for the rare 8-byte beacon it may be slightly
        stale — acceptable, the client has a motion-vector fallback and the
        flip-convention fix is what actually fixes wrong-facing). Only the
        latest point + seq cross the wire each push; the client accumulates the
        trail. The cold-start backfill is served separately by
        ``live_track_snapshot`` (derived from the authoritative ``live_map.track``
        so it survives a restart) — there is no per-push mirror to maintain here.
        """
        pt = [float(x_m), float(y_m),
              None if heading_deg is None else float(heading_deg), float(t)]
        self._live_point_seq += 1
        self._latest_point = pt
        LOGGER.debug(
            "[MAP] publish: seq=%d pt=(%.2f,%.2f) hdg=%s",
            self._live_point_seq, x_m, y_m,
            f"{heading_deg:.1f}(byte)" if heading_deg is not None else "none(vector)",
        )

    def live_track_snapshot(self) -> list[list]:
        """Cold-start backfill: the session-so-far trail as ``[x_m, y_m,
        heading_deg|None, t]`` rows, in capture order.

        Derived on demand from the authoritative ``live_map.track`` (persisted
        and restored from ``in_progress.json``), so a fresh card — including one
        opened after an HA restart mid-session — repaints the whole captured path
        before resuming live painting. Decimated to ``LIVE_TRACK_SNAPSHOT_MAX``
        (first + last always kept) to bound the per-push wire cost. Cached by
        track length so repeated attribute reads between ~5s appends are free.
        """
        track = self.live_map.track
        n = len(track)
        cache = self._track_snapshot_cache
        if cache is not None and cache[0] == n:
            return cache[1]
        rows = [
            [p.x_m, p.y_m, p.heading_deg, p.t]
            for p in _decimate(track, LIVE_TRACK_SNAPSHOT_MAX)
        ]
        self._track_snapshot_cache = (n, rows)
        return rows

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

