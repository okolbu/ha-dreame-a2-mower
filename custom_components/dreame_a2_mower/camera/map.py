"""Map camera entities — live map, per-map static, and work-log."""
from __future__ import annotations

import hashlib
from typing import Any

from homeassistant.components.camera import Camera
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .._devices import map_device_info, map_unique_id, mower_device_info, mower_unique_id
from ..coordinator import DreameA2MowerCoordinator
from ..map_render._geometry import zone_render_points


def _zone_points_m(zone: Any) -> list[list[float]]:
    """Metre-frame edit polygon for a :class:`Zone`, derived at this boundary.

    The decoder stores raw cloud-mm corners (the ``points_m`` stored twin was
    removed in P3, T2-17); the map-editor card's edit frame is the app-rotated
    corners in metres — ``rotate_zone_points(points, -angle)/1000`` — computed
    here so the ``editable_objects`` output is byte-identical to the old stored
    ``points_m``.
    """
    return [[x / 1000.0, y / 1000.0] for (x, y) in zone_render_points(zone)]

# Version of the camera "map" attribute contract the bundled cards consume
# (map_projection / latest_point / track_snapshot / editable_objects shapes).
# Bump this integer whenever that attribute SHAPE changes so a card can detect
# a backend it doesn't understand instead of mis-rendering silently. The card
# contract is pinned in tests/integration/test_card_contract.py.
# v2: editable_objects descriptors gained "shape_type" + a richer "kind"
# (decorative shapes like "heart"/"cloud", real "line") instead of just
# "nogo"/"ignore".
# v4: editable_objects now surfaces patrol/cruise points (kind="patrol",
# op=223, delete type 2) alongside maintenance points.
# v5: patrol entries gain "cycles" (int, default 1) + "auto_capture" (bool,
# default False) sourced from CloudState.cruise_config_by_map.
MAP_ATTR_SCHEMA_VERSION = 5

# Cloud ``shapeType`` -> human ``kind`` for editable_objects descriptors. Read
# side only; covers the real LINE (1) and the decorative palette (>=9). Absent
# values fall back to the subtype-derived "nogo"/"ignore".
_SHAPE_TYPE_KIND: dict[int, str] = {
    1: "line",
    2: "nogo",
    3: "nogo",
    9: "square",
    12: "circle",
    13: "heart",
    14: "triangle",
    15: "teardrop",
    16: "mushroom",
    17: "cloud",
    18: "rainbow",
}


def _last_known_point(snapshot: Any) -> list[Any] | None:
    """``[x_m, y_m, None]`` of the mower's last persisted telemetry position,
    or ``None`` if no position has ever been recorded.

    Lets the live map card draw a STATIC idle icon at the mower's last-known
    position BETWEEN sessions (when the live point stream is empty), so it's
    clear where the mower is sitting. The third element is the last persisted
    s1p4 heading (same value the live trail uses), so the idle icon faces the
    direction the mower was last travelling — at the dock that's its nose-in
    orientation. ``None`` heading (e.g. position known via a non-telemetry path)
    leaves the card's default orientation. Known limitation: this is the last
    *telemetry* pose, so it won't reflect the mower being moved/carried manually
    while idle.
    """
    x = getattr(snapshot, "position_x_m", None)
    y = getattr(snapshot, "position_y_m", None)
    if x is None or y is None:
        return None
    h = getattr(snapshot, "position_heading_deg", None)
    return [float(x), float(y), None if h is None else float(h)]


