"""Device-registry sync + lifecycle-event emission service (layer 4) — P3.9d.

Moved VERBATIM from ``coordinator/_device_sync.py``. Holds: the map sub-device
registry sync, the effective-target-area computation, the debounced cloud-refresh
tripwire, event-entity wiring, and the ``_fire_*`` lifecycle-event emitters
(mowing_ended, notification, lifecycle, local-novel-s2p2). The fault-specific
emitters (fault-delta + notices + emergency-stop) live in ``domain/faults.py``.

Each function takes the coordinator (``coord``) as its first argument; the
coordinator keeps thin ``_DeviceSyncMixin`` delegators so the public/test
surface (``coord.register_event_entities``, ``coord._fire_mowing_ended``, the
unbound ``_DeviceSyncMixin._X`` methods) is unchanged. The ``_fire_*`` emitters
are corpus-adjacent (they fire on state edges); moved VERBATIM, corpus
IDENTICAL is the proof.
"""
from __future__ import annotations

from typing import Any

from ..const import (
    DOMAIN,
    EVENT_TYPE_MOWING_ENDED,
    LOGGER,
)
from ..mower import fault_catalog
from ..state import MowerState


def compute_target_area_m2(coord, state: MowerState) -> float | None:
    """Effective area for the current mowing target.

    Behaves like the Dreame app's "this is what will be mowed"
    readout. Source-of-truth order:

    1. Live s1.4 telemetry's per-task area
       (``task_total_area_m2``) when a session is active. This
       is the firmware's own "target" figure; it covers any
       combination of selected zones/spots without the cloud map
       round-trip.
    2. Cloud-map area_m2 of the selected zone(s) or spot(s) when
       the user has picked a target. Used pre-session so the
       dashboard shows the planned target before pressing Start.
    3. Full lawn area otherwise (the sensor's original meaning).
    """
    from ..state import ActionMode

    # Priority 1: live telemetry while mowing.
    # Use live_map.is_active() — session_active was removed from MowerState (SM-14).
    live_task_area = state.task_total_area_m2
    if (
        coord.live_map.is_active()
        and live_task_area is not None
        and live_task_area > 0
    ):
        return float(live_task_area)

    _maps = coord.cloud_state.maps_by_id if coord.cloud_state is not None else {}
    map_data = _maps.get(coord._active_map_id)
    mode = state.action_mode
    if map_data is not None:
        if mode == ActionMode.ZONE and state.active_selection_zones:
            wanted = set(state.active_selection_zones)
            total = 0.0
            for z in getattr(map_data, "mowing_zones", ()):
                if z.zone_id in wanted:
                    total += float(getattr(z, "area_m2", 0.0) or 0.0)
            if total > 0:
                return total
        if mode == ActionMode.SPOT and state.active_selection_spots:
            wanted = set(state.active_selection_spots)
            total = 0.0
            matched: list[tuple[int, str, float]] = []
            for s in getattr(map_data, "spot_zones", ()):
                if s.spot_id in wanted:
                    matched.append(
                        (s.spot_id, s.name, float(getattr(s, "area_m2", 0.0) or 0.0))
                    )
                    total += matched[-1][2]
            if total > 0:
                return total
            # v1.0.0a51: log once when SPOT mode would target a real
            # selection but we can't compute an area — distinguishes
            # "spot not found in cached map" from "spot found but
            # cloud sent area=0".
            if not (
                coord._target_area_diagnostics_logged
                if hasattr(coord, "_target_area_diagnostics_logged") else False
            ):
                available = [
                    (s.spot_id, s.name, float(getattr(s, "area_m2", 0.0) or 0.0))
                    for s in getattr(map_data, "spot_zones", ())
                ]
                LOGGER.debug(
                    "[F5] target_area: SPOT mode wanted=%s matched=%s "
                    "available=%s — falling back to total_lawn_area_m2",
                    list(wanted), matched, available,
                )
                coord._target_area_diagnostics_logged = True
    # All-areas, edge mode, or no selection / no area data yet:
    # fall back to the full lawn area (the sensor's original
    # meaning).
    return state.total_lawn_area_m2


