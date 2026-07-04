"""Fault-surfacing service (layer 4) — refactor-v2 P3.9d.

Moved VERBATIM from ``coordinator/_device_sync.py``. This is the coordinator's
fault EMISSION glue — the fault-delta lifecycle events + the error-tier
persistent-notification lifecycle + the emergency-stop PIN banner. The fault
tier / category / severity / display-text KNOWLEDGE lives correctly at the
state layer in ``mower/fault_catalog.py`` + ``mower/error_codes.py`` (the P4
fault-catalog work); this module only orchestrates surfacing those to HA.

Each function takes the coordinator (``coord``) as its first argument; the
coordinator keeps thin ``_DeviceSyncMixin`` delegators (the fault methods stay
NAMED on ``_DeviceSyncMixin`` so ``test_fault_events``'s
``types.MethodType(_DeviceSyncMixin._fire_fault_delta, coord)`` binding is
preserved). These emitters are corpus-adjacent (they fire on snapshot.errors
edges); moved VERBATIM, corpus IDENTICAL is the proof.
"""
from __future__ import annotations

from ..const import (
    DOMAIN,
    EVENT_TYPE_FAULT_CLEARED,
    EVENT_TYPE_FAULT_DETECTED,
    LOGGER,
)

# Codes the generic fault-notice path must NOT touch: emergency-stop (23)
# has its own PIN-entry persistent notice via handle_emergency_stop_transition.
_EMERGENCY_STOP_CODE = 23


def handle_emergency_stop_transition(
    coord, prev: bool | None, new: bool | None,
) -> None:
    """Surface a persistent_notification mirroring the Dreame app's
    modal popup when the mower goes into the PIN-required lockout
    state, and dismiss it when the user enters the PIN to clear.

    byte[3] bit 7 (state.emergency_stop) is the load-bearing latch:
    sets on safety event (lid open OR lift), clears ONLY on PIN
    entry. So this notification's lifecycle exactly matches the
    app's "Emergency stop activated. Enter PIN code on the robot
    to unlock it." popup.
    """
    # Treat None (state not yet known) the same as False for trigger
    # purposes — handles the first heartbeat after HA restart where
    # the prior state was None and the mower is already in lockout.
    prev_active = prev is True
    new_active = new is True
    if prev_active and not new_active:
        try:
            from homeassistant.components import persistent_notification as _pn
            _pn.async_dismiss(
                coord.hass,
                notification_id=f"{DOMAIN}_emergency_stop_{coord.entry.entry_id}",
            )
            LOGGER.info("emergency_stop cleared — persistent_notification dismissed")
        except Exception as ex:
            LOGGER.warning("emergency_stop dismiss failed: %s", ex)
        return
    if prev_active or not new_active:
        return
    # Transition (None|False) → True: post the modal-equivalent banner.
    try:
        from homeassistant.components import persistent_notification as _pn
        _pn.async_create(
            coord.hass,
            message=(
                "The mower has triggered its safety lockout. **Enter "
                "the PIN code on the robot to unlock it.** The mower "
                "will not mow until the PIN is entered.\n\n"
                "This notification will dismiss automatically once "
                "the PIN is accepted."
            ),
            title="Dreame A2 Mower — Emergency stop activated",
            notification_id=f"{DOMAIN}_emergency_stop_{coord.entry.entry_id}",
        )
        LOGGER.info("emergency_stop activated — persistent_notification posted")
    except Exception as ex:
        LOGGER.warning("emergency_stop notification create failed: %s", ex)


def fault_notification_id(coord, code: int) -> str:
    return f"{DOMAIN}_fault_{int(code)}_{coord.entry.entry_id}"


