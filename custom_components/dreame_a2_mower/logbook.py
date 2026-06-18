"""Logbook describers for the integration's two EventEntity instances.

By default the HA logbook card renders an EventEntity state change as
"<friendly_name> detected an event" — which is technically correct
but loses the event_type and any payload (text / code) that makes
the event useful. This module overrides that formatting:

  - For event.dreame_a2_mower_lifecycle: "started mowing", "arrived
    at dock", etc.
  - For event.dreame_a2_mower_notification: the notification's `text`
    payload (the cloud's authoritative localised string when available),
    falling back to a per-event_type label.

The translations file (translations/en.json § entity.event) carries the
same labels for places HA reads the entity-state translation (entity
card, state badge). This logbook module guarantees the same labels reach
the logbook card too — EventEntity translations aren't currently picked
up by the logbook component on their own.
"""
from __future__ import annotations

from typing import Any, Callable

from homeassistant.components.logbook import (
    LOGBOOK_ENTRY_MESSAGE,
    LOGBOOK_ENTRY_NAME,
)
from homeassistant.core import Event, HomeAssistant, callback

from .const import DOMAIN

# event_type → human message for the lifecycle entity.
_LIFECYCLE_MESSAGES: dict[str, str] = {
    "mowing_started": "started mowing",
    "mowing_paused": "paused mowing",
    "mowing_resumed": "resumed mowing",
    "mowing_ended": "finished mowing",
    "dock_arrived": "arrived at the dock",
    "dock_departed": "left the dock",
    "charging_started": "started charging",
    "charging_complete": "finished charging",
    "rain_delay_started": "paused for rain — waiting out the delay",
    "self_shutdown": "shut itself down (low battery)",
}


def _format(entity_id: str, event_type: str, attrs: dict[str, Any]) -> str | None:
    """Return the human message for one of our event entities."""
    if entity_id.endswith("_lifecycle"):
        if event_type in ("fault_detected", "fault_cleared"):
            desc = attrs.get("description") or f"error {attrs.get('code')}"
            verb = "fault" if event_type == "fault_detected" else "recovered"
            return f"{verb}: {desc}"
        return _LIFECYCLE_MESSAGES.get(
            event_type, event_type.replace("_", " ")
        )
    if entity_id.endswith("_notification"):
        # The notification entity carries the cloud's authoritative
        # localised `text` in the payload; prefer it so context-rich
        # messages survive in the logbook. Fall back to humanising the
        # slug when 'text' is absent (the resolver always populates it
        # from cloud push or the bundled catalog).
        text = attrs.get("text")
        if text:
            return str(text)
        return event_type.replace("_", " ")
    return None


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[..., Any],
) -> None:
    """Register a logbook describer for our custom bus event.

    EventEntity state changes don't reach async_describe_event
    describers — HA logbook handles them as a PSEUDO_EVENT_STATE_CHANGED
    that bypasses the describer registry and falls through to a
    generic "detected an event" message. We work around that by
    firing a custom HA bus event (`<DOMAIN>_event`) from
    EventEntity.trigger() in addition to the entity-state update;
    custom bus events DO route through describers. This module
    formats those bus events.
    """

    @callback
    def describe(event: Event) -> dict[str, Any] | None:
        entity_id = event.data.get("entity_id", "")
        event_type = event.data.get("event_type", "")
        data = event.data.get("data") or {}
        if not entity_id or not event_type:
            return None
        message = _format(entity_id, event_type, data)
        if message is None:
            return None
        return {
            LOGBOOK_ENTRY_NAME: "Mower",
            LOGBOOK_ENTRY_MESSAGE: message,
        }

    async_describe_event(DOMAIN, f"{DOMAIN}_event", describe)
