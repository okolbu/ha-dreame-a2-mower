"""Map-edit CRUD write service (layer 4) — refactor-v2 P3.9b.

The map-edit transaction driver (``edit_map`` — o=200/204/mutations/201 txn
ordering) + the 11 CRUD ops layered on it (``rename_zone`` / ``delete_map_object``
/ ``create_*`` / ``split_zone`` / ``merge_zones``) + the patrol-point config
dual-write (``write_patrol_point_config`` — o=111 + CRUISED with the optimistic
overlay), extracted VERBATIM from ``coordinator/_writes.py``.

Each function takes the coordinator (``coord``) as its first argument; cross-
method CRUD ops stay ``coord.edit_map(...)`` so the coordinator's public/test
surface + monkeypatches are preserved. The staggered post-commit re-fetches are
scheduled through this module's own ``async_call_later`` (tests patch
``domain.writes.map_edit.async_call_later``) so the self-cleaning timer registry
behaves identically.
"""
from __future__ import annotations

from homeassistant.helpers.event import async_call_later

from ...const import LOGGER
from ...cloud_client import WriteResult
from ..timers import schedule_self_cleaning

from .service import _accepted


async def edit_map(
    coord, map_id: int, mutations: list[tuple[int, dict | None]]
) -> WriteResult:
    """Run a map-edit transaction on `map_id`, then refresh state.

    Sequence: o=200{idx:map_id} -> o=204(p:0) begin -> each mutation(p:0)
    -> o=201(p:1) commit. The target map becomes (and stays) active. Each
    leg is sent via routed_action; the commit (o=201) is ALWAYS sent so the
    device never stays in edit mode even if an earlier leg failed.

    Returns a :class:`WriteResult` (P2 Task 5 — was a bool): accepted only
    when EVERY leg was *accepted* by the device; otherwise the FIRST
    not-accepted leg's own WriteResult (so the device's rejection code —
    e.g. r!=0 on a bad region/id — and the delivered-vs-not distinction
    survive to the surfacing layer instead of collapsing into one bool).
    """
    if not hasattr(coord, "_cloud") or coord._cloud is None:
        LOGGER.warning("edit_map: cloud client not ready")
        return WriteResult.not_delivered("cloud client not ready")

    async def _send(op, extra=None, *, p=0):
        return await coord.hass.async_add_executor_job(
            lambda: coord._cloud.routed_action(op, extra, p=p)
        )

    failure: WriteResult | None = None

    def _track(leg: WriteResult) -> None:
        nonlocal failure
        if failure is None and not leg.accepted:
            failure = leg

    async with coord._chunked_write_lock:
        _track(await _send(200, {"idx": int(map_id)}))
        _track(await _send(204))
        for op, payload in mutations:
            _track(await _send(op, payload))
        # Commit is always sent (even on prior failure) to exit edit mode.
        _track(await _send(201, p=1))
    ok = failure is None
    LOGGER.info(
        "[map-edit] map %d, %d mutation(s), ok=%s", map_id, len(mutations), ok
    )
    # Immediate refresh often grabs STALE cloud data — the mower→cloud
    # propagation of a map edit takes seconds-to-a-minute and the next
    # regular refresh is up to ~2 min away, so the edited/deleted shape
    # would linger. Run the immediate refresh anyway, then schedule a few
    # staggered DELAYED re-fetches so the integration picks up the
    # propagated change in seconds. Scheduled unconditionally — a delete
    # that "hasn't applied yet" still benefits — and outside the write
    # lock (async_call_later fires later on the event loop).
    await coord._refresh_cloud_state()
    # T3-8 + P2-inherit (P3.8): each staggered re-fetch is scheduled via a
    # SELF-CLEANING canceller registry so a reload/unload inside the 40s
    # window cancels them (never firing a refresh into a torn-down
    # coordinator) AND the config-entry's unload-listener list does not grow
    # by 3 on every edit_map call — one unload hook cancels all outstanding
    # timers, and each timer removes itself on fire. See domain/timers.py.
    for delay in (8, 20, 40):
        schedule_self_cleaning(
            coord,
            async_call_later,
            delay,
            lambda _now: coord.hass.async_create_task(
                coord._refresh_cloud_state()
            ),
        )
    return failure if failure is not None else _accepted()


async def rename_zone(coord, map_id: int, region: int, name: str) -> WriteResult:
    """Rename mowing zone `region` on `map_id` (o=219)."""
    return await coord.edit_map(
        int(map_id), [(219, {"region": int(region), "name": str(name)})]
    )


async def delete_map_object(
    coord, map_id: int, object_id: int, category: int
) -> WriteResult:
    """Delete a map object by id+category on `map_id` (o=218).

    category: 0 = zone/no-go/mow-shape, 1 = spot, 2 = patrol/cruise point,
    3 = maintenance point, 4 = ignore-obstacle (all confirmed values;
    app-mitm 2026-06-12 + 2026-06-15 patrol).
    """
    return await coord.edit_map(
        int(map_id), [(218, {"id": int(object_id), "type": int(category)})]
    )


