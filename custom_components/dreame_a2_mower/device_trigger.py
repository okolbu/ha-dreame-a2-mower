"""HA device_trigger platform for the Dreame A2 Mower integration.

Exposes the integration's bus events (`dreame_a2_mower_event`, fired by
`event.py:_DreameA2EventEntityBase.trigger` and dispatched from
`coordinator/_device_sync.py:_fire_lifecycle` / `_fire_notification` /
`_fire_fault_delta`) as Home Assistant **device triggers** — the idiomatic
automation entry point. A user building an automation can pick the mower
device and choose a trigger like "Mowing started" or "Human detected"
without hand-writing an event trigger or templating on the event entity's
state.

This file adds NO new event infrastructure. It re-uses:

- the `dreame_a2_mower_event` bus event already fired with the payload
  `{entity_id, event_type, data}`;
- `LIFECYCLE_EVENT_TYPES` (11 types) and the catalog-derived
  `NOTIFICATION_EVENT_TYPES` from `const.py`.

Curated exposed set
-------------------
All 11 ``LIFECYCLE_EVENT_TYPES`` are exposed (each is an unambiguous,
automatable moment).

From the catalog-derived ``NOTIFICATION_EVENT_TYPES`` we expose a curated
high-value subset of 18 — the ones a user would plausibly automate on
(safety, fault, attention-needed). The pure status-mirror notifications
that merely duplicate a lifecycle event or a sensor state are omitted to
keep the trigger picker readable (they remain fully available as raw
event triggers / via the logbook). Omitted-and-why:

- ``mowing_started`` / ``mowing_complete`` / ``scheduled_mowing_started``
  — duplicate the ``mowing_started`` / ``mowing_ended`` lifecycle triggers.
- ``patrol_started`` / ``patrol_ended`` — mirror lifecycle/state already
  surfaced; low automation value.
- ``maintenance_reminder`` / ``continue_unfinished_task`` /
  ``schedule_cancelled_busy`` / ``task_cancelled`` — informational status,
  not an actionable transition.
- ``unknown_s2p2`` — a catch-all for novel codes with no stable meaning;
  exposing it as a labelled trigger would be misleading.

Everything in ``_EXPOSED_NOTIFICATION_EVENT_TYPES`` below is exposed.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_DOMAIN,
    CONF_ENTITY_ID,
    CONF_PLATFORM,
    CONF_TYPE,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    LIFECYCLE_EVENT_TYPES,
)

# The bus event device triggers listen on. Must match the event fired by
# event.py:_DreameA2EventEntityBase.trigger().
_BUS_EVENT_TYPE = f"{DOMAIN}_event"

# Curated, high-value notification triggers (see module docstring for the
# rationale on what's exposed vs omitted).
_EXPOSED_NOTIFICATION_EVENT_TYPES: tuple[str, ...] = (
    "human_detected",           # 27
    "trapped",                  # 2
    "emergency_stop",           # 23
    "blade_loss",               # 28
    "left_wheel",               # 4
    "right_wheel",              # 5
    "hanging",                  # 0
    "back_charge_failed",       # 31
    "locating_failed_with_map", # 33
    "task_start_failed",        # 36
    "battery_temp_low",         # 43 (shared slug with 59 FAULT variant)
    "battery_low_returning",    # 54
    "bad_weather_protecting",   # 56
    "idle_timeout_returning",   # 71
    "pause_timeout_returning",  # 72
    "top_cover_open",           # 73
    "go_to_cleanpoint_success", # 75
    "go_to_cleanpoint_failed",  # 76
)

# The full set of `type`s this device-trigger platform supports.
TRIGGER_TYPES: tuple[str, ...] = (
    *LIFECYCLE_EVENT_TYPES,
    *_EXPOSED_NOTIFICATION_EVENT_TYPES,
)

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): vol.In(TRIGGER_TYPES),
    }
)


def _is_mower_device(device: dr.DeviceEntry | None) -> bool:
    """True if the registry device belongs to this integration."""
    if device is None:
        return False
    return any(ident[0] == DOMAIN for ident in device.identifiers)


def _source_entity_id_for_type(
    hass: HomeAssistant, device_id: str, trigger_type: str
) -> str | None:
    """Resolve the `event.*` entity_id on ``device_id`` that fires ``trigger_type``.

    The `dreame_a2_mower_event` bus payload carries the source `entity_id`
    (the lifecycle or notification event entity) but NOT a `device_id`, so
    the device→entity resolution happens here via the entity registry. The
    integration's two event entities have unique_ids suffixed `_lifecycle`
    and `_notification`; a lifecycle trigger_type maps to the former, a
    notification trigger_type to the latter. (The exposed lifecycle and
    notification type sets are disjoint, so the mapping is unambiguous.)
    """
    suffix = "lifecycle" if trigger_type in LIFECYCLE_EVENT_TYPES else "notification"
    registry = er.async_get(hass)
    for entry in er.async_entries_for_device(
        registry, device_id, include_disabled_entities=True
    ):
        if (
            entry.domain == "event"
            and entry.platform == DOMAIN
            and entry.unique_id.endswith(f"_{suffix}")
        ):
            return entry.entity_id
    return None


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, Any]]:
    """Return the list of device triggers for a Dreame A2 Mower device.

    One trigger per supported event type. HA's automation editor renders
    each as a selectable trigger keyed by ``type``; ``device_automation``
    pairs the ``type`` with the ``device_automation.trigger_type.*`` label
    in ``strings.json`` for display.
    """
    device = dr.async_get(hass).async_get(device_id)
    if not _is_mower_device(device):
        return []

    base = {
        CONF_PLATFORM: "device",
        CONF_DOMAIN: DOMAIN,
        CONF_DEVICE_ID: device_id,
    }
    return [{**base, CONF_TYPE: trigger_type} for trigger_type in TRIGGER_TYPES]


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Attach a trigger.

    Delegates to the core ``event`` trigger, listening on the
    ``dreame_a2_mower_event`` bus event and matching on this device's
    event entities (resolved from the configured ``device_id`` via the
    entity registry) plus the configured ``type`` (``event_type`` in the
    payload). Keying off this device's own ``event.*`` entity_ids means
    the trigger only fires for the matching mower — multiple mower config
    entries don't cross-fire.
    """
    trigger_type = config[CONF_TYPE]
    event_data: dict[str, Any] = {"event_type": trigger_type}
    source_entity_id = _source_entity_id_for_type(
        hass, config[CONF_DEVICE_ID], trigger_type
    )
    if source_entity_id is not None:
        # Pin to this device's own event entity so multiple mower config
        # entries never cross-fire. (If the entity isn't in the registry —
        # e.g. a brand-new setup before the event platform registered —
        # fall back to event_type-only, which is still device-correct for
        # a single-mower deployment.)
        event_data[CONF_ENTITY_ID] = source_entity_id
    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: _BUS_EVENT_TYPE,
            event_trigger.CONF_EVENT_DATA: event_data,
        }
    )
    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info, platform_type="device"
    )