class DreameA2MapCamera(
    CoordinatorEntity[DreameA2MowerCoordinator], Camera
):
    """Live map camera for the Dreame A2 Mower."""

    _attr_has_entity_name = True
    _attr_name = "Map"
    _attr_content_type = "image/png"
    # Keep the volatile/large live-stream attributes out of HA's recorder DB.
    # track_snapshot grows to O(thousands) of points during a mow; point_seq
    # and latest_point change on every telemetry push (~1 Hz). Persisting them
    # would generate large DB writes with no restore value.
    # NOTE: nav_paths_pt_count_by_map and settings_dual_level_diagnostic are
    # diagnostic-only attrs that are also large; calibration_points is the
    # legacy name kept here so it stays excluded if ever re-added.
    # track_snapshot length is bounded by LIVE_TRACK_SNAPSHOT_MAX in
    # coordinator/_rendering.py (decimated, not truncated).
    _unrecorded_attributes = frozenset({
        "track_snapshot", "latest_point", "point_seq", "last_known_point",
        "settings_dual_level_diagnostic", "nav_paths_pt_count_by_map",
        "calibration_points",  # legacy name; harmless if ever re-added
        "wifi_overlay",        # fixed-size cell grid; changes only on archive refresh, no restore value
    })

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        Camera.__init__(self)
        CoordinatorEntity.__init__(self, coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "map")
        self._attr_device_info = mower_device_info(coordinator)

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the current rendered base-map PNG (lawn + background only).

        Trail + mower icon are drawn client-side from the published
        position stream (see ``extra_state_attributes``).
        """
        rendered = self.coordinator._base_png
        return rendered  # may be None on first boot before map is fetched

    @property
    def entity_picture(self) -> str | None:
        """Return our custom MapImageView URL with a content-hash query param.

        HA's default `/api/camera_proxy/` response has **no `Cache-Control`
        header**, leaving caching policy to browsers. Chrome / Firefox are
        conservative; Safari is aggressive — it serves cached responses on
        re-fetch even when the URL's token query param has changed. Verified
        2026-05-05 with a 7-pick A/B test: Chrome refreshed every pick,
        Safari lagged 1 behind plus skipped the first.

        We work around this by routing the map image through a custom
        ``HomeAssistantView`` (``MapImageView``) that explicitly emits
        ``Cache-Control: no-store, max-age=0`` headers. The URL also carries
        a ``?v=<sha1[:12]>`` derived from the cached PNG bytes so each
        render produces a structurally unique URL — defence in depth in case
        a misbehaving cache ignores headers.

        Returns ``None`` when no ``_base_png`` is present (the entity
        has nothing to serve yet, e.g. immediately after boot before the
        first map fetch).
        """
        png = self.coordinator._base_png
        if not png:
            return None
        v = hashlib.sha1(png).hexdigest()[:12]
        return f"/api/dreame_a2_mower/map.png?v={v}"

    def _editable_objects_from_map(
        self,
        map_data: Any,
    ) -> list[dict]:
        """Surface the active map's exclusion objects as edit-frame descriptors.

        One dict per :class:`ExclusionZone` that carries a cloud ``obj_id``
        (id-less archive-rebuilt zones are skipped — they can't be targeted by
        an edit op). Each descriptor pairs the wire op/type with the
        meter-frame polygon (``points_m``) the map-editor card's ``projectPoint``
        consumes directly:

        - no-go / forbidden (``subtype is None``) -> op 215, type 2
        - designated-ignore (``subtype == "ignore"``) -> op 234, type 0

        ``shape_type`` (the cloud ``shapeType`` enum) and a human ``kind`` are
        carried through so the card stops mislabeling a decorative heart no-go
        as a "line": a 2-point heart (shapeType 13) reads ``kind="heart"``, a
        real no-go line (shapeType 1) ``kind="line"``, etc.
        """
        out: list[dict] = []
        for z in getattr(map_data, "exclusion_zones", ()):
            if z.obj_id is None:
                continue
            is_ignore = z.subtype == "ignore"
            shape_type = getattr(z, "shape_type", None)
            kind = _SHAPE_TYPE_KIND.get(shape_type) if shape_type is not None else None
            if kind is None:
                kind = "ignore" if is_ignore else "nogo"
            out.append(
                {
                    "id": z.obj_id,
                    "op": 234 if is_ignore else 215,
                    "type": 0 if is_ignore else 2,
                    "kind": kind,
                    "shape_type": shape_type,
                    "points_m": _zone_points_m(z),
                    "radius": 0.0,
                }
            )
        # Spots — own opcode (o=214), same 4-corner geometry as a no-go rect.
        # Surface the meter-frame corners the editor card draws + edits.
        for s in getattr(map_data, "spot_zones", ()):
            if getattr(s, "spot_id", None) is None:
                continue
            out.append(
                {
                    "id": s.spot_id,
                    "op": 214,
                    "type": 1,
                    "kind": "spot",
                    "shape_type": None,
                    "points_m": _zone_points_m(s),
                    "radius": 0.0,
                }
            )
        # Maintenance points (cleanPoints, o=224) — single-point objects. A new
        # ``point_m`` [x, y] field (metres) replaces ``points_m`` for the card's
        # point-model marker. The read map carries no heading; create defaults 0.
        for p in getattr(map_data, "maintenance_points", ()):
            if getattr(p, "point_id", None) is None:
                continue
            out.append(
                {
                    "id": p.point_id,
                    "op": 224,
                    "type": 3,
                    "kind": "maintenance",
                    "point_m": [p.x_mm / 1000.0, p.y_mm / 1000.0],
                }
            )
        # Patrol / cruise points (cruisePoints, o=223) — single-point objects,
        # DISTINCT opcode from maintenance (o=224) with delete type 2. Same
        # ``point_m`` [x, y] marker model; the read map carries no heading, so
        # create defaults 0. (wire-confirmed app-mitm 2026-06-15.)
        # ``cycles`` + ``auto_capture`` come from CloudState.cruise_config_by_map
        # (keyed by point_id); defaults 1 / False when no config is present.
        cs = getattr(self.coordinator, "cloud_state", None)
        _cruise: dict = {}
        if cs is not None:
            _cruise = getattr(cs, "cruise_config_by_map", {}).get(
                self.coordinator._active_map_id, {}
            )
        for p in getattr(map_data, "patrol_points", ()):
            if getattr(p, "point_id", None) is None:
                continue
            _pc = _cruise.get(p.point_id) or {}
            out.append(
                {
                    "id": p.point_id,
                    "op": 223,
                    "type": 2,
                    "kind": "patrol",
                    "point_m": [p.x_mm / 1000.0, p.y_mm / 1000.0],
                    "cycles": _pc.get("cycles", 1),
                    "auto_capture": _pc.get("auto_capture", False),
                }
            )
        return out

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Surface the served base PNG's hash, the map projection params
        (incl. the mower-frame ↔ pixel ``calibration_points`` the WebGL LiDAR
        card uses for its map underlay), and the live position stream the
        bundled map card uses to draw the trail + mower icon client-side.
        """
        attrs: dict[str, Any] = {"schema_version": MAP_ATTR_SCHEMA_VERSION}
        png = self.coordinator._base_png
        if png:
            attrs["image_version"] = hashlib.sha1(png).hexdigest()[:12]
        # Clean (no-exclusions) base URL for the map-editor card. The card uses
        # this as its background so no-go/ignore zones render ONLY as the
        # editable overlays — no double-draw/ghosting while a device edit is
        # still propagating to the cloud-baked image. The ?v= busts the browser
        # cache when the underlying image changes.
        editor_png = self.coordinator._editor_base_png
        if editor_png:
            attrs["editor_base_url"] = (
                "/api/dreame_a2_mower/map.png?clean=1&v="
                + hashlib.sha1(editor_png).hexdigest()[:12]
            )
        md = self.coordinator.cloud_state.maps_by_id.get(self.coordinator._active_map_id)
        if md is not None:
            try:
                attrs["map_projection"] = {
                    "bx1_mm": float(md.bx1), "by1_mm": float(md.by1),
                    "bx2_mm": float(md.bx2), "by2_mm": float(md.by2),
                    "pixel_size_mm": float(md.pixel_size_mm),
                    "width_px": int(md.width_px), "height_px": int(md.height_px),
                }
                # Mower-frame mm ↔ served-PNG-pixel calibration the bundled
                # WebGL LiDAR card affine-fits to texture the base map onto a
                # ground quad (map underlay). Renderer formula
                # (`map_render._cloud_to_px`): px = (bx2 - x_mm) / grid,
                # py = (by2 - y_mm) / grid; the renderer then flips the canvas
                # vertically before saving, so served-PNG y = (h - 1) - py.
                # Three non-collinear mower-frame points suffice for the fit.
                bx2 = float(md.bx2)
                by2 = float(md.by2)
                grid = float(md.pixel_size_mm)
                h = int(md.height_px)
                samples = ((0.0, 0.0), (1000.0, 0.0), (0.0, 1000.0))
                attrs["calibration_points"] = [
                    {
                        "mower": {"x": x_mm, "y": y_mm},
                        "map": {
                            "x": (bx2 - x_mm) / grid,
                            "y": (h - 1) - (by2 - y_mm) / grid,
                        },
                    }
                    for x_mm, y_mm in samples
                ]
            except (TypeError, ValueError, AttributeError):
                pass
            # Edit-frame exclusion descriptors for the map-editor card.
            attrs["editable_objects"] = self._editable_objects_from_map(md)
        attrs["point_seq"] = self.coordinator._live_point_seq
        attrs["latest_point"] = self.coordinator._latest_point
        attrs["track_snapshot"] = self.coordinator.live_track_snapshot()
        # Last-known position for the idle icon: the live card draws a static
        # mower icon here BETWEEN sessions (when the live stream is empty). A
        # live session's points take over on the card. See _last_known_point.
        attrs["last_known_point"] = _last_known_point(
            self.coordinator.state_machine.snapshot()
        )
        mode = self.coordinator.base_png_mode
        attrs["background_mode"] = getattr(mode, "value", None)
        # Multi-map awareness — expose active map id and name.
        active = self.coordinator._active_map_id
        if active is not None:
            current_md = self.coordinator.cloud_state.maps_by_id.get(active)
            attrs["map_id"] = active
            attrs["map_name"] = getattr(current_md, "name", None)
        attrs["available_map_ids"] = sorted(self.coordinator.cloud_state.maps_by_id.keys())
        # Diagnostic: per-map nav_paths point count (helps debug whether
        # the cloud returned `paths` data for each map). Map 2's missing
        # rendered path is likely either (a) zero data from cloud, or
        # (b) renderer didn't draw despite data — this exposes which.
        nav_paths_by_map: dict[int, int] = {}
        for mid, md in self.coordinator.cloud_state.maps_by_id.items():
            paths = getattr(md, "nav_paths", ())
            nav_paths_by_map[mid] = sum(len(p.path) for p in paths) if paths else 0
        attrs["nav_paths_pt_count_by_map"] = nav_paths_by_map
        # CloudState diagnostics — populated when cloud_state is available.
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is not None:
            active = self.coordinator._active_map_id
            if active is not None:
                fnt = cs.forbidden_node_types_by_map.get(active)
                if fnt is not None:
                    attrs["forbidden_node_types"] = fnt
            # Full SETTINGS raw list — for inspection of the dual-level structure.
            attrs["settings_dual_level_diagnostic"] = cs.settings.raw
        overlay = self.coordinator.active_map_wifi_overlay
        if overlay is not None:
            attrs["wifi_overlay"] = overlay
        return attrs

    @callback
    def _handle_coordinator_update(self) -> None:  # type: ignore[override]
        """Rotate the camera's access_token whenever the coordinator
        broadcasts new data, then push the entity state.

        HA's frontend caches the ``/api/camera_proxy/`` URL by access
        token; the base render re-renders ``_base_png`` but the
        token only changes via ``async_update_token`` which is normally
        only invoked on a 5-minute timer. Rotating it here forces an
        immediate cache-bust whenever the underlying image is replaced
        — picker click → new render → new token → frontend re-fetches.

        Note: despite the ``async_`` prefix, ``Camera.async_update_token``
        is a ``@callback`` synchronous method (HA naming convention for
        event-loop-safe, not coroutine). v1.0.0a56 wrapped it in
        ``async_create_task`` and crashed with "a coroutine was expected,
        got None" on every coordinator update. v1.0.0a57 calls it
        directly.
        """
        # Warm the active-map WiFi body cache so wifi_overlay can be published
        # on a subsequent broadcast (load is async + self-notifies on completion).
        # This callback runs on the event loop, so the bare async_create_task in
        # _schedule_active_map_wifi_load is safe here.
        self.coordinator._schedule_active_map_wifi_load()
        cur = self.coordinator._base_png
        # Rotate access_token whenever the rendered PNG bytes change so
        # the frontend immediately re-fetches the updated image.
        png_changed = cur is not None and cur != getattr(self, "_last_seen_png", None)
        if png_changed:
            self._last_seen_png = cur
            self.async_update_token()
        super()._handle_coordinator_update()


