"""Service handlers for the Dreame A2 Mower integration.

Per spec §5.2: actions live in service calls; entities should be state.
This module wires the services declared in services.yaml to the
action-dispatch helpers in mower/actions.py (built in F3.5).

The handlers are registered in __init__.py via async_setup_entry, and
unregistered in async_unload_entry.
"""
from __future__ import annotations

import dataclasses
import functools
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from . import debug
from .._experimental import experimental_features_enabled
from ..cloud_client import WriteResult
from ..const import DOMAIN, LOGGER
from ..coordinator import DreameA2MowerCoordinator
from ..coordinator._write_errors import raise_for_write_result
from ..state import ActionMode

# Service names — keep in sync with services.yaml
SERVICE_SET_ACTIVE_SELECTION = "set_active_selection"
SERVICE_MOW_ZONE = "mow_zone"
SERVICE_MOW_EDGE = "mow_edge"
SERVICE_MOW_SPOT = "mow_spot"
# recharge / find_bot / set_child_lock / finalize_session / refresh_cloud_state
# services DELETED refactor-v2 P4.2 (R-28, track-5 T5-12): each duplicated an
# existing entity press/toggle 1:1 with no params (button.recharge +
# lawn_mower.dock / button.find_my_robot / switch.child_lock /
# button.finalize_session / button.refresh_from_cloud). Automations use
# button.press / switch.turn_on. move_lidar_scan (below) also deleted — a
# one-time T12 archive-migration helper by its own description.
SERVICE_SUPPRESS_FAULT = "suppress_fault"
SERVICE_REPLAY_SESSION = "replay_session"
SERVICE_SHOW_LIDAR_FULLSCREEN = "show_lidar_fullscreen"
SERVICE_DUMP_MAP_DIAGNOSTICS = "dump_map_diagnostics"
SERVICE_DISCOVER_CLOUD_API = "discover_cloud_api"
SERVICE_SET_SCHEDULE_PLANS = "set_schedule_plans"
SERVICE_SHOW_PHOTO_PRIVACY_POLICY = "show_photo_privacy_policy"
SERVICE_START_POINT_PATROL = "start_point_patrol"
SERVICE_START_EDGE_PATROL = "start_edge_patrol"
SERVICE_RENAME_ZONE = "rename_zone"
SERVICE_DELETE_MAP_OBJECT = "delete_map_object"
SERVICE_CREATE_NO_GO_ZONE = "create_no_go_zone"
SERVICE_CREATE_IGNORE_OBSTACLE = "create_ignore_obstacle"
SERVICE_CREATE_MOW_SHAPE = "create_mow_shape"
SERVICE_CREATE_SPOT = "create_spot"
SERVICE_CREATE_MAINTENANCE_POINT = "create_maintenance_point"
SERVICE_CREATE_PATROL_POINT = "create_patrol_point"
SERVICE_SET_PATROL_POINT_CONFIG = "set_patrol_point_config"
SERVICE_SPLIT_ZONE = "split_zone"
SERVICE_MERGE_ZONES = "merge_zones"
SERVICE_SET_SCHEDULE_ENABLED = "set_schedule_enabled"


# Schemas
SCHEMA_SET_SELECTION = vol.Schema(
    {
        vol.Optional("zones", default=[]): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Optional("spots", default=[]): vol.All(cv.ensure_list, [vol.Coerce(int)]),
    }
)

SCHEMA_MOW_ZONE = vol.Schema(
    {vol.Required("zone_ids"): vol.All(cv.ensure_list, [vol.Coerce(int)])}
)

SCHEMA_MOW_EDGE = vol.Schema(
    {
        # Each entry is a [map_id, contour_id] pair as expected by the
        # routed-action TASK envelope (s2.50 op=101, d:{edge: [[m,c],...]}).
        # Empty list edges every contour in the current map.
        vol.Optional("contour_ids", default=[]): vol.All(
            cv.ensure_list, [vol.All(cv.ensure_list, [vol.Coerce(int)])]
        ),
    }
)

SCHEMA_MOW_SPOT = vol.Schema(
    {vol.Required("spot_ids"): vol.All(cv.ensure_list, [vol.Coerce(int)])}
)

SCHEMA_START_POINT_PATROL = vol.Schema(
    {
        vol.Optional("map_id"): vol.Coerce(int),
        vol.Required("point_ids"): vol.All(cv.ensure_list, [vol.Coerce(int)]),
    }
)

SCHEMA_START_EDGE_PATROL = vol.Schema(
    {
        vol.Optional("map_id"): vol.Coerce(int),
        vol.Required("contour_ids"): vol.All(
            cv.ensure_list, [vol.All(cv.ensure_list, [vol.Coerce(int)])]
        ),
    }
)

SCHEMA_EMPTY = vol.Schema({})

SCHEMA_REPLAY_SESSION = vol.Schema(
    {vol.Required("session_md5"): str}
)