def update_device_registry_serial(coord, serial: str) -> None:
    """Reflect the real hardware serial onto the device record."""
    try:
        from homeassistant.helpers import device_registry as dr
    except ImportError:
        return
    registry = dr.async_get(coord.hass)
    device = registry.async_get_device(identifiers={(DOMAIN, coord.entry.entry_id)})
    if device is None:
        LOGGER.debug(
            "hardware_serial fetched but device record not yet registered "
            "(serial=%r) — will pick up on next entity registration",
            serial,
        )
        return
    if device.serial_number == serial:
        return
    registry.async_update_device(device.id, serial_number=serial)
    LOGGER.debug("device serial_number updated to %s", serial)


def get_device_registry(coord) -> object | None:
    """Return the HA device registry, or None if unavailable in this test env."""
    try:
        from homeassistant.helpers import device_registry as dr
    except ImportError:
        return None
    return dr.async_get(coord.hass)


def sync_map_subdevices(coord) -> None:
    """Add HA devices for new map_ids; remove devices for dropped ones.

    Called whenever ``cloud_state.maps_by_id`` may have changed (after
    ``_apply_mapl`` and after ``_refresh_cloud_state``). No-ops if ``coord.hass`` or
    ``coord.entry`` is missing or None (test stubs may not have them set).
    """
    if not hasattr(coord, "hass") or coord.hass is None:
        return
    if not hasattr(coord, "entry") or coord.entry is None:
        return
    if coord.cloud_state is None:
        return
    from .._devices import _stable_id, map_device_info

    registry = coord._get_device_registry()
    if registry is None:
        return
    stable = _stable_id(coord)
    wanted_ids = set(coord.cloud_state.maps_by_id.keys())

    for map_id, map_data in coord.cloud_state.maps_by_id.items():
        info = map_device_info(coord, map_id, getattr(map_data, "name", None))
        registry.async_get_or_create(
            config_entry_id=coord.entry.entry_id,
            **info,
        )

    # An empty maps_by_id means "no authoritative map list right now"
    # (transient empty cloud batch), NOT "delete every map". Pruning on
    # empty would wipe all per-map sub-devices; skip it.
    if not wanted_ids:
        return

    # Remove orphan map sub-devices belonging to this entry.
    # HA device identifiers are typed as `set[tuple[str, str]]` but in
    # the wild some integrations store longer tuples. Iterate defensively.
    prefix = f"{stable}_map_"
    for dev in list(registry.devices.values()):
        for ident_tuple in dev.identifiers:
            if len(ident_tuple) < 2 or ident_tuple[0] != DOMAIN:
                continue
            ident = ident_tuple[1]
            if not isinstance(ident, str) or not ident.startswith(prefix):
                continue
            try:
                map_id = int(ident.removeprefix(prefix))
            except ValueError:
                continue
            if map_id not in wanted_ids:
                registry.async_remove_device(dev.id)
            break


def schedule_cloud_refresh(
    coord, *, delay_sec: float = 5.0, reason: str = "tripwire",
) -> None:
    """Debounced cloud-state refresh — coalesces bursts of MQTT
    settings tripwires (s6p2 etc.) into a single fetch.

    Called from the MQTT event-loop hop on every tripwire push.
    Each call cancels any pending fire and arms a new timer so a
    burst of settings saves results in exactly one refresh once
    the burst settles. Default delay 5s — short enough that HA
    reflects an app-side edit within a few seconds, long enough
    to coalesce the 1-3 tripwires the firmware tends to emit per
    save (FRAME_INFO + an echo or two).
    """
    loop = coord.hass.loop
    if coord._cloud_refresh_debounce_handle is not None:
        coord._cloud_refresh_debounce_handle.cancel()

    def _fire() -> None:
        coord._cloud_refresh_debounce_handle = None
        LOGGER.info(
            "[cloud] settings tripwire (%s) → refreshing cloud state",
            reason,
        )
        coord.hass.async_create_task(coord._refresh_cloud_state())

    coord._cloud_refresh_debounce_handle = loop.call_later(delay_sec, _fire)


def register_event_entities(coord, *, lifecycle: Any, notification: Any) -> None:
    """Called from event.py's async_setup_entry to wire the event
    entities the coordinator's dispatcher fires through.

    Stored as plain attributes (no weakref needed — entities live
    for the integration's lifetime). The lifecycle and notification
    parameters are the EventEntity instances created by
    event.py's setup call.
    """
    coord._lifecycle_event = lifecycle
    coord._notification_event = notification


