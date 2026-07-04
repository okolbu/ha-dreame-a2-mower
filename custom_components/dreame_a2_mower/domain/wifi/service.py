"""WiFi archive service (layer 4) — refactor-v2 P3.9c + P3.9e.

P3.9c moved the archive-camera body cache + render-entry selection VERBATIM
from ``coordinator/_lidar_oss.py`` (§4 wifi body cache + §5 map-extent).

P3.9e consolidates the WiFi-heatmap ARCHIVE-REFRESH orchestration VERBATIM from
``coordinator/_wifi_archive.py`` (the ``_WifiArchiveMixin``) here too — the
periodic re-list, the OSS download+archive, and the RSSI-fingerprint map_id
matcher. Each function takes the coordinator (``coord``) as its first argument;
the coordinator keeps thin ``_WifiArchiveMixin`` / ``_LidarOssMixin``
delegators so the public/test surface (``coord.refresh_wifi_archive`` /
``coord._periodic_archive_refresh`` / ``coord.active_map_wifi_overlay`` /
``coord._resolve_active_map_wifi_entry`` / ``coord._schedule_active_map_wifi_load``
/ ``coord._download_and_archive_wifi`` / ``coord._read_session_wifi_samples`` /
``coord._tag_wifi_archive_map_ids``, read by ``camera/map.py`` and pinned by
``test_wifi_archive_refresh`` / ``test_active_map_wifi_overlay`` /
``test_wifi_matcher_plumbing`` / ``test_card_contract``) is unchanged. The
``_WIFI_MATCH_RECENT_SESSIONS`` cap stays a class const on ``_WifiArchiveMixin``
(read via ``coord._WIFI_MATCH_RECENT_SESSIONS`` so a test instance-override
still applies). Internal cross-method calls route through the coordinator
delegators (``coord._build_map_extents`` / ``coord._download_and_archive_wifi``
/ ``coord._tag_wifi_archive_map_ids`` / ``coord.refresh_wifi_archive`` /
``coord._backfill_lidar_from_3dmap``) so test stubs still intercept.
"""
from __future__ import annotations

from ...const import LOGGER


def get_wifi_body_cached(coord, object_name: str) -> "dict | None":
    """Return the cached decoded wifi-body for ``object_name``, or None.

    Never touches the disk; callers that need the body to be present
    should await ``_async_load_wifi_body`` first, or rely on the
    task scheduled by ``set_wifi_render_entry``.
    """
    return coord._wifi_body_cache.get(object_name)


async def async_load_wifi_body(coord, object_name: str) -> None:
    """Executor-side load of a wifi body; populates ``_wifi_body_cache``.

    Safe to call multiple times for the same object_name — the cache
    acts as a dedup guard.  After loading, notifies all listeners so
    the camera's ``available`` property re-evaluates with the new data.
    """
    store = coord.wifi_archive_store
    if store is None:
        return
    body = await coord.hass.async_add_executor_job(
        store.load_body, object_name
    )
    coord._wifi_body_cache[object_name] = body
    update_listeners = getattr(coord, "async_update_listeners", None)
    if callable(update_listeners):
        update_listeners()


def set_wifi_render_entry(coord, map_id: int | None, object_name: str | None) -> None:
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
        coord._wifi_render_entry = None
    else:
        coord._wifi_render_entry = (map_id, object_name)
        # Pre-warm the body cache if not already present.
        if object_name not in coord._wifi_body_cache:
            coord.hass.async_create_task(
                coord._async_load_wifi_body(object_name)
            )
    update_listeners = getattr(coord, "async_update_listeners", None)
    if callable(update_listeners):
        update_listeners()


