"""LiDAR archive + fetch service (layer 4) — refactor-v2 P3.9c.

Moved VERBATIM from ``coordinator/_lidar_oss.py`` (§2 archive accessors +
object-name handling). Each function takes the coordinator (``coord``) as its
first argument; the coordinator keeps thin ``_LidarOssMixin`` delegators.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from ...archive.lidar import LidarArchive
from ...const import LOGGER


def lidar_archive_for(coord, map_id: int) -> LidarArchive:
    """Return (or lazily create) the LidarArchive for *map_id*.

    Creates a new :class:`LidarArchive` under
    ``<_lidar_archive_root>/<map_id>/`` on first access and caches it
    in :attr:`lidar_archives`.  The per-archive retention and size caps
    are inherited from the coordinator's option values.
    """
    if map_id not in coord.lidar_archives:
        coord.lidar_archives[map_id] = LidarArchive(
            coord._lidar_archive_root,
            retention=coord._lidar_archive_retention,
            max_bytes=coord._lidar_archive_max_bytes,
            map_id=map_id,
        )
    return coord.lidar_archives[map_id]


def list_lidar_archive_entries(coord) -> list[tuple[int, Any]]:
    """Aggregate all LiDAR scans across maps, newest first.

    Returns list of (map_id, ArchivedLidarScan) tuples. Used by the
    cross-map LiDAR archive picker (``select.dreame_a2_mower_lidar_archive``).
    """
    out: list[tuple[int, Any]] = []
    for map_id, archive in coord.lidar_archives.items():
        for entry in archive.entries():
            out.append((map_id, entry))
    out.sort(key=lambda x: x[1].unix_ts, reverse=True)
    return out


def set_lidar_render_entry(coord, map_id: int | None, filename: str | None) -> None:
    """Set which LiDAR scan the selected-camera renders. None resets to default."""
    if map_id is None or filename is None:
        coord._lidar_render_entry = None
    else:
        coord._lidar_render_entry = (map_id, filename)
    update_listeners = getattr(coord, "async_update_listeners", None)
    if callable(update_listeners):
        update_listeners()


async def handle_lidar_object_name(coord, object_name: str, now_unix: int) -> None:
    """Fetch and archive a LiDAR PCD scan announced via s99p20.

    Called from `_on_state_update` whenever
    `MowerState.latest_lidar_object_name` flips to a new key.
    Idempotent: caches the last-handled object_name to avoid
    re-fetching while the property re-asserts.

    Failures are logged at WARNING and swallowed — observability
    never breaks telemetry, and the user can re-trigger the upload
    from the app.
    """
    if not object_name or object_name == coord._last_lidar_object_name:
        return
    coord._last_lidar_object_name = object_name
    LOGGER.debug("[LIDAR] s99p20 announced object_name=%r", object_name)

    # T12: route to the per-map archive for the currently active map.
    active_id = coord._active_map_id
    if active_id is None:
        LOGGER.debug(
            "[LIDAR] push received but _active_map_id unknown — dropping %s",
            object_name,
        )
        return

    cloud = coord._cloud if hasattr(coord, "_cloud") else None
    if cloud is None:
        LOGGER.warning(
            "[LIDAR] fetch skipped (no cloud client): %s", object_name
        )
        return

    try:
        url = await coord.hass.async_add_executor_job(
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
        raw = await coord.hass.async_add_executor_job(cloud.get_file, url)
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

    archive = coord.lidar_archive_for(active_id)

    entry = await coord.hass.async_add_executor_job(
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
    coord.async_set_updated_data(
        dataclasses.replace(
            coord.data, archived_lidar_count=archive.count
        )
    )


async def backfill_lidar_from_3dmap(coord, now_unix: int) -> None:
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
    if coord._lidar_backfill_done:
        return
    active_id = coord._active_map_id
    if active_id is None:
        return  # defer until the active map is known (next refresh)
    cloud = coord._cloud if hasattr(coord, "_cloud") else None
    if cloud is None:
        return
    try:
        names = await coord.hass.async_add_executor_job(cloud.list_3dmap_objects)
    except Exception as ex:  # noqa: BLE001
        LOGGER.warning("[LIDAR] 3dmap backfill list failed: %s", ex)
        return
    if names is None:
        return  # relay 80001 / failure — retry on the next refresh
    # The list call succeeded (possibly empty) — don't retry it this session.
    coord._lidar_backfill_done = True
    if not names:
        return

    archive = coord.lidar_archive_for(active_id)
    archived_names = {s.object_name for s in archive.entries()}
    new_count = 0
    for object_name in names:
        if not object_name or object_name in archived_names:
            continue
        try:
            url = await coord.hass.async_add_executor_job(
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
            raw = await coord.hass.async_add_executor_job(cloud.get_file, url)
        except Exception as ex:  # noqa: BLE001
            LOGGER.warning(
                "[LIDAR] backfill get_file failed for %s: %s", object_name, ex
            )
            continue
        if not raw:
            continue
        entry = await coord.hass.async_add_executor_job(
            archive.archive, object_name, now_unix, raw
        )
        if entry is not None:
            new_count += 1
            LOGGER.info(
                "[LIDAR] backfilled %s (%d bytes) into map %d",
                entry.filename, entry.size_bytes, active_id,
            )
    if new_count:
        coord.async_set_updated_data(
            dataclasses.replace(coord.data, archived_lidar_count=archive.count)
        )
        LOGGER.info(
            "[LIDAR] 3dmap backfill: %d new scan(s) archived (map %d, total=%d)",
            new_count, active_id, archive.count,
        )