async def create_no_go(coord, map_id, shape, points, radius=0.0, object_id=-1) -> WriteResult:
    """Create a no-go area (o=215): shape line(2pt)/polygon(>=3pt)/circle(1pt+radius>0).

    points are [x, y] meter pairs in the map edit-frame.
    object_id: -1 creates a new object; an existing id edits it in place.
    """
    from ...protocol import map_edit_shapes as _mes
    t = _mes.nogo_type(shape)
    pts = _mes.as_pairs(points)
    _mes.validate_nogo(shape, pts, radius=float(radius))
    return await coord.edit_map(int(map_id), [(215, {
        "id": int(object_id), "type": t, "points": pts, "radius": float(radius),
    })])


async def create_ignore_obstacle(coord, map_id, points, object_id=-1) -> WriteResult:
    """Create an ignore-obstacle area (o=234, polygon >=3 pt, no radius).

    object_id: -1 creates a new object; an existing id edits it in place.
    """
    from ...protocol import map_edit_shapes as _mes
    pts = _mes.as_pairs(points)
    if len(pts) < 3:
        raise ValueError(f"ignore-obstacle needs >=3 points, got {len(pts)}")
    return await coord.edit_map(int(map_id), [(234, {
        "id": int(object_id), "type": 0, "points": pts,
    })])


async def create_mow_shape(coord, map_id, shape, points, object_id=-1) -> WriteResult:
    """Create a decorative mow-shape (o=215 type 9/12-18). square=4pt, others=2pt bbox.

    object_id: -1 creates a new object; an existing id edits it in place.
    """
    from ...protocol import map_edit_shapes as _mes
    t = _mes.mow_shape_type(shape)
    pts = _mes.as_pairs(points)
    _mes.validate_mow_shape(shape, pts)
    return await coord.edit_map(int(map_id), [(215, {
        "id": int(object_id), "type": t, "points": pts, "radius": 0,
    })])


async def create_spot(coord, map_id, points, object_id=-1) -> WriteResult:
    """Create (or edit-in-place) a spot area (o=214).

    Spots are 4 axis-aligned corners — same geometry as a no-go rect, but
    their own opcode with NO type/radius/name on the wire. `points` are
    exactly four [x, y] meter pairs in the map edit-frame.
    object_id: -1 creates a new spot; an existing id edits it in place.
    Delete reuses ``delete_map_object`` with category 1.
    """
    from ...protocol import map_edit_shapes as _mes
    pts = _mes.as_pairs(points)
    if len(pts) != 4:
        raise ValueError(f"spot needs exactly 4 points, got {len(pts)}")
    return await coord.edit_map(int(map_id), [(214, {
        "id": int(object_id), "points": pts,
    })])


async def create_maintenance_point(
    coord, map_id, x, y, heading=0.0, object_id=-1
) -> WriteResult:
    """Create (or move) a maintenance / clean point (o=224).

    Wire payload is a FLAT 3-element array ``[x, y, heading]`` (NOT a
    list-of-pairs). `x`/`y` are meters in the map edit-frame; `heading` is
    in radians and defaults 0.0 (the read map carries no heading, so a MOVE
    — edit-in-place via a real object_id — resets heading to 0).
    object_id: -1 creates a new point; an existing id moves it.
    Delete reuses ``delete_map_object`` with category 3.
    """
    return await coord.edit_map(int(map_id), [(224, {
        "id": int(object_id),
        "points": [float(x), float(y), float(heading)],
    })])


async def create_patrol_point(
    coord, map_id, x, y, heading=0.0, object_id=-1
) -> WriteResult:
    """Create (or move) a patrol / cruise point (o=223).

    DISTINCT opcode from the maintenance point (o=224), though both are
    oriented points with the same FLAT 3-element wire array
    ``[x, y, heading]``. `x`/`y` are meters in the map edit-frame;
    `heading` is in radians and defaults 0.0 (the read map carries no
    heading, so a MOVE — edit-in-place via a real object_id — resets
    heading to 0). object_id: -1 creates a new point; an existing id moves
    it. Delete reuses ``delete_map_object`` with category 2.
    (wire-confirmed app-mitm 2026-06-15.)
    """
    return await coord.edit_map(int(map_id), [(223, {
        "id": int(object_id),
        "points": [float(x), float(y), float(heading)],
    })])