def build_map_extents(coord) -> dict[int, tuple[float, float, float, float]]:
    """Build map_id → (bx1, by1, bx2, by2) in cm for all cached maps.

    Used by refresh_wifi_archive to pass geometry hints to
    cloud_client.list_wifi_candidates for cross-map heatmap matching.
    Falls back to empty dict when no maps are cached or extent fields
    are unavailable.

    Filed under the wifi domain (P3.9c decision): its SOLE consumer is
    ``coordinator/_wifi_archive.py:refresh_wifi_archive`` (heatmap→map matching
    geometry hints). It reads ``coord.cloud_state`` (coordinator state, not pure
    map data), so it cannot be a pure ``map_render`` function; it is neither
    lidar- nor render-owned, so it lives with the wifi matching it feeds.
    """
    extents: dict[int, tuple[float, float, float, float]] = {}
    for map_id, map_data in coord.cloud_state.maps_by_id.items():
        try:
            bx1 = float(getattr(map_data, "bx1", 0.0))
            by1 = float(getattr(map_data, "by1", 0.0))
            bx2 = float(getattr(map_data, "bx2", 0.0))
            by2 = float(getattr(map_data, "by2", 0.0))
            extents[map_id] = (bx1, by1, bx2, by2)
        except (TypeError, ValueError, AttributeError):
            continue
    return extents


async def periodic_archive_refresh(coord) -> None:
    """Low-frequency re-list of BOTH cloud archives (wifimap + 3dmap).

    The live update paths only fire while the integration is up and
    listening: WiFi has no MQTT push slot at all (it is poll-only), and
    LiDAR's ``s99.20`` push fires only on an app "View LiDAR Map" tap. The
    boot backfill recovers anything missed while the integration was
    *down*, but on its own a long-running integration would never notice a
    map generated mid-session. This timer closes that gap: it re-runs the
    WiFi OBJ re-list and re-arms the one-shot LiDAR ``3dmap`` backfill.
    Both are idempotent (dedup by ``object_name`` before download), so a
    re-list only downloads genuinely-new objects.
    """
    import time as _time

    # Re-arm the one-shot LiDAR backfill so the 3dmap list is re-fetched
    # (it sets the flag back to True itself once the list succeeds).
    coord._lidar_backfill_done = False
    try:
        await coord._backfill_lidar_from_3dmap(int(_time.time()))
    except Exception:
        LOGGER.exception("_periodic_archive_refresh: lidar re-list failed")
    try:
        await coord.refresh_wifi_archive()
    except Exception:
        LOGGER.exception("_periodic_archive_refresh: wifi re-list failed")


async def refresh_wifi_archive(coord) -> dict:
    """Fetch all cloud wifimap objects and archive new ones to disk.

    Idempotent: objects already on disk are skipped. Returns:
        {"fetched": int, "new": int, "archive_total": int}
    """
    import time as _time

    if coord._wifi_archive_store is None or not hasattr(coord, "_cloud"):
        return {"fetched": 0, "new": 0, "archive_total": 0}

    extents = coord._build_map_extents()
    candidates = await coord.hass.async_add_executor_job(
        lambda: coord._cloud.list_wifi_candidates(map_extents=extents)
    )
    if not isinstance(candidates, list):
        candidates = []

    new_count = 0
    now_ts = int(_time.time())
    for cand in candidates:
        obj_name = cand.get("object_name") if isinstance(cand, dict) else None
        if not isinstance(obj_name, str):
            continue
        if coord._wifi_archive_store.has_object(obj_name):
            continue
        body = await coord.hass.async_add_executor_job(
            coord._download_and_archive_wifi, obj_name, now_ts
        )
        if body is not None:
            new_count += 1

    coord._wifi_archive_index = coord._wifi_archive_store.load_index()

    # v1.0.10a6+: tag each archive entry with its best-fit map_id
    # via RSSI fingerprint match against recent session samples.
    # Runs after each refresh so newly-downloaded heatmaps get a
    # map_id immediately, AND previously-archived entries that had
    # no session samples to compare against can be retroactively
    # tagged once back-fill samples are available.
    try:
        matched = await coord.hass.async_add_executor_job(
            coord._tag_wifi_archive_map_ids
        )
        if matched:
            # Reload index so consumers see the freshly-stamped map_id.
            coord._wifi_archive_index = coord._wifi_archive_store.load_index()
    except Exception:
        LOGGER.exception("refresh_wifi_archive: fingerprint matcher failed")

    # Bound archive growth: keep newest-N per map. Runs AFTER tagging so
    # the per-map buckets are correct (pre-tag, every entry is map_id=-1).
    # No-op unless a retention cap was set at construction.
    try:
        pruned = await coord.hass.async_add_executor_job(
            coord._wifi_archive_store.enforce_retention
        )
        if pruned:
            coord._wifi_archive_index = coord._wifi_archive_store.load_index()
    except Exception:
        LOGGER.exception("refresh_wifi_archive: retention enforcement failed")

    result = "downloaded" if new_count > 0 else "no_data"
    coord._wifi_archive_last_refresh = {
        "last_attempt_unix": int(_time.time()),
        "result": result,
        "fetched": len(candidates),
        "new": new_count,
    }
    coord.async_update_listeners()

    return {
        "fetched": len(candidates),
        "new": new_count,
        "archive_total": len(coord._wifi_archive_index),
    }