SCHEMA_SET_SCHEDULE_PLANS = vol.Schema({
    vol.Required("slot_id"): vol.Coerce(int),
    vol.Required("plans"): vol.All(cv.ensure_list, [vol.Schema({
        vol.Required("time_min"): vol.All(vol.Coerce(int), vol.Range(min=0, max=1439)),
        vol.Required("weekday_mask"): vol.All(vol.Coerce(int), vol.Range(min=1, max=127)),
        vol.Required("action_type"): vol.In([0, 1, 2]),
        vol.Optional("zone_id"): vol.Any(None, vol.Coerce(int)),
        vol.Optional("extra_bytes_hex"): str,
    })]),
})

SCHEMA_SET_SCHEDULE_ENABLED = vol.Schema({
    vol.Required("slot_id"): vol.All(vol.Coerce(int), vol.In([0, 1])),
    vol.Required("enabled"): cv.boolean,
})


SCHEMA_RENAME_ZONE = vol.Schema({
    vol.Required("map_id"): vol.Coerce(int),
    vol.Required("zone"): vol.Coerce(int),
    vol.Required("name"): vol.Coerce(str),
})

SCHEMA_DELETE_MAP_OBJECT = vol.Schema({
    vol.Required("map_id"): vol.Coerce(int),
    vol.Required("object_id"): vol.Coerce(int),
    vol.Required("category"): vol.Coerce(int),
})

# Map create/split/merge schemas. Per the plan's implementer note, the
# points/line_start/line_end/zones schemas stay PERMISSIVE (accept a list);
# the real coercion/validation happens in the coordinator wrapper's
# as_pairs/validators, so a bad point raises ValueError in the wrapper, which
# the handler catches + logs (cv.string is broken in the vanilla test stub).
SCHEMA_CREATE_NO_GO_ZONE = vol.Schema({
    vol.Required("map_id"): vol.Coerce(int),
    vol.Required("shape"): vol.In(["line", "polygon", "circle"]),
    vol.Required("points"): list,
    vol.Optional("radius", default=0.0): vol.Coerce(float),
    vol.Optional("object_id", default=-1): vol.Coerce(int),
})

SCHEMA_CREATE_IGNORE_OBSTACLE = vol.Schema({
    vol.Required("map_id"): vol.Coerce(int),
    vol.Required("points"): list,
    vol.Optional("object_id", default=-1): vol.Coerce(int),
})

SCHEMA_CREATE_MOW_SHAPE = vol.Schema({
    vol.Required("map_id"): vol.Coerce(int),
    vol.Required("shape"): vol.In([
        "square", "circle", "heart", "triangle",
        "teardrop", "mushroom", "cloud", "rainbow",
        "moon", "star", "butterfly", "blob", "tree", "carrot",
    ]),
    vol.Required("points"): list,
    vol.Optional("object_id", default=-1): vol.Coerce(int),
})

SCHEMA_CREATE_SPOT = vol.Schema({
    vol.Optional("map_id"): vol.Coerce(int),
    vol.Required("points"): list,
    vol.Optional("object_id", default=-1): vol.Coerce(int),
})

SCHEMA_CREATE_MAINTENANCE_POINT = vol.Schema({
    vol.Optional("map_id"): vol.Coerce(int),
    vol.Required("x"): vol.Coerce(float),
    vol.Required("y"): vol.Coerce(float),
    vol.Optional("heading", default=0.0): vol.Coerce(float),
    vol.Optional("object_id", default=-1): vol.Coerce(int),
})

SCHEMA_CREATE_PATROL_POINT = vol.Schema({
    vol.Optional("map_id"): vol.Coerce(int),
    vol.Required("x"): vol.Coerce(float),
    vol.Required("y"): vol.Coerce(float),
    vol.Optional("heading", default=0.0): vol.Coerce(float),
    vol.Optional("object_id", default=-1): vol.Coerce(int),
})

SCHEMA_SET_PATROL_POINT_CONFIG = vol.Schema({
    vol.Optional("map_id"): vol.Coerce(int),
    vol.Required("point_id"): vol.Coerce(int),
    vol.Required("cycles"): vol.All(vol.Coerce(int), vol.In((1, 2, 3))),
    vol.Required("auto_capture"): vol.Coerce(bool),
})

SCHEMA_SPLIT_ZONE = vol.Schema({
    vol.Required("map_id"): vol.Coerce(int),
    vol.Required("zone"): vol.Coerce(int),
    vol.Required("line_start"): list,
    vol.Required("line_end"): list,
})

SCHEMA_MERGE_ZONES = vol.Schema({
    vol.Required("map_id"): vol.Coerce(int),
    vol.Required("zones"): list,
})