class DreameA2PerMapCamera(
    CoordinatorEntity[DreameA2MowerCoordinator], Camera
):
    """Static base-map snapshot for a single map_id.

    Read-only — no live trail overlay (those follow the active map via
    DreameA2MapCamera). Used by the bundled "Maps" dashboard view to
    show all maps side-by-side.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "map_static"

    def __init__(
        self, coordinator: DreameA2MowerCoordinator, map_id: int
    ) -> None:
        super().__init__(coordinator)
        Camera.__init__(self)
        self._map_id = map_id
        self._attr_unique_id = map_unique_id(coordinator, map_id, "map")
        map_data = coordinator.cloud_state.maps_by_id.get(map_id)
        map_name = getattr(map_data, "name", None) if map_data is not None else None
        # has_entity_name=True; device_name ("Map N+1" or the map's user-named
        # label) is prepended automatically. Setting _attr_name to a separate
        # value here on top of the device name produced the doubled
        # friendly_name "Map 1 Map 1" (verified 2026-05-14 via /api/states).
        self._attr_name = "Base"
        self._attr_device_info = map_device_info(coordinator, map_id, name=map_name)

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        return self.coordinator._static_map_pngs_by_id.get(self._map_id)

    @property
    def entity_picture(self) -> str | None:
        png = self.coordinator._static_map_pngs_by_id.get(self._map_id)
        if not png:
            return None
        v = hashlib.sha1(png).hexdigest()[:12]
        return f"/api/dreame_a2_mower/map.png?map_id={self._map_id}&v={v}"


class DreameA2WorkLogCamera(
    CoordinatorEntity[DreameA2MowerCoordinator], Camera
):
    """The Work Log camera. Independent of live state — its PNG is
    written ONLY by the work-log picker (select.dreame_a2_mower_work_log).
    Periodic refreshes never touch it.

    Returns None when no log has been picked yet (or the picker is on
    the placeholder), surfacing as "Image not available" in the UI.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "work_log"
    _attr_name = "Work Log"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        Camera.__init__(self)
        self._attr_unique_id = mower_unique_id(coordinator, "work_log")
        self._attr_device_info = mower_device_info(coordinator)

    def _resolve_png(self) -> bytes | None:
        """Pick a PNG for the camera: picked log if any, else active-map clean base.

        When no session is picked (or the user picks the placeholder to
        clear), fall back to the active map's CLEAN base render (no
        trail, no mower icon, no M_PATH) so the empty state shows
        "this is the map your work logs would render on" without
        confusing the user with cumulative mow history.
        """
        png = self.coordinator._work_log_png
        if png:
            return png
        return self.coordinator._active_map_base_png

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        return self._resolve_png()

    @property
    def entity_picture(self) -> str | None:
        png = self._resolve_png()
        if not png:
            return None
        v = hashlib.sha1(png).hexdigest()[:12]
        return f"/api/dreame_a2_mower/work_log.png?v={v}"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Rotate the camera's access_token whenever the resolved PNG changes.

        picture-entity cards use `/api/camera_proxy/<entity>?token=<at>` for
        camera entities, ignoring our custom entity_picture URL. The browser
        caches that response by token, so a fresh picker pick (which
        replaces _work_log_png) wouldn't visibly update the card until the
        next ~5-8s poll cycle. Rotating the token here changes the URL
        query param on every PNG-change, busting the cache deterministically.

        Same pattern as DreameA2MapCamera. async_update_token is a
        @callback (synchronous despite the `async_` prefix) - call it
        directly, never via async_create_task.
        """
        cur = self._resolve_png()
        if cur is not None and cur != getattr(self, "_last_seen_png", None):
            self._last_seen_png = cur
            self.async_update_token()
        super()._handle_coordinator_update()