# ---------- active-map overlay for the live-map card (2026-06-08) ----------


def resolve_active_map_wifi_entry(coord):
    """Newest WiFi archive entry tagged with the ACTIVE map_id, or None.

    Mirrors ``DreameA2WifiPerMapCamera._resolve_entry`` but keyed on the
    live map's active map, so the overlay always matches what the live-map
    card is showing. Returns None when no active map is set or no archived
    heatmap carries that map_id yet.
    """
    active = coord.active_map_id
    if active is None:
        return None
    index = coord.wifi_archive_index or []
    matches = [e for e in index if int(getattr(e, "map_id", -1)) == int(active)]
    if not matches:
        return None
    matches.sort(key=lambda e: int(e.unix_ts), reverse=True)
    return matches[0]


def active_map_wifi_overlay(coord) -> "dict | None":
    """Overlay payload for the active map's WiFi heatmap, or None.

    Read-only and NON-BLOCKING: returns None when the body is not yet
    cached (the camera warms the cache via
    ``_schedule_active_map_wifi_load``). cm->m conversion happens here so
    the card stays in the same metre frame as ``map_projection`` and the
    live track points.

    Payload: ``{data, width, height, resolution_m, start_x_m, start_y_m}``.
    """
    entry = coord._resolve_active_map_wifi_entry()
    if entry is None:
        return None
    body = coord._get_wifi_body_cached(entry.object_name)
    if not isinstance(body, dict):
        return None
    data = body.get("data")
    width = body.get("width")
    height = body.get("height")
    if not (isinstance(data, list) and isinstance(width, int)
            and isinstance(height, int)):
        return None
    if width <= 0 or height <= 0 or len(data) != width * height:
        return None
    try:
        resolution_m = float(body.get("resolution", 1)) or 1.0
        start_x_m = float(body.get("startX", 0)) / 100.0
        start_y_m = float(body.get("startY", 0)) / 100.0
    except (TypeError, ValueError):
        return None
    return {
        "data": data,
        "width": width,
        "height": height,
        "resolution_m": resolution_m,
        "start_x_m": start_x_m,
        "start_y_m": start_y_m,
    }


def schedule_active_map_wifi_load(coord) -> None:
    """Schedule an executor load of the active map's WiFi body if it is
    not cached yet, so the next coordinator broadcast carries the overlay.

    No-op when already cached, no entry exists, or hass is unavailable.
    Call from the event loop (e.g. an entity's coordinator-update callback); off-loop callers must wrap the schedule in ``hass.loop.call_soon_threadsafe``.
    """
    entry = coord._resolve_active_map_wifi_entry()
    if entry is None:
        return
    if coord._get_wifi_body_cached(entry.object_name) is not None:
        return
    hass = getattr(coord, "hass", None)
    if hass is None:
        return
    hass.async_create_task(coord._async_load_wifi_body(entry.object_name))


def download_and_archive_wifi(
    coord, object_name: str, first_seen_unix: int
) -> dict | None:
    """Executor-side: download body from OSS and write to disk."""
    url = coord._cloud.get_interim_file_url(object_name)
    if not url:
        return None
    raw = coord._cloud.get_file(url)
    if not raw:
        return None
    try:
        import json as _json
        body = _json.loads(raw)
    except Exception:
        return None
    if not isinstance(body, dict) or "data" not in body:
        return None
    coord._wifi_archive_store.archive(object_name, body, first_seen_unix)
    return body


# --------------- v1.0.10a6+: fingerprint matcher plumbing ---------------