def _coordinator_from_call(hass: HomeAssistant, call: ServiceCall) -> DreameA2MowerCoordinator | None:
    """Resolve the (only) coordinator instance.

    Single-mower integration: there's at most one coordinator. If
    multi-mower is ever supported, the call would need to specify
    which one (e.g., via entity_id of the lawn_mower entity).
    """
    coordinators = hass.data.get(DOMAIN, {})
    if not coordinators:
        LOGGER.warning("No %s coordinator registered; service ignored", DOMAIN)
        return None
    return next(iter(coordinators.values()))


def service_handler(
    body: Callable[[DreameA2MowerCoordinator, ServiceCall], Awaitable[None]],
) -> Callable[[ServiceCall], Awaitable[None]]:
    """Wrap a service body so the 22x coordinator preamble lives in ONE place.

    The wrapped ``body`` is written as ``async def _x(coordinator, call)``: the
    decorator resolves the (single) coordinator from the call and short-circuits
    — exactly as the old ``coordinator = _coordinator_from_call(...); if
    coordinator is None: return`` boilerplate did — before invoking the body
    with the resolved coordinator.

    ``_coordinator_from_call`` is looked up through the module global at call
    time (not captured at decoration time), so tests that monkeypatch
    ``services._coordinator_from_call`` keep working.
    """

    @functools.wraps(body)
    async def handler(call: ServiceCall) -> None:
        coordinator = _coordinator_from_call(call.hass, call)
        if coordinator is None:
            return
        await body(coordinator, call)

    return handler


def experimental_service(
    body: Callable[[DreameA2MowerCoordinator, ServiceCall], Awaitable[None]],
) -> Callable[[ServiceCall], Awaitable[None]]:
    """Like :func:`service_handler` but gated on the experimental-features option
    (P4 / R-52).

    Resolves the (single) coordinator, then RAISES ``ServiceValidationError``
    with a clear "enable experimental features" message when the gate is off —
    before the body runs. The gate is read live from the coordinator's config
    entry at call time, so toggling the option takes effect on the next call (no
    reload needed for the raise-path).

    Use for FUNCTIONAL experimental services that must stay VISIBLE in the
    registry but are opt-in (e.g. create_patrol_point, populated in P4.4).
    Diagnostic services that should be HIDDEN from the registry when off use the
    not-registered-when-off path instead (see ``async_reconcile_debug_services``).
    Like ``service_handler``, a missing coordinator short-circuits to a no-op.
    """

    @functools.wraps(body)
    async def handler(call: ServiceCall) -> None:
        coordinator = _coordinator_from_call(call.hass, call)
        if coordinator is None:
            return
        if not experimental_features_enabled(getattr(coordinator, "entry", None)):
            raise ServiceValidationError(
                "This service is experimental and disabled by default. Enable "
                "'Experimental features' in the Dreame A2 Mower integration "
                "options (Settings → Devices & Services → Dreame A2 Mower → "
                "Configure) to use it."
            )
        await body(coordinator, call)

    return handler


async def _run_map_edit(
    coro: Awaitable[WriteResult], label: str, log_key: str,
) -> None:
    """Run a map-edit coroutine with the 5x identical try/except/raise shape.

    The map-edit wrappers (``create_no_go`` / ``create_ignore_obstacle`` /
    ``create_mow_shape`` / ``split_zone`` / ``merge_zones``) raise ``ValueError``
    on a bad geometry/argument — we log+swallow that (the user fixes the
    request, no traceback needed; pre-existing behaviour) — and otherwise
    return the transaction's :class:`WriteResult` (P2 Task 5 — was a bool):
    ``raise_for_write_result`` surfaces a delivered-but-rejected leg as a
    ServiceValidationError carrying the device's own code (fix the request)
    and a not-delivered transaction as a retryable HomeAssistantError.
    """
    try:
        result = await coro
    except ValueError as err:
        LOGGER.warning("%s: %s", log_key, err)
        return
    raise_for_write_result(result, label)


@service_handler
async def _handle_set_active_selection(
    coordinator: DreameA2MowerCoordinator, call: ServiceCall
) -> None:
    """Update coordinator.data.active_selection_zones / _spots."""
    zones = tuple(call.data.get("zones", []))
    spots = tuple(call.data.get("spots", []))
    new_state = dataclasses.replace(
        coordinator.data,
        active_selection_zones=zones,
        active_selection_spots=spots,
    )
    coordinator.async_set_updated_data(new_state)


@service_handler
async def _handle_mow_zone(
    coordinator: DreameA2MowerCoordinator, call: ServiceCall
) -> None:
    """Set zone selection then dispatch start_mowing in zone mode."""
    zone_ids = tuple(call.data["zone_ids"])
    new_state = dataclasses.replace(
        coordinator.data,
        action_mode=ActionMode.ZONE,
        active_selection_zones=zone_ids,
    )
    coordinator.async_set_updated_data(new_state)
    # Dispatch the actual start. Imported here to avoid circular imports.
    from ..mower.actions import MowerAction
    result = await coordinator.dispatch_action(MowerAction.START_ZONE_MOW, {"zones": list(zone_ids)})
    raise_for_write_result(result, "Mow zone")


