"""WiFi archive-camera body cache + render-entry selection (layer 4) —
refactor-v2 P3.9c.

Moved VERBATIM from ``coordinator/_lidar_oss.py`` (§4 wifi body cache + §5
map-extent). Each function takes the coordinator (``coord``) as its first
argument; the coordinator keeps thin ``_LidarOssMixin`` delegators.
"""
from __future__ import annotations


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
