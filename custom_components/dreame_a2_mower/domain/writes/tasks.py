"""Task-launch write service (layer 4) — refactor-v2 P3.9b.

The typed-action dispatch (``dispatch_action``) + the unified mowing-mode
launchers (``start_mowing_*`` / ``start_go_to_point`` / ``start_*_patrol``) and
their active-map guard (``ensure_active_map``), extracted VERBATIM from
``coordinator/_writes.py``.

Each function takes the coordinator (``coord``) as its first argument; cross-
method calls stay ``coord.<method>`` so the coordinator's public/test surface +
monkeypatches (``coord.dispatch_action``, ``coord.write_setting``,
``coord._run_finalize_incomplete``) are preserved exactly.
"""
from __future__ import annotations

from typing import Any

from ...const import LOGGER
from ...cloud_client import WriteResult
from ...mower.actions import ACTION_TABLE, MowerAction


async def dispatch_action(
    coord, action: MowerAction, parameters: dict[str, Any] | None = None
) -> WriteResult:
    """Dispatch a typed mower action.

    Looks up the action in ACTION_TABLE. local_only actions are handled
    internally (currently only FINALIZE_SESSION — its actual
    implementation lands in F5). Cloud actions go via the routed path
    (s2 aiid=50) since the direct (siid, aiid) call returns 80001 on
    g2408.

    For actions that have a ``routed_o`` opcode, uses
    ``cloud_client.routed_action(op, extra)`` — the working path on g2408.
    For actions that have only ``siid``/``aiid`` (no opcode), falls back
    to a direct ``cloud_client.action(siid, aiid)`` call.

    Returns a :class:`WriteResult` carrying the honest device verdict for
    the cloud path, or a synthetic one for the local-only / cfg-toggle /
    not-ready / unknown-action / error branches. **Non-raising** — errors
    and timeouts are logged and folded into a not-accepted WriteResult so
    the integration keeps going and existing callers (which ignore the
    return value in Task A) are unaffected. Surfacing rejections to the
    user is Task B's job.
    """
    parameters = parameters or {}
    entry = ACTION_TABLE.get(action)
    if entry is None:
        LOGGER.warning("dispatch_action: unknown action %r", action)
        return WriteResult.not_delivered(f"unknown action {action!r}")

    if entry.get("local_only"):
        # FINALIZE_SESSION — integration-internal action; routes to the
        # finalize-incomplete path (F5.10.1).  Forces an "(incomplete)"
        # archive of whatever the live_map currently holds, clears
        # pending_session_* state, and calls live_map.end_session().
        # Safe to call even when no session is active (no-ops cleanly).
        if action == MowerAction.FINALIZE_SESSION:
            import time as _time
            LOGGER.info(
                "dispatch_action: FINALIZE_SESSION — running finalize-incomplete path"
            )
            await coord._run_finalize_incomplete(int(_time.time()))
        else:
            LOGGER.info(
                "dispatch_action: local-only %s — no implementation yet", action.name
            )
        # Local-only actions have no device round-trip; they always "succeed".
        return WriteResult.local_ok()

    # cfg_toggle_field path — reads the named MowerState field, computes
    # the toggled (boolean NOT) value, and calls write_setting.
    # Used for LOCK_BOT_TOGGLE → CFG key CLS.  This branch runs before
    # the cloud-client path; write_setting itself handles executor dispatch.
    cfg_toggle_field = entry.get("cfg_toggle_field")
    if cfg_toggle_field is not None:
        cfg_key = entry.get("cfg_key")
        if not cfg_key:
            LOGGER.warning(
                "dispatch_action %s: cfg_toggle_field set but cfg_key missing — skipped",
                action.name,
            )
            return WriteResult.not_delivered(
                "cfg_toggle_field set but cfg_key missing"
            )
        current = getattr(coord.data, cfg_toggle_field, None)
        toggled = not bool(current)
        LOGGER.info(
            "dispatch_action: %s toggle %s=%r → %r via write_setting(%r)",
            action.name, cfg_toggle_field, current, toggled, cfg_key,
        )
        # write_setting now returns the honest WriteResult from
        # set_cfg (P2 Task 5) — propagate it verbatim; the old synthetic
        # code=None "setting write rejected" wrapper is gone.
        return await coord.write_setting(
            cfg_key,
            int(toggled),  # CLS wire value is int {0, 1}
            field_updates={cfg_toggle_field: toggled},
        )

    if not hasattr(coord, "_cloud") or coord._cloud is None:
        LOGGER.warning("dispatch_action: cloud client not ready; %s deferred", action.name)
        return WriteResult.not_delivered("cloud not ready")

    routed_o = entry.get("routed_o")
    payload_fn = entry.get("payload_fn")

    # START_EDGE_MOW default-contour resolution. When the caller doesn't
    # specify ``contour_ids``, we want to edge every zone's outer
    # perimeter (entries in the cached map's contour table whose
    # second-int = 0). This matches the Dreame app's behaviour and
    # avoids the firmware's "edge every contour including merged
    # sub-zone seams" mode that drains the edge-mode budget on
    # invisible internal segments and triggers FTRTS.
    # See docs/research/g2408-protocol.md §4.6 (2026-05-05 finding).
    if action == MowerAction.START_EDGE_MOW and not parameters.get("contour_ids"):
        map_data = coord.cloud_state.maps_by_id.get(coord._active_map_id)
        avail = getattr(map_data, "available_contour_ids", ()) if map_data else ()
        outer = [list(cid) for cid in avail if len(cid) == 2 and cid[1] == 0]
        if outer:
            parameters = {**parameters, "contour_ids": outer}
            LOGGER.info(
                "dispatch_action: START_EDGE_MOW defaulting contour_ids to "
                "all outer perimeters %s (from %d cached contours)",
                outer, len(avail),
            )
        # else: fall through to _edge_mow_payload's [[1, 0]] last-resort
        # fallback (map data not loaded yet on this start).

    try:
        extra = payload_fn(parameters) if payload_fn else None
    except ValueError as ex:
        LOGGER.warning("dispatch_action %s: payload error: %s", action.name, ex)
        return WriteResult.not_delivered(f"payload error: {ex}")

    LOGGER.info(
        "dispatch_action: %s via routed op=%s extra=%s",
        action.name, routed_o, extra,
    )

    try:
        if routed_o is not None:
            # Action opcode path — works on g2408 (cfg_action.call_action_op).
            # routed_action already returns an honest WriteResult; propagate.
            return await coord.hass.async_add_executor_job(
                coord._cloud.routed_action, routed_o, extra
            )
        # Direct siid/aiid path — returns 80001 on g2408 for most actions,
        # but included for completeness (PAUSE/DOCK/STOP/etc. may succeed
        # via this path on some firmware or cloud configurations).
        siid = entry.get("siid")
        aiid = entry.get("aiid")
        if siid is None or aiid is None:
            LOGGER.warning(
                "dispatch_action: %s has no routed_o and no siid/aiid — skipped",
                action.name,
            )
            return WriteResult.not_delivered("no routed_o and no siid/aiid")
        # The direct action() returns the raw device dict or None — wrap it
        # into a WriteResult. We can't read out[0].r here (action() doesn't
        # carry the routed envelope), so a non-None result is treated as
        # delivered+accepted (mirrors routed_action's no-`out` branch).
        result = await coord.hass.async_add_executor_job(
            coord._cloud.action, siid, aiid
        )
        if result is None:
            return WriteResult.not_delivered("direct action not delivered")
        return WriteResult(delivered=True, accepted=True, code=None)
    except Exception as ex:
        LOGGER.warning("dispatch_action %s failed: %s", action.name, ex)
        return WriteResult.not_delivered(str(ex))