@service_handler
async def _handle_mow_edge(
    coordinator: DreameA2MowerCoordinator, call: ServiceCall
) -> None:
    contour_ids = call.data.get("contour_ids") or []
    from ..mower.actions import MowerAction
    result = await coordinator.dispatch_action(
        MowerAction.START_EDGE_MOW, {"contour_ids": contour_ids}
    )
    raise_for_write_result(result, "Mow edge")


@service_handler
async def _handle_mow_spot(
    coordinator: DreameA2MowerCoordinator, call: ServiceCall
) -> None:
    spot_ids = tuple(int(s) for s in call.data["spot_ids"])
    if not spot_ids:
        LOGGER.warning("mow_spot: spot_ids list is empty; ignoring")
        return
    new_state = dataclasses.replace(
        coordinator.data,
        action_mode=ActionMode.SPOT,
        active_selection_spots=spot_ids,
    )
    coordinator.async_set_updated_data(new_state)
    from ..mower.actions import MowerAction
    result = await coordinator.dispatch_action(
        MowerAction.START_SPOT_MOW, {"spots": list(spot_ids)}
    )
    raise_for_write_result(result, "Mow spot")


@service_handler
async def _handle_start_point_patrol(
    coordinator: DreameA2MowerCoordinator, call: ServiceCall
) -> None:
    map_id = call.data.get("map_id")
    if map_id is None:
        map_id = coordinator.active_map_id or 0
    point_ids = list(int(p) for p in call.data["point_ids"])
    result = await coordinator.start_point_patrol(map_id=int(map_id), point_ids=point_ids)
    raise_for_write_result(result, "Start point patrol")


@service_handler
async def _handle_start_edge_patrol(
    coordinator: DreameA2MowerCoordinator, call: ServiceCall
) -> None:
    map_id = call.data.get("map_id")
    if map_id is None:
        map_id = coordinator.active_map_id or 0
    contour_ids = [list(c) for c in call.data["contour_ids"]]
    result = await coordinator.start_edge_patrol(map_id=int(map_id), contour_ids=contour_ids)
    raise_for_write_result(result, "Start edge patrol")


async def _handle_simple_action(action_name: str):
    """Factory for parameterless action handlers (recharge, find_bot, etc.)."""
    from ..mower.actions import MowerAction
    target = MowerAction[action_name]

    @service_handler
    async def handler(coordinator: DreameA2MowerCoordinator, call: ServiceCall) -> None:
        result = await coordinator.dispatch_action(target, {})
        # FINALIZE_SESSION is local-only (always accepted) so it never raises;
        # the others surface a device rejection / undelivered command.
        raise_for_write_result(result, target.name.replace("_", " ").title())

    return handler



@service_handler
async def _handle_replay_session(
    coordinator: DreameA2MowerCoordinator, call: ServiceCall
) -> None:
    """Look up an archived session by md5 and render it into _work_log_png."""
    md5 = call.data["session_md5"].strip()
    await coordinator.replay_session(md5)


@service_handler
async def _handle_set_schedule_plans(
    coordinator: DreameA2MowerCoordinator, call: ServiceCall
) -> None:
    """Replace one slot's full plan list, leave other slots untouched.

    Card-side flow: card holds the working set locally as the user edits;
    on Save it calls this service with the complete new plan list for ONE
    slot. The coordinator does the cloud round-trip; on success the next
    cloud refresh updates sensor attrs which the card re-reads.
    """
    from ..state.cloud_state import SchedulePlan, ScheduleSlot

    cs = getattr(coordinator, "cloud_state", None)
    if cs is None:
        LOGGER.warning("set_schedule_plans: cloud_state not yet populated")
        return
    target_slot_id = int(call.data["slot_id"])
    new_plan_dicts = call.data["plans"]
    new_plans = tuple(
        SchedulePlan(
            time_min=int(p["time_min"]),
            weekday_mask=int(p["weekday_mask"]),
            action_type=int(p["action_type"]),
            zone_id=p.get("zone_id"),
            extra_bytes=bytes.fromhex(p["extra_bytes_hex"]) if p.get("extra_bytes_hex") else b"",
        )
        for p in new_plan_dicts
    )
    new_slots = []
    found = False
    for slot in cs.schedule.slots:
        if slot.slot_id == target_slot_id:
            new_slots.append(ScheduleSlot(
                slot_id=slot.slot_id,
                name=slot.name,
                raw_blob_b64="",
                plans=new_plans,
                # Preserve the slot's active/empty flag — the cloud emits 1
                # for the primary slot and 0 for an empty one; if we
                # hardcoded 0 here we'd silently turn an active slot off.
                mode=slot.mode,
            ))
            found = True
        else:
            new_slots.append(slot)
    if not found:
        # New slot inserted by the user. Default mode=1 (active) since the
        # caller is creating a slot that has plans — an empty slot would
        # not be created via this service. Empty/secondary slots are left
        # at the default mode=0 in cloud_state.ScheduleSlot.
        default_mode = 1 if new_plans else 0
        new_slots.append(ScheduleSlot(
            slot_id=target_slot_id, name="", raw_blob_b64="",
            plans=new_plans, mode=default_mode,
        ))
    result = await coordinator.write_schedule(new_slots)
    LOGGER.info(
        "set_schedule_plans: slot %d, %d plan(s), accepted=%s",
        target_slot_id, len(new_plans), result.accepted,
    )
    # P2 Task 5: surface the honest verdict — a device rejection (SCHD*V3 leg
    # r!=0) raises ServiceValidationError with the code; a transport drop
    # raises the retryable HomeAssistantError.
    raise_for_write_result(result, "Set schedule plans")


