"""LastKnown — offline last-known read-only snapshot (layer 3, Task 12a / P6.7).

A SEPARATE, self-contained value object holding the read-only device values the
integration should keep showing while the mower/cloud is offline (including
across an HA restart). It is deliberately NOT part of ``MowerState`` /
``StateSnapshot`` / any of the eight state containers: adding a field to those
would change ``MowerState.to_flat_dict()`` / ``FLAT_FIELDS`` /
``dataclasses.asdict(snapshot())`` and break the corpus-replay golden digest
(``tools/replay/corpus_replay.py``) even though decode semantics are unchanged.
So this lives here with its own ``to_dict`` / ``from_dict`` and is persisted via
its own ``homeassistant.helpers.storage.Store`` (see ``coordinator/_core.py``
``_restore_last_known`` / ``_save_last_known`` and ``domain/boot.py``).

Pure module: it imports nothing from coordinator/entities. ``from_state`` reads
the flat MowerState fields by name via ``getattr`` (duck-typed — no MowerState
import needed), so this stays a layer-3 leaf.

The ``12b`` follow-up (entity availability/staleness) consumes ``saved_unix``.
"""
from __future__ import annotations

from dataclasses import dataclass, fields as _dc_fields
from typing import Any

# Debounce window for the last-known Store write (seconds). Matches the
# device-messages store cadence — a refresh burst coalesces into one disk write.
LAST_KNOWN_SAVE_DELAY_S = 5

# MowerState flat field names this blob mirrors 1:1. These are read off
# ``coord.data`` at save time and seeded back onto it at restore time. Each name
# MUST be a real MowerState flat field (see ``state/containers.py``). The two
# meta fields (``active_map_id`` / ``saved_unix``) are NOT MowerState fields and
# are handled separately — they never seed MowerState.
_STATE_FIELDS: tuple[str, ...] = (
    # consumables + lifetime totals (MIHIS)
    "blades_life_pct",
    "cleaning_brush_life_pct",
    "robot_maintenance_life_pct",
    "total_mowed_area_m2",
    "total_mowing_time_min",
    "mowing_count",
    # 4G SIM
    "sim_card_id",
    "sim_left_days",
    "sim_active_time",
    "sim_expired_time",
    "sim_data_remaining_mb",
    "sim_out_of_warranty",
    # dock pose
    "dock_x_mm",
    "dock_y_mm",
    "dock_yaw",
    "dock_in_lawn_region",
    # firmware
    "firmware_version",
    # device-wide read-only time-window / protection settings (NOT per-map)
    "rain_protection_enabled",
    "rain_protection_resume_hours",
    "frost_protection_enabled",
    "dnd_enabled",
    "dnd_start_min",
    "dnd_end_min",
    "custom_charging_enabled",
    "charging_start_min",
    "charging_end_min",
    # WiFi identity
    "wifi_ssid",
    "wifi_ip",
    # device-wide CFG config settings (persist so the Settings/DnD tab survives
    # the device being offline — CFG is a device-routed call, dark when off).
    "child_lock_enabled",
    "volume_pct",
    "language_text_idx",
    "language_voice_idx",
    "language_code",
    "low_speed_at_night_enabled",
    "low_speed_at_night_start_min",
    "low_speed_at_night_end_min",
    "auto_recharge_battery_pct",
    "resume_battery_pct",
    "led_period_enabled",
    "led_in_standby",
    "led_in_working",
    "led_in_charging",
    "led_in_error",
    "anti_theft_lift_alarm",
    "anti_theft_offmap_alarm",
    "anti_theft_realtime_location",
    "human_presence_alert_enabled",
    "human_presence_alert_sensitivity",
    "human_presence_scenario_standby",
    "human_presence_scenario_mowing",
    "human_presence_scenario_recharge",
    "human_presence_scenario_patrol",
    "human_presence_alert_voice",
    "human_presence_alert_push_interval_min",
    "msg_alert_anomaly",
    "msg_alert_error",
    "msg_alert_task",
    "msg_alert_consumables",
    "voice_regular_notification",
    "voice_work_status",
    "voice_special_status",
    "voice_error_status",
    "auto_recharge_standby_enabled",
    "ai_obstacle_photos_enabled",
    "navigation_path_smart",
    # CFG.PRE / CFG.REC[7] / CFG.WRF / CFG.TIME / CFG.VER (review fix: 6
    # device-wide CFG config fields omitted from the initial 37-field sweep)
    "pre_zone_id",
    "pre_mowing_efficiency",
    "photo_consent",
    "weather_forecast_reference",
    "timezone",
    "cfg_version",
)


