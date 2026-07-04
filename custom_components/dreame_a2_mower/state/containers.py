"""Domain sub-containers for MowerState (P3.6 state-container split).

Eight frozen, slotted dataclasses split along wire-source seams (T2-15).
Each container is the value-object a single domain service owns/writes.
Fields were moved verbatim (name + annotation + default) from the former
flat ``mower/state.py``; per-field source citations live in
``inventory.yaml`` and git history. The enums (``State``, ``ActionMode``,
``ChargingStatus``) live here so container annotations can reference them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum


class State(IntEnum):
    """Mower state per s2.1.

    Source: ``docs/research/g2408-protocol.md`` §2.1 row ``s2.1``,
    confirmed via ioBroker apk decompilation.

    Persistence: volatile (HA shows ``unavailable`` when stale).
    """

    WORKING = 1
    STANDBY = 2
    PAUSED = 3
    # Value 4 also renders "Paused" in the Dreame app (same label as 3), but is
    # the auto/hold pause variant subject to a ~1 h timeout — distinct from the
    # user pause (3, co-incident with s2p56 status=[[1,4]]). After the timeout
    # the mower either auto-resumes (observed 2026-05-25) or auto-returns to the
    # dock via s2p2=72 "returning after pause timeout" (observed 2026-06-13:
    # s2p1=4 @21:45 → s2p2=72 @22:45, exactly 1 h later). See inventory.yaml
    # § s2p1 verifications (2026-05-25, 2026-06-15) and § s2p2 code 72.
    PAUSED_HOLD = 4
    RETURNING = 5
    CHARGING = 6
    MAPPING = 11
    CHARGED = 13
    UPDATING = 14


class ActionMode(str, Enum):
    """User's mode selection for the next start_mowing dispatch.

    Mirrors the Dreame app's main-screen dropdown (per APP_INFO.txt).
    Manual mode is BT-only on g2408 and intentionally omitted.

    Persistence: persistent (intent survives HA restart).
    """
    ALL_AREAS = "all_areas"
    EDGE = "edge"
    ZONE = "zone"
    SPOT = "spot"


class ChargingStatus(IntEnum):
    """Charging status per s3.2 (g2408 enum offset vs upstream).

    Source: ``docs/research/g2408-protocol.md`` §2.1 row ``s3.2``.

    Persistence: volatile.
    """

    NOT_CHARGING = 0
    CHARGING = 1
    CHARGED = 2


@dataclass(frozen=True, slots=True)
class Identity:
    """Device nameplate / identity (hardware serial, installed firmware)."""

    hardware_serial: str | None = None
    firmware_version: str | None = None


@dataclass(frozen=True, slots=True)
class OtaState:
    """OTA / firmware-update lifecycle (s1p2/s1p3 + checkDeviceVersion + DEV.ota)."""

    ota_capable_raw: int | None = None
    ota_state: int | None = None
    ota_progress: int | None = None
    firmware_latest: str | None = None
    firmware_update_available: bool | None = None
    firmware_release_notes: str | None = None


@dataclass(frozen=True, slots=True)
class Telemetry:
    """Live device runtime: s1p1/s1p4/s2/s3 pushes, derived position/area, dock, MPOS, raw diag slots."""

    battery_level: int | None = None
    charging_status: ChargingStatus | None = None
    error_code: int | None = None
    bluetooth_connected: bool | None = None
    area_mowed_m2: float | None = None
    session_distance_m: float | None = None
    total_lawn_area_m2: float | None = None
    task_total_area_m2: float | None = None
    target_area_m2: float | None = None
    mowing_phase: int | None = None
    position_x_m: float | None = None
    position_y_m: float | None = None
    wheel_bind_active: bool | None = None
    wheel_bind_consecutive_frames: int = 0
    position_heading_deg: float | None = None
    dock_in_lawn_region: bool | None = None
    dock_x_mm: int | None = None
    dock_y_mm: int | None = None
    dock_yaw: int | None = None
    battery_temp_low: bool | None = None
    robot_shutdown_trigger: int | None = None
    drop_tilt: bool | None = None
    bumper: bool | None = None
    lift: bool | None = None
    emergency_stop: bool | None = None
    safety_alert_active: bool | None = None
    slam_task_label: str | None = None
    task_state_code: int | None = None
    zone_progress: tuple[tuple[int, int], ...] = ()
    s5p104_raw: int | None = None
    s5p105_raw: int | None = None
    s5p106_raw: int | None = None
    s5p107_raw: int | None = None
    s6p1_raw: int | None = None
    mpos_x: int | None = None
    mpos_y: int | None = None
    mpos_yaw: int | None = None
    mpos_updated_unix: int | None = None
    mpos_last_result: str | None = None


@dataclass(frozen=True, slots=True)
class Connectivity:
    """External connectivity: wifi, 4G SIM, GPS fix, OSS storage quota."""

    position_lat: float | None = None
    position_lon: float | None = None
    gps_update_time: str | None = None
    gps_card4g: str | None = None
    sim_active_time: str | None = None
    sim_card_id: str | None = None
    sim_expired_time: str | None = None
    sim_left_days: int | None = None
    sim_data_remaining_mb: float | None = None
    sim_out_of_warranty: bool | None = None
    oss_storage_used: int | None = None
    oss_storage_total: int | None = None
    wifi_rssi_dbm: int | None = None
    wifi_ssid: str | None = None
    wifi_ip: str | None = None


@dataclass(frozen=True, slots=True)
class Consumables:
    """Consumable wear percentages + lifetime totals."""

    blades_life_pct: float | None = None
    cleaning_brush_life_pct: float | None = None
    robot_maintenance_life_pct: float | None = None
    total_mowing_time_min: int | None = None
    total_mowed_area_m2: float | None = None
    mowing_count: int | None = None
    first_mowing_date: str | None = None


@dataclass(frozen=True, slots=True)
class Settings:
    """Device settings (CFG/s2p51/PRE), per-map SETTINGS, and persistent user prefs/intent."""

    active_selection_edge_contours: tuple[tuple[int, int], ...] = ()
    action_mode: ActionMode = ActionMode.ALL_AREAS
    active_selection_zones: tuple[int, ...] = ()
    active_selection_spots: tuple[int, ...] = ()
    active_selection_point: tuple[int, int] | None = None
    child_lock_enabled: bool | None = None
    volume_pct: int | None = None
    language_code: str | None = None
    pre_zone_id: int | None = None
    pre_mowing_efficiency: int | None = None
    pre_mowing_height_mm: int | None = None
    pre_edgemaster: bool | None = None
    rain_protection_enabled: bool | None = None
    rain_protection_resume_hours: int | None = None
    low_speed_at_night_enabled: bool | None = None
    low_speed_at_night_start_min: int | None = None
    low_speed_at_night_end_min: int | None = None
    anti_theft_lift_alarm: bool | None = None
    anti_theft_offmap_alarm: bool | None = None
    anti_theft_realtime_location: bool | None = None
    dnd_enabled: bool | None = None
    dnd_start_min: int | None = None
    dnd_end_min: int | None = None
    auto_recharge_battery_pct: int | None = None
    resume_battery_pct: int | None = None
    custom_charging_enabled: bool | None = None
    charging_start_min: int | None = None
    charging_end_min: int | None = None
    led_period_enabled: bool | None = None
    led_in_standby: bool | None = None
    led_in_working: bool | None = None
    led_in_charging: bool | None = None
    led_in_error: bool | None = None
    human_presence_alert_enabled: bool | None = None
    human_presence_alert_sensitivity: int | None = None
    human_presence_scenario_standby: bool | None = None
    human_presence_scenario_mowing: bool | None = None
    human_presence_scenario_recharge: bool | None = None
    human_presence_scenario_patrol: bool | None = None
    human_presence_alert_voice: bool | None = None
    human_presence_alert_push_interval_min: int | None = None
    photo_consent: bool | None = None
    language_text_idx: int | None = None
    language_voice_idx: int | None = None
    frost_protection_enabled: bool | None = None
    auto_recharge_standby_enabled: bool | None = None
    ai_obstacle_photos_enabled: bool | None = None
    navigation_path_smart: bool | None = None
    msg_alert_anomaly: bool | None = None
    msg_alert_error: bool | None = None
    msg_alert_task: bool | None = None
    msg_alert_consumables: bool | None = None
    voice_regular_notification: bool | None = None
    voice_work_status: bool | None = None
    voice_special_status: bool | None = None
    voice_error_status: bool | None = None
    last_settings_change_unix: int | None = None
    weather_forecast_reference: int | None = None
    timezone: str | None = None
    cfg_version: int | None = None
    settings_mowing_height: int | None = None
    settings_mowing_direction: int | None = None
    settings_mowing_direction_mode: int | None = None
    settings_turning_method: int | None = None
    settings_cutter_position: int | None = None
    settings_cutter_position_height: int | None = None
    settings_edge_mowing_num: int | None = None
    settings_edge_mowing_auto: bool | None = None
    settings_edge_mowing_safe: bool | None = None
    settings_edge_mowing_obstacle_avoidance: bool | None = None
    settings_edge_mowing_walk_mode: int | None = None
    settings_obstacle_avoidance_enabled: bool | None = None
    settings_obstacle_avoidance_height: int | None = None
    settings_obstacle_avoidance_distance: int | None = None
    settings_obstacle_avoidance_sensitivity: int | None = None
    settings_obstacle_avoidance_ai: int | None = None
    trail_render_width: int = 24


@dataclass(frozen=True, slots=True)
class SessionRefs:
    """Session lifecycle bookkeeping: pending-OSS refs, latest-session summary, archive/lidar counters."""

    session_started_unix: int | None = None
    session_track_segments: tuple[tuple[tuple[float, float], ...], ...] | None = None
    pending_session_object_name: str | None = None
    pending_session_first_event_unix: int | None = None
    pending_session_last_attempt_unix: int | None = None
    pending_session_attempt_count: int | None = None
    latest_session_unix_ts: int | None = None
    latest_session_area_m2: float | None = None
    latest_session_duration_min: int | None = None
    archived_session_count: int | None = None
    latest_lidar_object_name: str | None = None
    archived_lidar_count: int | None = None


@dataclass(frozen=True, slots=True)
class Messages:
    """Account/device message stores + unread counters."""

    service_messages_unread: int | None = None
    system_messages_unread: int | None = None
    latest_service_message: str | None = None
    device_messages: list[dict] = field(default_factory=list)
    service_messages: list[dict] = field(default_factory=list)
    shared_messages: list[dict] = field(default_factory=list)