@service_handler
async def _handle_set_schedule_enabled(
    coordinator: DreameA2MowerCoordinator, call: ServiceCall
) -> None:
    """Enable/disable one schedule season (mutually exclusive). Blocked while a
    mow session is active — the Dreame app forbids this mid-task; we replicate
    the guard (the mower's mid-task behavior is untested)."""
    from ..state.snapshot import MowSession

    sm = getattr(coordinator, "state_machine", None)
    if sm is not None and sm.snapshot().mow_session == MowSession.IN_SESSION:
        raise ServiceValidationError(
            "End the current mowing task before changing a schedule's on/off state."
        )
    slot_id = int(call.data["slot_id"])
    enabled = bool(call.data["enabled"])
    result = await coordinator.write_schedule_enabled(slot_id=slot_id, enabled=enabled)
    LOGGER.info(
        "set_schedule_enabled: slot %d -> %s, accepted=%s",
        slot_id, "on" if enabled else "off", result.accepted,
    )
    raise_for_write_result(result, "Set schedule enabled")


async def _handle_show_lidar_fullscreen(call: ServiceCall) -> None:
    """Fire a bus event a Lovelace card can listen for to pop up the
    full-resolution LiDAR view. The handler accepts no parameters today;
    the convention exists for future extensibility (e.g. a specific
    archived md5 to display)."""
    call.hass.bus.async_fire("dreame_a2_mower_lidar_fullscreen", {})


# ---------------------------------------------------------------------------
# Debug / discovery services (moved to services/debug.py, P3.8 — autopsy #5).
# The bodies live in the isolated debug module; the @service_handler wrapper
# (coordinator resolution) is applied HERE so debug.py has no back-import into
# the package. Registered ONLY when _debug_services_enabled(entry) is true.
# ---------------------------------------------------------------------------
_handle_dump_map_diagnostics = service_handler(debug.dump_map_diagnostics)
_async_handle_discover_cloud_api = service_handler(debug.discover_cloud_api)


async def _handle_show_photo_privacy_policy(call: ServiceCall) -> None:
    """Surface the verbatim Dreame "AI Obstacle Recognition Privacy Policy"
    text as an HA persistent_notification.

    The policy is the gate behind the in-app *Privacy Policy for
    Capturing and Transmitting Photos* sub-menu. The integration cannot
    accept it on the user's behalf — REC writes return r=-3 on this
    firmware, and a privacy policy that flips without an explicit
    accept-screen would be a UX bug. This service exists so the policy
    text is reviewable from inside HA without opening the Dreame app.

    The notification is dismissable via the bell icon. The acceptance
    state itself is surfaced read-only at
    `binary_sensor.dreame_a2_mower_photo_consent` (CFG.REC[7]).
    """
    # Imported lazily — `homeassistant.components.*` isn't available in
    # the test environment that stubs only `homeassistant.const`.
    from homeassistant.components.persistent_notification import (
        async_create as async_create_notification,
    )
    policy_path = Path(__file__).parent / "data" / "privacy_policy_photo.md"
    try:
        text = await call.hass.async_add_executor_job(policy_path.read_text)
    except OSError as ex:
        LOGGER.warning("show_photo_privacy_policy: %s not readable: %s", policy_path, ex)
        return
    async_create_notification(
        call.hass,
        text,
        title="Dreame A2 — AI Photo Capture Privacy Policy",
        notification_id="dreame_a2_mower_photo_privacy_policy",
    )


# _handle_refresh_cloud_state + _async_move_lidar_scan handlers DELETED
# refactor-v2 P4.2 (R-28, track-5 T5-12): refresh_cloud_state duplicated
# button.refresh_from_cloud 1:1; move_lidar_scan was a one-time archive-migration
# helper. See the SERVICE_* deletion note above.


@service_handler
async def _handle_rename_zone(
    coordinator: DreameA2MowerCoordinator, call: ServiceCall
) -> None:
    """Rename a mowing zone on a map (o=219)."""
    result = await coordinator.rename_zone(
        int(call.data["map_id"]), int(call.data["zone"]), str(call.data["name"])
    )
    raise_for_write_result(result, "Rename zone")