# ------------------------------------------------------------------
# Unified mowing-mode wrappers (used by DreameA2MowingModeSelect)
# ------------------------------------------------------------------


async def ensure_active_map(coord, map_id: int) -> WriteResult:
    """Switch to map_id via SET_ACTIVE_MAP (op=200) if it isn't already active.

    No-op when the requested map is already active or when
    _active_map_id is None (not yet polled — single-map devices never
    set it, so we fall through and let the firmware pick).  Logs a
    warning and continues on failure so the subsequent mow command
    still fires against whatever map is currently active.

    Returns the SET_ACTIVE_MAP dispatch result so a failed switch is
    visible to the caller; the no-op cases return an accepted result.
    """
    current = coord._active_map_id
    if current is None or current == map_id:
        return WriteResult.local_ok()
    try:
        return await coord.dispatch_action(
            MowerAction.SET_ACTIVE_MAP, {"map_id": map_id}
        )
    except Exception as ex:
        LOGGER.warning(
            "start_mowing: SET_ACTIVE_MAP(map_id=%d) failed: %s — "
            "proceeding with current active map %s",
            map_id,
            ex,
            current,
        )
        return WriteResult.not_delivered(str(ex))


async def start_mowing_all_areas(coord, *, map_id: int) -> WriteResult:
    """Start all-areas mow on the given map (op=100).

    Switches the active map first if needed.  The all-areas TASK
    envelope doesn't carry a map_id itself; op=200 SET_ACTIVE_MAP
    must be sent first when the requested map isn't already active.
    Returns the START dispatch's result.
    """
    await coord._ensure_active_map(map_id)
    return await coord.dispatch_action(MowerAction.START_MOWING, {})


