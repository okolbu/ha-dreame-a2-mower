"""Diagnostics dump for HA's download_diagnostics button.

R-3 rewrite (2026-07-05): this dump used to redact via a DENYLIST
(``REDACTION_KEYS``) — everything not named leaked, including GPS
``position_lat``/``position_lon``, wifi SSID/IP, the SIM card id, the
hardware serial, the cloud client's ``did``/``uid``/``uuid``/``host``, and
the MQTT subscribe topic (which embeds the device serial). A downloaded
diagnostics file attached to a public bug report would leak all of these.

Replaced with an explicit ALLOWLIST (default-deny): only fields known to
be safe for a bug report are emitted; everything else is omitted, or —
for the ``config_entry`` section, so a reader can see credentials WERE
present but scrubbed — replaced with the ``"**REDACTED**"`` marker.

Sections in the dump:
- config_entry         (safe passthrough keys shown; credentials -> marker)
- versions             (integration + firmware version)
- state                (SAFE_STATE_FIELDS allowlisted subset of MowerState)
- capabilities         (Capabilities dataclass as dict)
- cloud_state          (allowlisted subset — never did/uid/uuid/host)
- mqtt_state           (allowlisted subset — never subscribe_topic/first_topics)
- entity_counts        (counts only, never contents)
- archive_counts       (counts only, never contents)
- novel_observations   (registry snapshot — list of {category, detail, first_seen_unix})
- freshness            (per-field last_updated map)
- endpoint_log         (cloud RPC accept/reject map)
- recent_novel_log_lines (tail of NOVEL log warnings, capped at 200)
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .mower.capabilities import Capabilities

_REDACTED = "**REDACTED**"

# config_entry: these keys pass through verbatim; everything else is
# either redacted-to-marker (see _CONFIG_ENTRY_REDACT_KEYS) or dropped.
_CONFIG_ENTRY_SAFE_KEYS: frozenset[str] = frozenset({"country", "model"})

# config_entry: these keys are known-sensitive and get the marker (so a
# reader can see credentials WERE present but scrubbed) instead of being
# silently dropped.
_CONFIG_ENTRY_REDACT_KEYS: frozenset[str] = frozenset(
    {"username", "password", "token", "did", "sn", "mac", "host"}
)

# cloud_state: allowlist only — did/uid/uuid/host are dropped entirely
# (not even a marker), since they are internal transport identifiers with
# no debugging value once redacted.
_CLOUD_STATE_SAFE_KEYS: frozenset[str] = frozenset(
    {"logged_in", "connected", "model", "country", "last_send_error_code"}
)

# mqtt_state: allowlist only — subscribe_topic/first_topics are dropped
# entirely (MQTT topics embed the device serial).
_MQTT_STATE_SAFE_KEYS: frozenset[str] = frozenset(
    {
        "connected",
        "connecting",
        "callback_registered",
        "client_present",
        "username_set",
        "suback_results",
    }
)

# The flat MowerState debugging subset considered safe to attach to a
# public bug report. Deliberately EXCLUDES: GPS (position_lat/position_lon,
# gps_card4g), the SIM card id, the hardware serial, exact in-map
# robot/dock coordinates (position_x_m/position_y_m, dock_x_mm/dock_y_mm/
# dock_yaw, position_heading_deg, mpos_*), raw per-point session track
# geometry (session_track_segments), OSS object-name strings that embed
# did/uid (pending_session_object_name, latest_lidar_object_name), and raw
# message/notification content (device_messages, service_messages,
# shared_messages, latest_service_message) — only unread *counts* are kept.
# See state/containers.py for the field-owning containers.
SAFE_STATE_FIELDS: frozenset[str] = frozenset(
    {
        # Identity — firmware only; hardware_serial is never included.
        "firmware_version",
        # OtaState — full: no identifiers.
        "ota_capable_raw",
        "ota_state",
        "ota_progress",
        "firmware_latest",
        "firmware_update_available",
        "firmware_release_notes",
        # Telemetry — state-machine phase/mode, error/fault code, task/area
        # counters, and safety-flag booleans. Excludes exact position/dock/
        # mpos coordinates and raw diagnostic slots.
        "battery_level",
        "charging_status",
        "error_code",
        "bluetooth_connected",
        "area_mowed_m2",
        "session_distance_m",
        "total_lawn_area_m2",
        "task_total_area_m2",
        "target_area_m2",
        "mowing_phase",
        "task_state_code",
        "zone_progress",
        "robot_shutdown_trigger",
        "battery_temp_low",
        "drop_tilt",
        "bumper",
        "lift",
        "emergency_stop",
        "safety_alert_active",
        # Connectivity — status/quota values only; never position_lat/lon,
        # gps_card4g, sim_card_id, wifi_ssid, wifi_ip.
        "gps_update_time",
        "sim_active_time",
        "sim_expired_time",
        "sim_left_days",
        "sim_data_remaining_mb",
        "sim_out_of_warranty",
        "oss_storage_used",
        "oss_storage_total",
        "wifi_rssi_dbm",
        # Consumables — full: percentages + lifetime totals, no identifiers.
        "blades_life_pct",
        "cleaning_brush_life_pct",
        "robot_maintenance_life_pct",
        "total_mowing_time_min",
        "total_mowed_area_m2",
        "mowing_count",
        "first_mowing_date",
        # Settings — full: booleans + numeric mode/height settings, no PII.
        "active_selection_edge_contours",
        "action_mode",
        "active_selection_zones",
        "active_selection_spots",
        "active_selection_point",
        "child_lock_enabled",
        "volume_pct",
        "language_code",
        "pre_zone_id",
        "pre_mowing_efficiency",
        "pre_mowing_height_mm",
        "pre_edgemaster",
        "rain_protection_enabled",
        "rain_protection_resume_hours",
        "low_speed_at_night_enabled",
        "low_speed_at_night_start_min",
        "low_speed_at_night_end_min",
        "anti_theft_lift_alarm",
        "anti_theft_offmap_alarm",
        "anti_theft_realtime_location",
        "dnd_enabled",
        "dnd_start_min",
        "dnd_end_min",
        "auto_recharge_battery_pct",
        "resume_battery_pct",
        "custom_charging_enabled",
        "charging_start_min",
        "charging_end_min",
        "led_period_enabled",
        "led_in_standby",
        "led_in_working",
        "led_in_charging",
        "led_in_error",
        "human_presence_alert_enabled",
        "human_presence_alert_sensitivity",
        "human_presence_scenario_standby",
        "human_presence_scenario_mowing",
        "human_presence_scenario_recharge",
        "human_presence_scenario_patrol",
        "human_presence_alert_voice",
        "human_presence_alert_push_interval_min",
        "photo_consent",
        "language_text_idx",
        "language_voice_idx",
        "frost_protection_enabled",
        "auto_recharge_standby_enabled",
        "ai_obstacle_photos_enabled",
        "navigation_path_smart",
        "msg_alert_anomaly",
        "msg_alert_error",
        "msg_alert_task",
        "msg_alert_consumables",
        "voice_regular_notification",
        "voice_work_status",
        "voice_special_status",
        "voice_error_status",
        "last_settings_change_unix",
        "weather_forecast_reference",
        "timezone",
        "cfg_version",
        "settings_mowing_height",
        "settings_mowing_direction",
        "settings_mowing_direction_mode",
        "settings_turning_method",
        "settings_cutter_position",
        "settings_cutter_position_height",
        "settings_edge_mowing_num",
        "settings_edge_mowing_auto",
        "settings_edge_mowing_safe",
        "settings_edge_mowing_obstacle_avoidance",
        "settings_edge_mowing_walk_mode",
        "settings_obstacle_avoidance_enabled",
        "settings_obstacle_avoidance_height",
        "settings_obstacle_avoidance_distance",
        "settings_obstacle_avoidance_sensitivity",
        "settings_obstacle_avoidance_ai",
        "trail_render_width",
        # SessionRefs — counters/timestamps only; never track_segments or
        # the OSS object-name strings (they embed did/uid).
        "session_started_unix",
        "pending_session_first_event_unix",
        "pending_session_last_attempt_unix",
        "pending_session_attempt_count",
        "latest_session_unix_ts",
        "latest_session_area_m2",
        "latest_session_duration_min",
        "archived_session_count",
        "archived_lidar_count",
        # Messages — unread counts only; never the raw message content lists.
        "service_messages_unread",
        "system_messages_unread",
    }
)


def _allowlist(payload: dict[str, Any] | None, safe_keys: frozenset[str]) -> dict[str, Any]:
    """Keep only ``safe_keys`` from ``payload``; drop everything else
    (default-deny). Never raises on a falsy/None payload."""
    if not payload:
        return {}
    return {k: v for k, v in payload.items() if k in safe_keys}


def _redact_entry_data(payload: dict[str, Any]) -> dict[str, Any]:
    """config_entry allowlist: pass safe keys through verbatim, replace
    known-sensitive keys with the redaction marker, drop anything else."""
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key in _CONFIG_ENTRY_SAFE_KEYS:
            out[key] = value
        elif key in _CONFIG_ENTRY_REDACT_KEYS:
            out[key] = _REDACTED
    return out


def _safe_state_dict(state: Any) -> dict[str, Any]:
    """Return the SAFE_STATE_FIELDS subset of a MowerState's flat view.
    Prefers omission over a REDACTED marker — a 130-field marker dump is
    noise, not a debugging aid."""
    if state is None:
        return {}
    to_flat = getattr(state, "to_flat_dict", None)
    flat = to_flat() if callable(to_flat) else (asdict(state) if is_dataclass(state) else {})
    return {k: v for k, v in flat.items() if k in SAFE_STATE_FIELDS}


def _integration_version() -> str | None:
    """Read the integration version from manifest.json. Never raises —
    diagnostics must never crash the download over a missing/malformed
    manifest."""
    try:
        manifest_path = Path(__file__).parent / "manifest.json"
        with manifest_path.open(encoding="utf-8") as fh:
            return json.load(fh).get("version")
    except Exception:  # noqa: BLE001 - diagnostics must not crash
        return None


def _safe_len(value: Any) -> int:
    """``len(value)`` that never raises — used for archive/entity counts
    where the underlying accessor may be absent on a partially-set-up
    coordinator (or a test double)."""
    try:
        return len(value)
    except Exception:  # noqa: BLE001 - diagnostics must not crash
        return 0


def _entity_counts(coordinator: Any) -> dict[str, int]:
    try:
        maps_by_id = getattr(coordinator.cloud_state, "maps_by_id", None)
    except Exception:  # noqa: BLE001 - diagnostics must not crash
        maps_by_id = None
    return {"maps": _safe_len(maps_by_id or {})}


def _archive_counts(coordinator: Any, state: Any) -> dict[str, int]:
    # Note: the coordinator's underscore-prefixed archive-store attrs are
    # deliberately NOT read here — this module lives outside the coordinator
    # package, and the string-getattr audit gate
    # (tests/audit/test_no_coordinator_private_getattr.py) forbids reaching a
    # coordinator-private attribute by name from anywhere else in the tree.
    # Only counts reachable via a public accessor or a MowerState field are
    # surfaced.
    counts: dict[str, int] = {
        "sessions": getattr(state, "archived_session_count", None) or 0,
    }
    try:
        counts["lidar"] = _safe_len(coordinator.list_lidar_archive_entries())
    except Exception:  # noqa: BLE001 - diagnostics must not crash
        counts["lidar"] = 0
    try:
        counts["wifi"] = int(coordinator.wifi_archive_entry_count)
    except Exception:  # noqa: BLE001 - diagnostics must not crash
        counts["wifi"] = 0
    return counts


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    snap = coordinator.novel_registry.snapshot()
    cloud = coordinator.cloud
    endpoint_log = dict(getattr(cloud, "endpoint_log", {})) if cloud is not None else {}
    _caps_attr = getattr(coordinator, "capabilities", None)
    caps = _caps_attr if is_dataclass(_caps_attr) else Capabilities()

    cloud_state_raw: dict[str, Any] = {}
    if cloud is not None:
        cloud_state_raw = {
            "logged_in": getattr(cloud, "_logged_in", None),
            "connected": getattr(cloud, "_connected", None),
            "model": getattr(cloud, "_model", None),
            "country": getattr(cloud, "_country", None),
            "last_send_error_code": getattr(cloud, "_last_send_error_code", None),
        }

    mqtt = coordinator.mqtt
    mqtt_state_raw: dict[str, Any] = {}
    if mqtt is not None:
        mqtt_state_raw = {
            "connected": getattr(mqtt, "_connected", None),
            "connecting": getattr(mqtt, "_connecting", None),
            "callback_registered": getattr(mqtt, "_callback", None) is not None,
            "client_present": getattr(mqtt, "_client", None) is not None,
            "username_set": getattr(mqtt, "_username", None) is not None,
            "suback_results": list(getattr(mqtt, "_suback_results", []) or []),
        }

    state = coordinator.data
    return {
        "config_entry": _redact_entry_data(dict(entry.data)),
        "versions": {
            "integration": _integration_version(),
            "firmware": getattr(state, "firmware_version", None),
        },
        "state": _safe_state_dict(state),
        "capabilities": asdict(caps),
        "cloud_state": _allowlist(cloud_state_raw, _CLOUD_STATE_SAFE_KEYS),
        "mqtt_state": _allowlist(mqtt_state_raw, _MQTT_STATE_SAFE_KEYS),
        "entity_counts": _entity_counts(coordinator),
        "archive_counts": _archive_counts(coordinator, state),
        "novel_observations": [
            {
                "category": o.category,
                "detail": o.detail,
                "first_seen_unix": o.first_seen_unix,
            }
            for o in snap.observations
        ],
        "freshness": coordinator.freshness.snapshot(),
        "endpoint_log": endpoint_log,
        "recent_novel_log_lines": coordinator.novel_log.lines(),
    }