@service_handler
async def _handle_delete_map_object(
    coordinator: DreameA2MowerCoordinator, call: ServiceCall
) -> None:
    """Delete a map object by id+category (o=218; 0=zone/no-go/mow, 1=spot, 2=patrol, 3=maintenance, 4=ignore)."""
    result = await coordinator.delete_map_object(
        int(call.data["map_id"]),
        int(call.data["object_id"]),
        int(call.data["category"]),
    )
    raise_for_write_result(result, "Delete map object")


@service_handler
async def _handle_create_no_go_zone(
    coordinator: DreameA2MowerCoordinator, call: ServiceCall
) -> None:
    """Create a no-go area / virtual wall on a map (o=215). Coords = edit-frame metres."""
    await _run_map_edit(
        coordinator.create_no_go(
            int(call.data["map_id"]), call.data["shape"],
            call.data["points"], float(call.data.get("radius", 0.0)),
            object_id=int(call.data.get("object_id", -1)),
        ),
        "Create no-go zone", "create_no_go_zone",
    )


@service_handler
async def _handle_create_ignore_obstacle(
    coordinator: DreameA2MowerCoordinator, call: ServiceCall
) -> None:
    """Create an ignore-obstacle area on a map (o=234, polygon >=3 pt)."""
    await _run_map_edit(
        coordinator.create_ignore_obstacle(
            int(call.data["map_id"]), call.data["points"],
            object_id=int(call.data.get("object_id", -1)),
        ),
        "Create ignore obstacle", "create_ignore_obstacle",
    )


@service_handler
async def _handle_create_mow_shape(
    coordinator: DreameA2MowerCoordinator, call: ServiceCall
) -> None:
    """Create a decorative mow-shape on a map (o=215 type 9/12-18)."""
    await _run_map_edit(
        coordinator.create_mow_shape(
            int(call.data["map_id"]), call.data["shape"], call.data["points"],
            object_id=int(call.data.get("object_id", -1)),
        ),
        "Create mow shape", "create_mow_shape",
    )


@service_handler
async def _handle_create_spot(
    coordinator: DreameA2MowerCoordinator, call: ServiceCall
) -> None:
    """Create (or edit-in-place) a spot area on a map (o=214, 4 corner metres)."""
    map_id = call.data.get("map_id")
    if map_id is None:
        map_id = coordinator.active_map_id or 0
    await _run_map_edit(
        coordinator.create_spot(
            int(map_id), call.data["points"],
            object_id=int(call.data.get("object_id", -1)),
        ),
        "Create spot", "create_spot",
    )


@service_handler
async def _handle_create_maintenance_point(
    coordinator: DreameA2MowerCoordinator, call: ServiceCall
) -> None:
    """Create (or move) a maintenance / clean point on a map (o=224)."""
    map_id = call.data.get("map_id")
    if map_id is None:
        map_id = coordinator.active_map_id or 0
    await _run_map_edit(
        coordinator.create_maintenance_point(
            int(map_id), float(call.data["x"]), float(call.data["y"]),
            heading=float(call.data.get("heading", 0.0)),
            object_id=int(call.data.get("object_id", -1)),
        ),
        "Create maintenance point", "create_maintenance_point",
    )


@service_handler
async def _handle_create_patrol_point(
    coordinator: DreameA2MowerCoordinator, call: ServiceCall
) -> None:
    """Create (or move) a patrol / cruise point on a map (o=223)."""
    map_id = call.data.get("map_id")
    if map_id is None:
        map_id = coordinator.active_map_id or 0
    await _run_map_edit(
        coordinator.create_patrol_point(
            int(map_id), float(call.data["x"]), float(call.data["y"]),
            heading=float(call.data.get("heading", 0.0)),
            object_id=int(call.data.get("object_id", -1)),
        ),
        "Create patrol point", "create_patrol_point",
    )


@service_handler
async def _handle_set_patrol_point_config(
    coordinator: DreameA2MowerCoordinator, call: ServiceCall
) -> None:
    """Set a patrol point's cycles + auto-capture (CRUISED CFG write)."""
    map_id = call.data.get("map_id")
    if map_id is None:
        map_id = coordinator.active_map_id or 0
    try:
        result = await coordinator.write_patrol_point_config(
            map_id=int(map_id),
            point_id=int(call.data["point_id"]),
            cycles=int(call.data["cycles"]),
            auto_capture=bool(call.data["auto_capture"]),
        )
    except ValueError as err:
        raise ServiceValidationError(f"set_patrol_point_config: {err}") from err
    raise_for_write_result(result, "Set patrol point config")