async def write_patrol_point_config(
    coord, *, map_id: int, point_id: int, cycles: int, auto_capture: bool
) -> WriteResult:
    """Set a patrol point's per-point cycles + auto-capture.

    DUAL-WRITE — the app sends BOTH of these for every patrol-config change,
    and CRUISED alone does NOT stick (it only updates the cloud CRUISE.0
    record; cycles never reach the device). Order matches the wire
    [app-mitm:2026-06-16 (miio-13267.jsonl, 12:26-12:31 window)]:

      1. routed_action(111, {"point":[point_id, cycles]}) -> {m:'a',p:0,
         o:111,d:{point:[id,cycles]}} — the DEVICE-APPLIED cycles write.
      2. set_cfg("CRUISED", {idx, value:[-1, point_id, auto, cycles]}) —
         the cloud-record half, read back via the CRUISE.0 device-data key
         (no m:g getter on t:CRUISED).

    o=111 carries ONLY [point_id, cycles]; auto_capture lives solely in
    CRUISED (config the device reads at patrol-run time). idx = the 0-based
    map index (== map_id, same convention as PRE). value[0]=-1 is a constant
    sentinel. See inventory.yaml § CRUISED. Returns a :class:`WriteResult`
    (P2 Task 5 — was a bool): accepted only when BOTH legs are accepted
    (out[0].r==0); otherwise the first not-accepted leg's verdict. The
    optimistic overlay + listener notify (v1.0.29a3) run exactly when they
    used to — both legs accepted — so the pending-write UX is unchanged.

    THE WRITE WORKS — it just reads back with lag. Confirmed 2026-06-17: a
    write through this path IS applied (an independent app client reflected
    x1 after an integration write), but CRUISE.0 (the cloud device-data the
    read path uses) propagates slowly, so a poll right after the write
    returns the STALE value. We do NOT need to activate the map (the
    earlier _ensure_active_map was a red herring — writes propagated on the
    build without it; it also had the side-effect of switching the active
    map on a config save). Instead we record an OPTIMISTIC pending write so
    the stale poll cannot revert the user's change — see
    _pending_cruise_writes + _apply_pending_cruise_overlay.
    """
    if int(cycles) not in (1, 2, 3):
        raise ValueError(f"cycles must be 1, 2 or 3, got {cycles!r}")
    # Leg 1: o=111 applies the cycles to the device.
    cycles_ok = await coord.hass.async_add_executor_job(
        lambda: coord._cloud.routed_action(
            111, {"point": [int(point_id), int(cycles)]}
        )
    )
    # Leg 2: CRUISED records cycles + auto_capture (cloud CRUISE.0).
    value = [-1, int(point_id), 1 if auto_capture else 0, int(cycles)]
    cruised_ok = await coord.hass.async_add_executor_job(
        coord._cloud.set_cfg, "CRUISED", {"idx": int(map_id), "value": value}
    )
    # Both legs are WriteResults now (routed_action + set_cfg); surface
    # the first not-accepted leg's honest verdict.
    if not cycles_ok.accepted:
        result = cycles_ok
    elif not cruised_ok.accepted:
        result = cruised_ok
    else:
        result = _accepted()
    ok = result.accepted
    if ok:
        # Optimistic: hold the just-written value over the laggy CRUISE.0
        # cache until a poll confirms it (or the TTL expires).
        import time as _time
        coord._pending_cruise_writes[(int(map_id), int(point_id))] = {
            "cycles": int(cycles),
            "auto_capture": bool(auto_capture),
            "ts": _time.time(),
        }
        # Reflect it immediately on the live cloud_state so the UI updates
        # now (the next refresh re-applies the overlay).
        try:
            cfg = coord.cloud_state.cruise_config_by_map.setdefault(int(map_id), {})
            cfg[int(point_id)] = {
                "cycles": int(cycles),
                "auto_capture": bool(auto_capture),
            }
        except Exception:  # noqa: BLE001 — cloud_state may be unset early
            pass
        # Push to the frontend NOW. Entities (patrol-points sensor + map
        # camera editable_objects) read cloud_state lazily on coordinator
        # update, so without this notify the optimistic value would not
        # surface until the next ~2-min poll — the exact symptom: the app
        # reflects the edit instantly while HA lags minutes.
        notify = getattr(coord, "async_update_listeners", None)
        if callable(notify):
            notify()
    return result


async def split_zone(coord, map_id, zone_id, line_start, line_end) -> WriteResult:
    """Split a zone by a line (o=220). DESTRUCTIVE: clears that zone's schedule/prefs."""
    from ...protocol import map_edit_shapes as _mes
    return await coord.edit_map(int(map_id), [(220, {
        "id": int(zone_id),
        "line_start": _mes.pair(line_start),
        "line_end": _mes.pair(line_end),
    })])


async def merge_zones(coord, map_id, ids) -> WriteResult:
    """Merge zones by id list (o=221). DESTRUCTIVE: resets merged prefs."""
    zone_ids = [int(i) for i in ids]
    if len(zone_ids) < 2:
        raise ValueError(f"merge needs >=2 zone ids, got {zone_ids}")
    return await coord.edit_map(int(map_id), [(221, {"ids": zone_ids})])