def fire_lifecycle(
    coord, event_type: str, event_data: dict[str, Any] | None = None
) -> None:
    """Race-safe dispatcher to the lifecycle event entity.

    Drops the call with a DEBUG log if the entity isn't yet wired
    (transient on startup before event.py's async_setup_entry has
    run). Delegates payload-cleaning to the entity's `trigger`
    wrapper.
    """
    ent = coord._lifecycle_event
    if ent is None:
        LOGGER.debug(
            "[event] _fire_lifecycle(%r) dropped — entity not yet registered",
            event_type,
        )
        return
    ent.trigger(event_type, event_data)


def fire_local_novel_s2p2(coord, *, code: int, now_unix: int) -> None:
    """Fire a local (NOT cloud-gated) notification for a truly-unknown
    s2p2 code so it always reaches the activity list. The cloud resolver
    may still enrich with authoritative text later; this is the guaranteed
    floor. source='local' distinguishes it from cloud-sourced fires.
    """
    ent = coord._notification_event
    if ent is None:
        return
    LOGGER.warning(
        "[event] novel s2p2 code=%d — local activity entry created; no S2P2_EVENT_TYPES mapping",
        int(code),
    )
    ent.trigger(
        "unknown_s2p2",
        {"code": int(code), "text": f"Unrecognised status {code}",
         "source": "local", "siid": 2, "piid": 2, "fired_at": int(now_unix)},
    )


def fire_mowing_ended(
    coord,
    now_unix: int,
    area_mowed_m2: float | None,
    duration_min: int | None,
    completed: bool,
) -> None:
    """Fire the mowing_ended lifecycle event AND notify state machine.

    Called from both _do_oss_fetch (FINALIZE_COMPLETE, summary-driven)
    and _run_finalize_incomplete (FINALIZE_INCOMPLETE, best-effort).
    Delegates payload-shape consistency to one place.

    State-machine sync: the finalize gate can fire on a cloud-
    detected task_state transition (prev ∈ {0,4} → new ∈ {2,None})
    without a matching MQTT push. Without this hook the state
    machine stays IN_SESSION + MOWING indefinitely while the
    lifecycle event correctly reports the session ended.
    """
    coord._fire_lifecycle(
        EVENT_TYPE_MOWING_ENDED,
        {
            "at_unix": int(now_unix),
            "area_mowed_m2": area_mowed_m2,
            "duration_min": duration_min,
            "completed": bool(completed),
        },
    )
    coord._rain_delay_started_at = None  # session over → no rain wait
    sm = getattr(coord, "state_machine", None)
    if sm is not None:
        try:
            sm.end_session(now_unix=int(now_unix))
        except Exception:
            LOGGER.exception("state_machine.end_session failed")


def fire_notification(
    coord,
    *,
    event_type: str,
    text: str,
    code: int,
    siid: int = 2,
    piid: int = 2,
    send_time: str | None = None,
    message_id: str | None = None,
    now_unix: int = 0,
) -> None:
    """Race-safe dispatcher to the notification event entity.

    Called by ``domain.notifications.resolve_s2p2_notification`` after
    the resolver has fetched the authoritative text from the cloud's
    device-messages store. Drops the call with DEBUG if the entity
    isn't registered yet (transient on startup before event.py's
    async_setup_entry has run). Also stashes the notification for
    sensor.last_notification.

    NOTE: pre-2026-05-26 there was an inline `_fire_alert` called
    directly from _on_state_update with a hardcoded text table. That
    path is gone — texts now come from the cloud per-fire.
    """
    coord._last_notification = {
        "event_type": event_type,
        "text": text,
        "code": code,
        "fired_at": now_unix,
    }
    LOGGER.info(
        "[notification] s%dp%d=%d slug=%r text=%r (msg=%s)",
        siid, piid, code, event_type, text, message_id or "-",
    )
    ent = coord._notification_event
    if ent is None:
        LOGGER.debug(
            "[event] _fire_notification(%r) dropped — entity not yet registered",
            event_type,
        )
        return
    payload = {
        "text": text,
        "code": code,
        "siid": siid,
        "piid": piid,
        "send_time": send_time,
        "message_id": message_id,
        "source": "cloud",
        "tier": fault_catalog.fault_tier(code),
        "category": fault_catalog.fault_category(code),
        "severity": fault_catalog.fault_severity(code),
    }
    ent.trigger(event_type, payload)