@service_handler
async def _handle_split_zone(
    coordinator: DreameA2MowerCoordinator, call: ServiceCall
) -> None:
    """Split a zone by a line (o=220). DESTRUCTIVE: clears that zone's schedule/prefs."""
    await _run_map_edit(
        coordinator.split_zone(
            int(call.data["map_id"]), int(call.data["zone"]),
            call.data["line_start"], call.data["line_end"],
        ),
        "Split zone", "split_zone",
    )


@service_handler
async def _handle_merge_zones(
    coordinator: DreameA2MowerCoordinator, call: ServiceCall
) -> None:
    """Merge zones by id list (o=221). DESTRUCTIVE: resets merged prefs."""
    await _run_map_edit(
        coordinator.merge_zones(int(call.data["map_id"]), call.data["zones"]),
        "Merge zones", "merge_zones",
    )


# The two developer-only diagnostic services. Gated OFF by default behind the
# UNIFIED ``experimental_features`` config-entry option (P4 / R-52; the former
# ``debug_services`` option is absorbed — see _debug_services_enabled): when the
# gate is off they are NEVER registered, so they don't appear in the HA service
# registry (hiding diagnostic services is intentional UX — functional gated
# services use experimental_service's raise-when-off path instead). They still
# ship in services.yaml so their descriptions are available when enabled.
_DEBUG_SERVICES = (SERVICE_DUMP_MAP_DIAGNOSTICS, SERVICE_DISCOVER_CLOUD_API)


def _debug_services_enabled(entry: Any | None) -> bool:
    """Whether the debug-only diagnostic services should be registered.

    P4 / R-52: the debug services are now gated on the UNIFIED
    ``experimental_features`` option. Delegates to
    ``experimental_features_enabled``, which reads ``experimental_features``
    (default False) and also honours a legacy ``debug_services=True`` option for
    backward-compat. When no entry is supplied the gate stays OFF (safe default).
    """
    return experimental_features_enabled(entry)


async def async_register_services(hass: HomeAssistant, entry: Any | None = None) -> None:
    """Register all the integration's service handlers.

    ``entry`` (the config entry) is optional; when supplied it gates the two
    debug-only services behind its ``debug_services`` option. When omitted the
    debug services are not registered.
    """
    hass.services.async_register(DOMAIN, SERVICE_SET_ACTIVE_SELECTION,
                                  _handle_set_active_selection, schema=SCHEMA_SET_SELECTION)
    hass.services.async_register(DOMAIN, SERVICE_MOW_ZONE,
                                  _handle_mow_zone, schema=SCHEMA_MOW_ZONE)
    hass.services.async_register(DOMAIN, SERVICE_MOW_EDGE,
                                  _handle_mow_edge, schema=SCHEMA_MOW_EDGE)
    hass.services.async_register(DOMAIN, SERVICE_MOW_SPOT,
                                  _handle_mow_spot, schema=SCHEMA_MOW_SPOT)
    hass.services.async_register(DOMAIN, SERVICE_SUPPRESS_FAULT,
                                  await _handle_simple_action("SUPPRESS_FAULT"), schema=SCHEMA_EMPTY)
    hass.services.async_register(DOMAIN, SERVICE_REPLAY_SESSION,
                                  _handle_replay_session, schema=SCHEMA_REPLAY_SESSION)
    hass.services.async_register(DOMAIN, SERVICE_SET_SCHEDULE_PLANS,
                                  _handle_set_schedule_plans, schema=SCHEMA_SET_SCHEDULE_PLANS)
    hass.services.async_register(DOMAIN, SERVICE_SET_SCHEDULE_ENABLED,
                                  _handle_set_schedule_enabled, schema=SCHEMA_SET_SCHEDULE_ENABLED)
    hass.services.async_register(DOMAIN, SERVICE_SHOW_LIDAR_FULLSCREEN,
                                  _handle_show_lidar_fullscreen, schema=SCHEMA_EMPTY)
    # Debug-only services: registered ONLY when the debug_services option is on.
    if _debug_services_enabled(entry):
        hass.services.async_register(DOMAIN, SERVICE_DUMP_MAP_DIAGNOSTICS,
                                      _handle_dump_map_diagnostics, schema=SCHEMA_EMPTY)
        hass.services.async_register(DOMAIN, SERVICE_DISCOVER_CLOUD_API,
                                      _async_handle_discover_cloud_api, schema=SCHEMA_EMPTY)
    hass.services.async_register(DOMAIN, SERVICE_SHOW_PHOTO_PRIVACY_POLICY,
                                  _handle_show_photo_privacy_policy, schema=SCHEMA_EMPTY)
    hass.services.async_register(DOMAIN, SERVICE_START_POINT_PATROL,
                                  _handle_start_point_patrol, schema=SCHEMA_START_POINT_PATROL)
    hass.services.async_register(DOMAIN, SERVICE_START_EDGE_PATROL,
                                  _handle_start_edge_patrol, schema=SCHEMA_START_EDGE_PATROL)
    hass.services.async_register(DOMAIN, SERVICE_RENAME_ZONE,
                                  _handle_rename_zone, schema=SCHEMA_RENAME_ZONE)
    hass.services.async_register(DOMAIN, SERVICE_DELETE_MAP_OBJECT,
                                  _handle_delete_map_object, schema=SCHEMA_DELETE_MAP_OBJECT)
    hass.services.async_register(DOMAIN, SERVICE_CREATE_NO_GO_ZONE,
                                  _handle_create_no_go_zone, schema=SCHEMA_CREATE_NO_GO_ZONE)
    hass.services.async_register(DOMAIN, SERVICE_CREATE_IGNORE_OBSTACLE,
                                  _handle_create_ignore_obstacle, schema=SCHEMA_CREATE_IGNORE_OBSTACLE)
    hass.services.async_register(DOMAIN, SERVICE_CREATE_MOW_SHAPE,
                                  _handle_create_mow_shape, schema=SCHEMA_CREATE_MOW_SHAPE)
    hass.services.async_register(DOMAIN, SERVICE_CREATE_SPOT,
                                  _handle_create_spot, schema=SCHEMA_CREATE_SPOT)
    hass.services.async_register(DOMAIN, SERVICE_CREATE_MAINTENANCE_POINT,
                                  _handle_create_maintenance_point, schema=SCHEMA_CREATE_MAINTENANCE_POINT)
    hass.services.async_register(DOMAIN, SERVICE_CREATE_PATROL_POINT,
                                  _handle_create_patrol_point, schema=SCHEMA_CREATE_PATROL_POINT)
    hass.services.async_register(DOMAIN, SERVICE_SET_PATROL_POINT_CONFIG,
                                  _handle_set_patrol_point_config, schema=SCHEMA_SET_PATROL_POINT_CONFIG)
    hass.services.async_register(DOMAIN, SERVICE_SPLIT_ZONE,
                                  _handle_split_zone, schema=SCHEMA_SPLIT_ZONE)
    hass.services.async_register(DOMAIN, SERVICE_MERGE_ZONES,
                                  _handle_merge_zones, schema=SCHEMA_MERGE_ZONES)