async def start_mowing_edge(coord, *, map_id: int) -> WriteResult:
    """Start edge mow on the given map (op=101)."""
    await coord._ensure_active_map(map_id)
    return await coord.dispatch_action(MowerAction.START_EDGE_MOW, {})


async def start_mowing_zone(coord, *, map_id: int, zone_id: int) -> WriteResult:
    """Start zone mow for a specific zone on the given map (op=102)."""
    await coord._ensure_active_map(map_id)
    return await coord.dispatch_action(
        MowerAction.START_ZONE_MOW, {"zones": [zone_id]}
    )


async def start_mowing_spot(coord, *, map_id: int, spot_id: int) -> WriteResult:
    """Start spot mow for a specific spot on the given map (op=103)."""
    await coord._ensure_active_map(map_id)
    return await coord.dispatch_action(
        MowerAction.START_SPOT_MOW, {"spots": [spot_id]}
    )


async def start_go_to_point(coord, *, map_id: int, point_id: int) -> WriteResult:
    """Send the mower to a maintenance/clean point on the given map (op=109).

    Confirmed 2026-05-31: ``routed_action(109, {"point":[id]})``. ``point_id``
    is a per-map cleanPoint id, so the map must be active first.
    """
    await coord._ensure_active_map(map_id)
    return await coord.dispatch_action(
        MowerAction.GO_TO_POINT, {"point_id": point_id}
    )


async def start_point_patrol(coord, *, map_id: int, point_ids: list[int]) -> WriteResult:
    """Launch a POINT patrol (op=107) over the given cruise points on map_id.

    point_ids are per-map cruisePoint ids, so the map must be active first.
    SEND shape is [UNVERIFIED] — see actions._point_patrol_payload / o107.
    """
    await coord._ensure_active_map(map_id)
    return await coord.dispatch_action(
        MowerAction.START_POINT_PATROL, {"point_ids": [int(i) for i in point_ids]}
    )


async def start_edge_patrol(coord, *, map_id: int, contour_ids: list[list[int]]) -> WriteResult:
    """Launch an EDGE patrol (op=108) over the given contour pairs on map_id.

    contour_ids are [m, c] pairs (outer perimeters). SEND shape is
    [UNVERIFIED] — see actions._edge_patrol_payload / o108.
    """
    await coord._ensure_active_map(map_id)
    return await coord.dispatch_action(
        MowerAction.START_EDGE_PATROL, {"contour_ids": [list(c) for c in contour_ids]}
    )