def post_fault_notice(coord, code: int, lang: str) -> None:
    """Post a persistent_notification for a newly-detected error-tier fault.

    Title = the catalog fault_text; body = the catalog detail (solution
    steps) when present, else the fault_text. Skips emergency-stop (its
    dedicated PIN notice owns code 23). Wrapped in try/except so a UI-notice
    failure never breaks fault handling (mirrors handle_emergency_stop_transition).
    No-ops if hass or entry are not yet available (e.g. test stubs)."""
    if getattr(coord, "hass", None) is None or getattr(coord, "entry", None) is None:
        return
    if int(code) == _EMERGENCY_STOP_CODE:
        return
    from ..mower import fault_catalog
    title = fault_catalog.fault_text(int(code), lang) or f"Fault {int(code)}"
    body = fault_catalog.fault_detail(int(code), lang) or title
    try:
        from homeassistant.components import persistent_notification as _pn
        _pn.async_create(
            coord.hass,
            message=body,
            title=f"Dreame A2 Mower — {title}",
            notification_id=coord._fault_notification_id(code),
        )
        LOGGER.info("fault %d active — persistent_notification posted", int(code))
    except Exception as ex:
        LOGGER.warning("fault %d notice create failed: %s", int(code), ex)


def dismiss_fault_notice(coord, code: int) -> None:
    """Dismiss the persistent_notification for a cleared error-tier fault.

    No-ops if hass or entry are not yet available (e.g. test stubs)."""
    if getattr(coord, "hass", None) is None or getattr(coord, "entry", None) is None:
        return
    if int(code) == _EMERGENCY_STOP_CODE:
        return
    try:
        from homeassistant.components import persistent_notification as _pn
        _pn.async_dismiss(
            coord.hass, notification_id=coord._fault_notification_id(code)
        )
        LOGGER.info("fault %d cleared — persistent_notification dismissed", int(code))
    except Exception as ex:
        LOGGER.warning("fault %d notice dismiss failed: %s", int(code), ex)


def repost_active_fault_notices(coord) -> None:
    """Re-post error-tier persistent notices for faults restored from disk.

    On HA restart with a still-latched fault, snapshot.errors is restored but
    fire_fault_delta won't re-fire (no delta when the first MQTT push equals
    the restored set), so the banner is lost. This one-shot startup call
    re-posts it directly — WITHOUT firing fault_detected (no fire_fault_delta).
    Idempotent: post_fault_notice uses a per-code notification_id. emergency-stop
    (23) is skipped by post_fault_notice (its own notice re-posts via
    handle_emergency_stop_transition on the first heartbeat). No-ops if hass/
    entry/state_machine are unavailable (test stubs / early boot)."""
    if getattr(coord, "hass", None) is None or getattr(coord, "entry", None) is None:
        return
    sm = getattr(coord, "state_machine", None)
    if sm is None:
        return
    try:
        errors = sm.snapshot().errors
    except Exception:
        return
    if not errors:
        return
    from ..mower import fault_catalog
    cfg = getattr(coord.hass, "config", None)
    lang = fault_catalog.resolve_lang(getattr(cfg, "language", None))
    for code in sorted(errors):
        coord._post_fault_notice(int(code), lang)


def fire_fault_delta(coord, prev_errors, new_errors, *, now_unix: int) -> None:
    """Fire fault_detected / fault_cleared lifecycle events for the
    change between two snapshot.errors sets. Fired LOCALLY (not via the
    cloud notification resolver) so faults always reach the activity list.
    """
    from ..mower.error_codes import describe_error
    from ..mower import fault_catalog
    hass = getattr(coord, "hass", None)
    cfg = getattr(hass, "config", None)
    lang = fault_catalog.resolve_lang(getattr(cfg, "language", None))
    for code in sorted(new_errors - prev_errors):
        coord._fire_lifecycle(
            EVENT_TYPE_FAULT_DETECTED,
            {"code": int(code), "description": describe_error(int(code), lang),
             "at_unix": int(now_unix)},
        )
        coord._post_fault_notice(int(code), lang)
    for code in sorted(prev_errors - new_errors):
        coord._fire_lifecycle(
            EVENT_TYPE_FAULT_CLEARED,
            {"code": int(code), "description": describe_error(int(code), lang),
             "at_unix": int(now_unix)},
        )
        coord._dismiss_fault_notice(int(code))