def async_reconcile_debug_services(hass: HomeAssistant, entry: Any | None = None) -> None:
    """Add/remove the debug-only services to match the current option state.

    Called on each setup/reload when the bulk services are already registered
    (process-wide), so flipping the ``debug_services`` option + reloading the
    entry adds or removes those two services without a full HA restart.
    """
    enabled = _debug_services_enabled(entry)
    if enabled:
        if not hass.services.has_service(DOMAIN, SERVICE_DUMP_MAP_DIAGNOSTICS):
            hass.services.async_register(DOMAIN, SERVICE_DUMP_MAP_DIAGNOSTICS,
                                          _handle_dump_map_diagnostics, schema=SCHEMA_EMPTY)
        if not hass.services.has_service(DOMAIN, SERVICE_DISCOVER_CLOUD_API):
            hass.services.async_register(DOMAIN, SERVICE_DISCOVER_CLOUD_API,
                                          _async_handle_discover_cloud_api, schema=SCHEMA_EMPTY)
    else:
        for svc in _DEBUG_SERVICES:
            hass.services.async_remove(DOMAIN, svc)


def async_unregister_services(hass: HomeAssistant) -> None:
    # The two debug services (_DEBUG_SERVICES) are included unconditionally:
    # hass.services.async_remove is a no-op when the service isn't registered,
    # so this correctly handles the gated-OFF case where they were never added.
    for svc in (
        SERVICE_SET_ACTIVE_SELECTION, SERVICE_MOW_ZONE, SERVICE_MOW_EDGE, SERVICE_MOW_SPOT,
        SERVICE_SUPPRESS_FAULT,
        SERVICE_REPLAY_SESSION, SERVICE_SET_SCHEDULE_PLANS,
        SERVICE_SET_SCHEDULE_ENABLED,
        SERVICE_SHOW_LIDAR_FULLSCREEN, SERVICE_DUMP_MAP_DIAGNOSTICS, SERVICE_DISCOVER_CLOUD_API,
        SERVICE_SHOW_PHOTO_PRIVACY_POLICY,
        SERVICE_START_POINT_PATROL, SERVICE_START_EDGE_PATROL,
        SERVICE_RENAME_ZONE, SERVICE_DELETE_MAP_OBJECT,
        SERVICE_CREATE_NO_GO_ZONE, SERVICE_CREATE_IGNORE_OBSTACLE,
        SERVICE_CREATE_MOW_SHAPE, SERVICE_CREATE_SPOT,
        SERVICE_CREATE_MAINTENANCE_POINT,
        SERVICE_CREATE_PATROL_POINT, SERVICE_SET_PATROL_POINT_CONFIG,
        SERVICE_SPLIT_ZONE, SERVICE_MERGE_ZONES,
    ):
        hass.services.async_remove(DOMAIN, svc)
