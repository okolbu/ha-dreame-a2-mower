"""Shared optimistic-write helper for SETTINGS-driven entities.

Replaces the three near-identical helpers that lived in switch.py,
select.py, and number.py — keeping the persistent-notification format
and revert flow in one place so a UX change touches one file.

Pattern (used by every settings-mirroring switch / select / number):
    1. Save old MowerState value.
    2. Update coordinator.data optimistically + push to HA (instant UI).
    3. Call coordinator.write_settings(map_id, field, cloud_value).
    4. On success: cloud refresh confirms; nothing else to do.
    5. On failure: revert MowerState + fire persistent_notification + raise
       HomeAssistantError via raise_for_write_result (P2 Task 5) so the UI
       action shows the honest device/cloud verdict.
"""
from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING, Any

from .coordinator._write_errors import raise_for_write_result

if TYPE_CHECKING:
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

_LOGGER = logging.getLogger(__name__)


async def settings_optimistic_write(
    entity: CoordinatorEntity,
    *,
    field: str,
    new_value: Any,
    state_field: str,
    map_id: int,
) -> None:
    """Optimistic write of one SETTINGS field with revert-on-failure.

    `new_value` is the entity-side value (bool / int / float). Bools are
    coerced to int for the wire (cloud SETTINGS stores all toggle fields
    as int 0/1, not booleans — see inventory.yaml § PRE, the dual-write
    PRE/SETTINGS family). The local MowerState keeps the entity-native
    type for clean UI reads.

    `map_id` selects which map to write to. Required — every per-map entity
    supplies its own explicit `map_id` (the single-map-era
    `map_id=None → coord._active_map_id` fallback was deleted 2026-07-02;
    it had zero production callers — see
    docs/research/debunked-claims.md § single-map era).
    """
    coord = entity.coordinator
    old_value = getattr(coord.data, state_field)
    coord.data = dataclasses.replace(coord.data, **{state_field: new_value})
    entity.async_write_ha_state()
    cloud_value = int(new_value) if isinstance(new_value, bool) else new_value
    result = await coord.write_settings(
        map_id=map_id, field=field, value=cloud_value,
    )
    if result.accepted:
        return
    # Revert + notify
    coord.data = dataclasses.replace(coord.data, **{state_field: old_value})
    entity.async_write_ha_state()
    await entity.hass.services.async_call(
        "persistent_notification", "create",
        service_data={
            "title": "Dreame A2 Mower: setting write rejected",
            "message": (
                f"The cloud rejected the write of {field}={new_value!r}. "
                f"Reverted to previous value ({old_value!r})."
            ),
            "notification_id": f"dreame_a2_write_fail_{entity.entity_id}",
        },
        blocking=False,
    )
    # P2 Task 5: after the revert + notification, raise so the UI action that
    # triggered the write also shows the honest verdict (T3-3 surfacing).
    raise_for_write_result(result, f"Set {field}", context="entity")


async def pre_settings_optimistic_write(
    entity, *, state_field: str, new_value, map_id: int,
    pre_index: int, pre_value, settings_field: str | None = None, settings_value=None,
) -> None:
    """Optimistic per-map General-Mode write via the coordinator PRE dual-write,
    reverting the local state + notifying if the device (PRE) write fails."""
    coord = entity.coordinator
    old_value = getattr(coord.data, state_field)
    coord.data = dataclasses.replace(coord.data, **{state_field: new_value})
    entity.async_write_ha_state()
    result = await coord.write_map_general_setting(
        map_id=map_id, pre_index=pre_index, pre_value=pre_value,
        settings_field=settings_field, settings_value=settings_value,
    )
    if result.accepted:
        return
    coord.data = dataclasses.replace(coord.data, **{state_field: old_value})
    entity.async_write_ha_state()
    await entity.hass.services.async_call(
        "persistent_notification", "create",
        service_data={
            "title": "Dreame A2 Mower: setting write rejected",
            "message": (
                f"The mower rejected the write of {state_field}={new_value!r}. "
                f"Reverted to {old_value!r}."
            ),
            "notification_id": f"dreame_a2_write_fail_{entity.entity_id}",
        },
        blocking=False,
    )
    # P2 Task 5: after the revert + notification, raise so the UI action that
    # triggered the write also shows the honest verdict (T3-3 surfacing).
    raise_for_write_result(result, f"Set {state_field}", context="entity")
