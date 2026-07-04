"""GPS / absolute-location refresh service (layer 4) — refactor-v2 P3.9d.

Moved VERBATIM from ``coordinator/_refreshers.py`` (the ``_refresh_gps`` cycle).
Takes the coordinator (``coord``) as its first argument; the coordinator keeps a
thin ``_RefreshersMixin._refresh_gps`` delegator.

Only the GPS refresh moved here this task — the rest of ``_refreshers.py``
(cloud_state / dock / net / remote / messages / dev / mpos / aiobs / mapl) is
coordinator poll-cycle orchestration that stays with the coordinator until 9e
dissolves ``_async_update_data``.
"""
from __future__ import annotations

import dataclasses


async def refresh_gps(coord) -> None:
    """Absolute GPS via getRecords → position_lat/lon (+ attrs).

    T3-10: ``fetch_gps`` distinguishes transient fetch failure (``None``
    — HTTP error, timeout, transport exception) from a genuine "no
    data" response (``{}`` — endpoint answered, zero records, e.g.
    Real-Time Location disabled). Only the latter clears the tracker;
    a transient failure keeps the last known fix so a single flaky
    poll doesn't flap the mower to "unknown".
    """
    if not hasattr(coord, "_cloud"):
        return
    gps = await coord.hass.async_add_executor_job(coord._cloud.fetch_gps)
    if gps is None:
        # Transient fetch failure — keep the last known fix.
        return
    if not gps:
        # Explicit empty-records response — genuine no-data, clear it.
        if (coord.data.position_lat is not None or coord.data.position_lon is not None
                or coord.data.gps_update_time is not None or coord.data.gps_card4g is not None):
            coord.async_set_updated_data(dataclasses.replace(
                coord.data, position_lat=None, position_lon=None,
                gps_update_time=None, gps_card4g=None))
        return
    new = dataclasses.replace(
        coord.data, position_lat=gps["lat"], position_lon=gps["lon"],
        gps_update_time=gps.get("update_time"), gps_card4g=gps.get("card4g"))
    if new != coord.data:
        coord.async_set_updated_data(new)