def read_session_wifi_samples(
    coord, filename: str
) -> list[tuple[float, float, int, int]]:
    """Read one session blob from disk and extract wifi_samples.

    Tolerates missing / legacy blobs (no wifi_samples key, garbage
    rows). Executor-side; called from the matcher loop.
    """
    path = coord.session_archive.root / filename
    try:
        import json as _json
        body = _json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(body, dict):
        return []
    raw = body.get("wifi_samples")
    if not isinstance(raw, list):
        return []
    out: list[tuple[float, float, int, int]] = []
    for row in raw:
        try:
            out.append((float(row[0]), float(row[1]), int(row[2]), int(row[3])))
        except (TypeError, ValueError, IndexError):
            continue
    return out


def tag_wifi_archive_map_ids(coord) -> int:
    """Score each WifiArchiveEntry against the most-recent sessions
    and write back ``map_id`` when the matcher finds a winner.

    Executor-side (blocking disk reads + writes). Returns the
    number of entries whose map_id was updated.

    Strategy:
    1. Load the current archive index. Skip entries that already
       have map_id >= 0 (those were tagged on a prior refresh).
    2. Load the N most-recent finalized sessions from
       ``coord.session_archive`` and pull each session's
       wifi_samples + map_id from its on-disk blob.
    3. For each un-tagged heatmap entry, load its body, build a
       candidate list ``[(session_map_id, samples), …]``, and
       invoke ``match_heatmap_to_session``.
    4. If the matcher returns a non-None map_id, persist it via
       ``WifiArchiveStore.set_map_id``.
    """
    from ...wifi_match import match_heatmap_to_session

    store = coord._wifi_archive_store
    if store is None:
        return 0

    # Step 1: snapshot the index.
    entries = store.load_index()
    if not entries:
        return 0
    # Skip already-tagged.
    untagged = [e for e in entries if int(getattr(e, "map_id", -1)) < 0]
    if not untagged:
        return 0

    # Step 2: collect (session_map_id, samples) for recent sessions.
    try:
        coord.session_archive.load_index()
    except Exception:
        return 0
    recent_sessions = coord.session_archive.list_sessions()[
        : coord._WIFI_MATCH_RECENT_SESSIONS
    ]
    # Skip the synthesized in-progress entry (still_running=True);
    # it has no archived JSON blob to read samples from.
    session_candidates: list[
        tuple[int, list[tuple[float, float, int, int]]]
    ] = []
    for s in recent_sessions:
        if getattr(s, "still_running", False):
            continue
        sid = int(getattr(s, "map_id", -1))
        if sid < 0:
            continue
        samples = coord._read_session_wifi_samples(s.filename)
        if not samples:
            continue
        session_candidates.append((sid, samples))

    if not session_candidates:
        return 0

    # De-dup candidates by map_id while preserving sample list —
    # concatenate so a busier map gets more fingerprints than one
    # with a single session.
    merged: dict[int, list[tuple[float, float, int, int]]] = {}
    for sid, samples in session_candidates:
        merged.setdefault(sid, []).extend(samples)
    flat_candidates = list(merged.items())

    # Step 3+4: load each untagged entry's body, score, persist.
    modified = 0
    for entry in untagged:
        body = store.load_body(entry.object_name)
        if not isinstance(body, dict):
            continue
        grid = body.get("data")
        if not isinstance(grid, list):
            continue
        try:
            width = int(body.get("width", 0))
            height = int(body.get("height", 0))
            res = int(body.get("resolution", 1)) or 1
            # Cloud reports startX/startY in cm; convert to metres.
            start_x_m = float(body.get("startX", 0)) / 100.0
            start_y_m = float(body.get("startY", 0)) / 100.0
        except (TypeError, ValueError):
            continue
        map_id = match_heatmap_to_session(
            heatmap_grid=grid,
            heatmap_width=width,
            heatmap_height=height,
            heatmap_resolution_m=res,
            heatmap_start_x_m=start_x_m,
            heatmap_start_y_m=start_y_m,
            candidates=flat_candidates,
        )
        if map_id is None:
            continue
        if store.set_map_id(entry.object_name, int(map_id)):
            modified += 1
            LOGGER.info(
                "[wifi-match] tagged %s → map_id=%d "
                "(scored against %d session(s))",
                entry.object_name, map_id, len(flat_candidates),
            )
    return modified