@dataclass(frozen=True, slots=True)
class LastKnown:
    """Frozen last-known read-only values + active map + save timestamp."""

    # --- mirrored MowerState fields (keep in sync with _STATE_FIELDS) ---
    blades_life_pct: float | None = None
    cleaning_brush_life_pct: float | None = None
    robot_maintenance_life_pct: float | None = None
    total_mowed_area_m2: float | None = None
    total_mowing_time_min: int | None = None
    mowing_count: int | None = None
    sim_card_id: str | None = None
    sim_left_days: int | None = None
    sim_active_time: str | None = None
    sim_expired_time: str | None = None
    sim_data_remaining_mb: float | None = None
    sim_out_of_warranty: bool | None = None
    dock_x_mm: int | None = None
    dock_y_mm: int | None = None
    dock_yaw: int | None = None
    dock_in_lawn_region: bool | None = None
    firmware_version: str | None = None
    rain_protection_enabled: bool | None = None
    rain_protection_resume_hours: int | None = None
    frost_protection_enabled: bool | None = None
    dnd_enabled: bool | None = None
    dnd_start_min: int | None = None
    dnd_end_min: int | None = None
    custom_charging_enabled: bool | None = None
    charging_start_min: int | None = None
    charging_end_min: int | None = None
    wifi_ssid: str | None = None
    wifi_ip: str | None = None
    child_lock_enabled: bool | None = None
    volume_pct: int | None = None
    language_text_idx: int | None = None
    language_voice_idx: int | None = None
    language_code: str | None = None
    low_speed_at_night_enabled: bool | None = None
    low_speed_at_night_start_min: int | None = None
    low_speed_at_night_end_min: int | None = None
    auto_recharge_battery_pct: int | None = None
    resume_battery_pct: int | None = None
    led_period_enabled: bool | None = None
    led_in_standby: bool | None = None
    led_in_working: bool | None = None
    led_in_charging: bool | None = None
    led_in_error: bool | None = None
    anti_theft_lift_alarm: bool | None = None
    anti_theft_offmap_alarm: bool | None = None
    anti_theft_realtime_location: bool | None = None
    human_presence_alert_enabled: bool | None = None
    human_presence_alert_sensitivity: int | None = None
    human_presence_scenario_standby: bool | None = None
    human_presence_scenario_mowing: bool | None = None
    human_presence_scenario_recharge: bool | None = None
    human_presence_scenario_patrol: bool | None = None
    human_presence_alert_voice: bool | None = None
    human_presence_alert_push_interval_min: int | None = None
    msg_alert_anomaly: bool | None = None
    msg_alert_error: bool | None = None
    msg_alert_task: bool | None = None
    msg_alert_consumables: bool | None = None
    voice_regular_notification: bool | None = None
    voice_work_status: bool | None = None
    voice_special_status: bool | None = None
    voice_error_status: bool | None = None
    auto_recharge_standby_enabled: bool | None = None
    ai_obstacle_photos_enabled: bool | None = None
    navigation_path_smart: bool | None = None
    pre_zone_id: int | None = None
    pre_mowing_efficiency: int | None = None
    photo_consent: bool | None = None
    weather_forecast_reference: int | None = None
    timezone: str | None = None
    cfg_version: int | None = None
    # --- meta (not MowerState fields) ---
    active_map_id: int | None = None
    saved_unix: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Plain JSON-native dict for the Store (all values scalar or None)."""
        return {f.name: getattr(self, f.name) for f in _dc_fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "LastKnown":
        """Build from a stored dict, tolerating missing/extra keys (compat).

        Missing keys default to ``None``; unknown keys are ignored so a blob
        written by a newer/older version restores cleanly.
        """
        data = data or {}
        names = {f.name for f in _dc_fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})

    @classmethod
    def from_state(
        cls, state: Any, active_map_id: int | None, saved_unix: float | None
    ) -> "LastKnown":
        """Snapshot the mirrored fields off a MowerState (duck-typed)."""
        kw: dict[str, Any] = {n: getattr(state, n, None) for n in _STATE_FIELDS}
        kw["active_map_id"] = active_map_id
        kw["saved_unix"] = saved_unix
        return cls(**kw)

    def non_none_state_updates(self) -> dict[str, Any]:
        """The mirrored fields that are set, as ``MowerState.with_updates`` kwargs.

        Excludes the meta fields (``active_map_id`` / ``saved_unix``) and any
        field still ``None`` — so a restore never clobbers a real value with a
        blank and never passes a non-MowerState key into ``with_updates``.
        """
        out: dict[str, Any] = {}
        for name in _STATE_FIELDS:
            val = getattr(self, name)
            if val is not None:
                out[name] = val
        return out
