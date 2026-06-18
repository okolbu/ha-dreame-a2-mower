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

# event_type → human message for the notification entity. Used as a
# fallback when the bus event doesn't carry a 'text' field (which is
# the cloud's authoritative localised string — preferred when present).
# Slugs are catalog-derived (mower/error_codes.py → fault_catalog.json
# [apk:g2408-plugin-ext1423]). Task 5 will replace this hand-table with
# a catalog lookup; this table is the bridge until then.
_NOTIFICATION_MESSAGES: dict[str, str] = {
    "autobuild_stop": "auto boundary detection stopped",
    "away_from_map": "robot is away from the map",
    "back_charge_failed": "failed to return to station",
    "bad_weather_protecting": "rain protection activated — returning to station",
    "battery_low": "low battery — robot will shut down soon",
    "battery_low_returning": "low battery — returning to station",
    "battery_low_schedule_suspend": "low battery — scheduled task cancelled",
    "battery_overheat": "battery overheating — returning to station",
    "battery_temp_low": "charging paused — battery too cold",
    "blade_loss": "blades severely worn — replace soon",
    "cam_abnormal": "front camera error",
    "cam_cover": "front camera blocked — please check",
    "charging": "charging error — please check",
    "continue_from_breakpoint": "continuing unfinished task",
    "crash_plate": "bumper error — please check",
    "cruise_start": "patrol task started",
    "cruise_task_finish": "patrol complete",
    "cutter": "blade disc can't rotate — please check",
    "dark_schedule_suspend": "outside operating hours — scheduled task delayed",
    "destination_not_reachable": "unable to reach certain zones — task ended",
    "docking_failed": "failed to dock in station",
    "emergency_stop": "emergency stop activated",
    "emergency_stopped_schedule_suspend": "PIN verification failed — scheduled task cancelled",
    "exception_on_way_to_cleanpoint": "robot error on way to maintenance point — task ended",
    "fault_mode_schedule_suspend": "robot status error — scheduled task cancelled",
    "frozen_schedule_suspend": "frost protection — scheduled task cancelled",
    "go_to_cleanpoint_failed": "unable to reach maintenance point — task ended",
    "go_to_cleanpoint_success": "arrived at maintenance point",
    "hanging": "is hanging (lifted off the ground)",
    "human_detected": "detected a person in the mowing area",
    "idle_timeout_returning": "on standby too long — auto-returning to station",
    "in_forbidden_area": "in a no-go zone — please move it",
    "left_wheel": "left drive wheel error — please check",
    "lidar_abnormal": "lidar malfunction",
    "lidar_covered": "lidar blocked — please check",
    "lidar_dirty": "lidar dirty — please clean",
    "lidar_overheat": "lidar overheating — please check",
    "lidar_overheat_with_map": "lidar overheating — returning to station",
    "lidar_overheat_without_map": "lidar overheating — please check",
    "lift_motor": "blade disc not moving up/down — please check",
    "locating_abnormal": "mapping failed — positioning error",
    "locating_failed_with_map": "positioning failed",
    "maintain_loss": "maintenance reminder — service the robot soon",
    "narrow_path_to_station": "insufficient turning space at station — please check",
    "not_disturb_returning": "do not disturb — returning to station",
    "not_disturb_schedule_suspend": "do not disturb — scheduled task cancelled",
    "out_of_map": "robot is outside the map — please check",
    "path_impassable": "path obstructed — please check",
    "pause_timeout_returning": "task paused too long — returning to station",
    "rain_schedule_interupted": "rain protection — scheduled task cancelled",
    "rain_schedule_suspend": "rain protection — scheduled task cancelled",
    "remote_controling_schedule_suspend": "under remote control — scheduled task cancelled",
    "right_wheel": "right drive wheel error — please check",
    "schedule_start": "scheduled mow started",
    "schedule_timeout": "scheduled task complete (some areas not mowed in time)",
    "sensor": "sensor error — please check",
    "sided_motor": "blade disc can't move sideways — please check",
    "station_loss": "cleaning brush severely worn — replace soon",
    "station_not_connected_to_working_area": "station not connected to work area — can't start",
    "task_cancelled": "task cancelled",
    "task_finish": "mowing complete",
    "task_start": "mowing started",
    "task_start_failed": "failed to start task — please retry",
    "tilted": "robot is tilted — please reposition",
    "top_cover_open": "top cover is open",
    "top_cover_open_schedule_suspend": "top cover open — scheduled task cancelled",
    "trapped": "robot is stuck — please assist",
    "working_schedule_suspend": "mower busy — scheduled task cancelled",
    "unknown_s2p2": "notification (novel code)",
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
        # messages survive in the logbook. Fallback to the per-slug
        # message table below when 'text' is absent (cloud unreachable
        # at fire time, or a future code path that doesn't fetch text).
        text = attrs.get("text")
        if text:
            return str(text)
        return _NOTIFICATION_MESSAGES.get(
            event_type, event_type.replace("_", " ")
        )
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
