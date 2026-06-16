"""Device-level sensor entity classes and description tables for the Dreame A2 Mower.

This module is a helper — NOT a HA platform — so HA will not attempt to
load it directly.  It is imported by sensor.py.

Contains: SENSORS, DIAGNOSTIC_SENSORS (description tables), all device-level
entity classes, and module-level helpers used exclusively by device sensors.
"""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..._availability import _FreshnessAvailableMixin
from ..._devices import _MowerScopedEntity, mower_device_info, mower_unique_id
from ...coordinator import DreameA2MowerCoordinator
from ...mower.error_codes import describe_error
from ...mower.state import ChargingStatus, MowerState
from .base import (
    DreameA2DiagnosticSensorEntityDescription,
    DreameA2SensorEntityDescription,
    _SnapshotEnumSensorBase,
)


# ---------------------------------------------------------------------------
# Module-level helpers and constants (device-sensor only)
# ---------------------------------------------------------------------------

# Cache the integration version once at module import time.
# manifest.json is static for the lifetime of the HA process. Read it ONCE at
# module-import time — HA imports integration modules in an import executor
# (off the event loop), so the synchronous read here is safe. Reading it lazily
# from native_value (the previous behaviour) landed on the event loop and tripped
# HA 2026.6's blocking-call detector (read_text inside the loop).
def _read_manifest_version() -> str:
    try:
        _manifest_path = Path(__file__).parent / "manifest.json"
        return str(json.loads(_manifest_path.read_text()).get("version", "unknown"))
    except Exception:  # noqa: BLE001
        return "unknown"


_MANIFEST_VERSION: str = _read_manifest_version()


def _manifest_version() -> str:
    """Return the integration version string (read once at import)."""
    return _MANIFEST_VERSION


# Kept for the state_machine_audit eval-globals; no live value_fn calls it now.
def _describe_error_or_none(code: int | None) -> str | None:
    return describe_error(code) if code is not None else None


def _active_fault_text(snapshot) -> str | None:
    """Human text for the currently-latched fault(s), or None.

    Reads the state machine's latched fault set (snapshot.errors) rather than
    the last raw s2p2 (MowerState.error_code). s2p2 multiplexes faults with
    status codes, so the raw value is usually a non-fault and a real fault is
    overwritten within seconds — the latch is the actionable signal. Multiple
    simultaneous faults are joined with '; '. Sorted for stable output.
    """
    # getattr (not snapshot.errors) keeps the audit eval-path robust to partial fakes.
    errors = getattr(snapshot, "errors", None)
    if not errors:
        return None
    return "; ".join(describe_error(c) for c in sorted(errors))


def _format_active_selection(state: MowerState) -> str | None:
    """Format zone/spot selection for display.

    Examples:
      action_mode=all_areas → 'All areas'
      action_mode=edge → 'Edge mow'
      action_mode=zone, zones=(3, 1, 2) → 'Zones 3 → 1 → 2'
      action_mode=zone, zones=() → 'No zones selected'
      action_mode=spot, spots=() → 'No spots selected'
    """
    from ...mower.state import ActionMode
    mode = state.action_mode
    if mode == ActionMode.ALL_AREAS:
        return "All areas"
    if mode == ActionMode.EDGE:
        return "Edge mow"
    if mode == ActionMode.ZONE:
        zones = state.active_selection_zones
        if not zones:
            return "No zones selected"
        return "Zones " + " → ".join(str(z) for z in zones)
    if mode == ActionMode.SPOT:
        spots = state.active_selection_spots
        if not spots:
            return "No spots selected"
        return "Spots " + " → ".join(str(s) for s in spots)
    return None


def _api_endpoints_value(coord) -> int:
    cloud = getattr(coord, "_cloud", None)
    if cloud is None:
        return 0
    return sum(1 for v in cloud.endpoint_log.values() if v == "accepted")


def _api_endpoints_attrs(coord) -> dict[str, list[str]]:
    cloud = getattr(coord, "_cloud", None)
    if cloud is None:
        return {"accepted": [], "rejected_80001": [], "device_rejected": [], "error": []}
    log = cloud.endpoint_log
    return {
        "accepted": sorted(k for k, v in log.items() if v == "accepted"),
        "rejected_80001": sorted(k for k, v in log.items() if v == "rejected_80001"),
        "device_rejected": sorted(k for k, v in log.items() if v == "device_rejected"),
        "error": sorted(k for k, v in log.items() if v == "error"),
    }


def _freshness_value(coord) -> int | None:
    """Age in seconds of the oldest tracked field, or None if nothing
    has been stamped yet."""
    snap = coord.freshness.snapshot()
    if not snap:
        return None
    now = int(time.time())
    return now - min(snap.values())


def _freshness_attrs(coord) -> dict[str, int]:
    """Per-field age in seconds, keyed as ``{field}_age_s``."""
    snap = coord.freshness.snapshot()
    now = int(time.time())
    return {f"{name}_age_s": now - ts for name, ts in snap.items()}


def _mpos_value(coord) -> str | None:
    """Format the raw MPOS x/y/yaw triple as a string, or None if any field is absent."""
    s = coord.data
    if s.mpos_x is None or s.mpos_y is None or s.mpos_yaw is None:
        return None
    return f"{s.mpos_x}, {s.mpos_y}, {s.mpos_yaw}"


def _mpos_attrs(coord) -> dict:
    """Extra attributes for the MPOS diagnostic sensor.

    Returns raw x/y/yaw, ISO timestamp of the last successful refresh,
    the last result string, and a honesty note that these are
    untransformed cloud values — NOT the integration's position.
    """
    s = coord.data
    last_updated = (
        datetime.fromtimestamp(s.mpos_updated_unix, tz=UTC).isoformat()
        if s.mpos_updated_unix else None
    )
    return {
        "x": s.mpos_x,
        "y": s.mpos_y,
        "yaw": s.mpos_yaw,
        "last_updated": last_updated,
        "last_result": s.mpos_last_result,
        "note": (
            "Raw cloud MPOS reading, untransformed — NOT the integration's "
            "position. Frame/units unverified. Press 'Refresh MPOS' to update."
        ),
    }


def _mqtt_age_value(coord) -> int | None:
    """Seconds since the last MQTT heartbeat from the device, or None if
    none has arrived yet. Reads the canonical `snapshot.last_heartbeat_unix`
    that the state machine stamps on every s1p1 push — same source the
    snapshot's `mqtt_connectivity` enum derives from. Pair with
    `binary_sensor.cloud_connected` (which is the ONLINE/STALE binary view)."""
    snap = coord.state_machine.snapshot()
    last = snap.last_heartbeat_unix
    if last is None:
        return None
    return int(time.time()) - int(last)


# Schedule label helpers — module-level so tests / dashboard templates
# can reuse them. Mon..Sun ordering matches the firmware's weekday=1..7
# numbering decoded into bit 0..bit 6.
_WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_ACTION_LABELS = {
    0: "all_area",
    1: "zone",
    2: "edge",
}


def _fmt_hhmm(time_min: int) -> str:
    return f"{time_min // 60:02d}:{time_min % 60:02d}"


def _fmt_weekdays(mask: int) -> list[str]:
    return [_WEEKDAY_LABELS[i] for i in range(7) if mask & (1 << i)]


def _fmt_action(action_type: int) -> str:
    return _ACTION_LABELS.get(action_type, f"unknown_{action_type}")


# ---------------------------------------------------------------------------
# Description tables
# ---------------------------------------------------------------------------

SENSORS: tuple[DreameA2SensorEntityDescription, ...] = (
    DreameA2SensorEntityDescription(
        key="charging_status",
        translation_key="charging_status",
        name="Charging status",
        device_class=SensorDeviceClass.ENUM,
        options=[c.name.lower() for c in ChargingStatus],
        availability_source="mqtt",
        value_fn=lambda s: (s.charging_status.name.lower() if s.charging_status is not None else None),
    ),

    # Telemetry-derived:
    DreameA2SensorEntityDescription(
        key="area_mowed_m2",
        name="Area mowed",
        native_unit_of_measurement="m²",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        availability_source="mqtt",
        value_fn=lambda s: s.area_mowed_m2 if s.area_mowed_m2 is not None else 0,
    ),
    DreameA2SensorEntityDescription(
        key="session_distance_m",
        name="Session distance",
        native_unit_of_measurement="m",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        availability_source="mqtt",
        value_fn=lambda s: s.session_distance_m if s.session_distance_m is not None else 0,
    ),
    # mowing_phase / task_state_code / slam_task_label have been migrated
    # to DIAGNOSTIC_SENSORS so they read coord.state_machine.snapshot()
    # and survive HA restarts (last-known persisted via the snapshot
    # Store). See the entries near the bottom of DIAGNOSTIC_SENSORS.

    # State-related:
    DreameA2SensorEntityDescription(
        key="error_code",
        name="Error code",
        entity_category=EntityCategory.DIAGNOSTIC,
        availability_source="mqtt",
        value_fn=lambda s: s.error_code,
    ),
    # Lawn / environment:
    DreameA2SensorEntityDescription(
        # Keep the existing key for entity-id stability; the value_fn
        # now resolves to the *target* area (cloud-supplied area_m2 of
        # the selected zone/spot) when the user has picked a target,
        # falling back to the full lawn area otherwise. Reads as
        # 'Target area' so the friendly name matches the value.
        key="total_lawn_area_m2",
        name="Target area",
        native_unit_of_measurement="m²",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        availability_source="cloud",
        value_fn=lambda s: (
            s.target_area_m2 if s.target_area_m2 is not None else s.total_lawn_area_m2
        ),
    ),
    DreameA2SensorEntityDescription(
        key="wifi_ssid",
        name="WiFi SSID",
        icon="mdi:wifi",
        entity_category=EntityCategory.DIAGNOSTIC,
        availability_source="mqtt",
        value_fn=lambda s: s.wifi_ssid,
    ),
    DreameA2SensorEntityDescription(
        key="wifi_ip",
        name="WiFi IP",
        icon="mdi:ip-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        availability_source="mqtt",
        value_fn=lambda s: s.wifi_ip,
    ),
    # CFG.DOCK position fields. yaw user-confirmed to match compass
    # X-axis of the dock-relative frame; x/y are map-frame coords (NOT
    # necessarily 0,0 despite earlier integration assumptions).
    DreameA2SensorEntityDescription(
        key="dock_x_mm",
        name="Dock X",
        native_unit_of_measurement="mm",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        availability_source="cloud",
        value_fn=lambda s: s.dock_x_mm,
    ),
    DreameA2SensorEntityDescription(
        key="dock_y_mm",
        name="Dock Y",
        native_unit_of_measurement="mm",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        availability_source="cloud",
        value_fn=lambda s: s.dock_y_mm,
    ),
    DreameA2SensorEntityDescription(
        key="dock_yaw",
        name="Dock yaw",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        availability_source="cloud",
        # User-confirmed 2026-05-04: matches compass bearing for the
        # X-axis direction of the dock frame. Unit unclear (may be
        # degrees, may be deci-degrees — `near_yaw: 1912` is suspicious
        # if `yaw: 112` is degrees).
        value_fn=lambda s: s.dock_yaw,
    ),

    # CFG-derived consumables:
    DreameA2SensorEntityDescription(
        key="blades_life_pct",
        name="Blades life",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        availability_source="cloud",
        value_fn=lambda s: s.blades_life_pct,
    ),
    DreameA2SensorEntityDescription(
        key="cleaning_brush_life_pct",
        name="Cleaning brush life",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        availability_source="cloud",
        value_fn=lambda s: s.cleaning_brush_life_pct,
    ),
    DreameA2SensorEntityDescription(
        key="robot_maintenance_life_pct",
        name="Robot maintenance life",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        availability_source="cloud",
        value_fn=lambda s: s.robot_maintenance_life_pct,
    ),
    DreameA2SensorEntityDescription(
        key="total_mowing_time_min",
        name="Total mowing time",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        availability_source="cloud",
        value_fn=lambda s: s.total_mowing_time_min,
    ),
    DreameA2SensorEntityDescription(
        key="total_mowed_area_m2",
        name="Total mowed area",
        native_unit_of_measurement="m²",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        availability_source="cloud",
        value_fn=lambda s: s.total_mowed_area_m2,
    ),
    DreameA2SensorEntityDescription(
        key="mowing_count",
        name="Mowing count",
        # Pre-greenfield used "x" as the unit; HA's recorder compares
        # incoming statistics against the historical unit and suppresses
        # long-term stats on mismatch. Keep the same unit so existing
        # statistics carry over without manual cleanup.
        native_unit_of_measurement="x",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        availability_source="cloud",
        value_fn=lambda s: s.mowing_count,
    ),
    DreameA2SensorEntityDescription(
        key="first_mowing_date",
        name="First mowing date",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.first_mowing_date,
    ),
    DreameA2SensorEntityDescription(
        key="active_selection",
        name="Active selection",
        value_fn=_format_active_selection,
    ),

    # Settings-derived (s2.51) observability:
    DreameA2SensorEntityDescription(
        key="last_settings_change_unix",
        name="Last settings change",
        entity_category=EntityCategory.DIAGNOSTIC,
        availability_source="cloud",
        value_fn=lambda s: s.last_settings_change_unix,
    ),
    DreameA2SensorEntityDescription(
        key="language_text_idx",
        name="Language text index",
        entity_category=EntityCategory.DIAGNOSTIC,
        availability_source="cloud",
        value_fn=lambda s: s.language_text_idx,
    ),
    DreameA2SensorEntityDescription(
        key="language_voice_idx",
        name="Language voice index",
        entity_category=EntityCategory.DIAGNOSTIC,
        availability_source="cloud",
        value_fn=lambda s: s.language_voice_idx,
    ),

    # ------ v1.0.0a11: raw protocol diagnostic sensors per spec §5.6 ------
    DreameA2SensorEntityDescription(
        key="s5p104_raw",
        name="s5.104 raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        availability_source="mqtt",
        value_fn=lambda s: s.s5p104_raw,
    ),
    DreameA2SensorEntityDescription(
        key="s5p105_raw",
        name="s5.105 raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        availability_source="mqtt",
        value_fn=lambda s: s.s5p105_raw,
    ),
    DreameA2SensorEntityDescription(
        key="s5p106_raw",
        name="s5.106 raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        availability_source="mqtt",
        value_fn=lambda s: s.s5p106_raw,
    ),
    DreameA2SensorEntityDescription(
        key="s5p107_raw",
        name="s5.107 raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        availability_source="mqtt",
        value_fn=lambda s: s.s5p107_raw,
    ),
    DreameA2SensorEntityDescription(
        key="s6p1_raw",
        name="s6.1 raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        availability_source="mqtt",
        value_fn=lambda s: s.s6p1_raw,
    ),

    # ------ F5.11.1: session history sensors ------

    DreameA2SensorEntityDescription(
        key="latest_session_area_m2",
        name="Latest session area",
        native_unit_of_measurement="m²",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda s: s.latest_session_area_m2,
    ),
    DreameA2SensorEntityDescription(
        key="latest_session_duration_min",
        name="Latest session duration",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.latest_session_duration_min,
    ),
    DreameA2SensorEntityDescription(
        key="latest_session_unix_ts",
        name="Latest session time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda s: (
            datetime.fromtimestamp(s.latest_session_unix_ts, tz=UTC)
            if s.latest_session_unix_ts is not None
            else None
        ),
    ),
    DreameA2SensorEntityDescription(
        key="archived_session_count",
        name="Archived session count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.archived_session_count,
    ),
    DreameA2SensorEntityDescription(
        key="lidar_archive_count",
        translation_key="lidar_archive_count",
        icon="mdi:cube-scan",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.archived_lidar_count,
    ),
    DreameA2SensorEntityDescription(
        key="session_track_point_count",
        name="Session track point count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: (
            sum(len(leg) for leg in s.session_track_segments)
            if s.session_track_segments is not None
            else 0
        ),
    ),
    # REC[8] — push notification cooldown (minutes between successive
    # detection pushes). Wire enum {3, 10, 20} from the app's 3-radio-
    # button "Push interval" selector. Read-only on this firmware.
    DreameA2SensorEntityDescription(
        key="human_presence_push_interval_min",
        translation_key="human_presence_push_interval_min",
        name="Human presence push interval",
        native_unit_of_measurement="min",
        entity_category=EntityCategory.DIAGNOSTIC,
        availability_source="cloud",
        value_fn=lambda s: s.human_presence_alert_push_interval_min,
    ),

    # ------ Phase 2 recorder-merge safety-net sensor ------
    # charging_status_code_raw exists so HA's recorder captures charging
    # transitions as raw ints. T7's merge_recorder_samples reads it back
    # to backfill in_progress.json charging-state sample streams.
    # state_code_raw was removed (redundant with snapshot-backed
    # sensor.task_state_code) and error_code_raw was removed (redundant
    # with the existing sensor.error_code which already returns the raw int).
    DreameA2SensorEntityDescription(
        key="charging_status_code_raw",
        translation_key="charging_status_code_raw",
        name="Charging status code (raw)",
        entity_category=EntityCategory.DIAGNOSTIC,
        availability_source="mqtt",
        value_fn=lambda s: s.charging_status.value if s.charging_status is not None else None,
    ),
    # ------ Phase D: OSS storage quota sensors ------
    # Bytes → MB conversion (1 MiB = 1 048 576 bytes).  None-safe: returns
    # None when the cloud hasn't delivered the quota block yet.
    DreameA2SensorEntityDescription(
        key="oss_storage_used",
        name="OSS storage used",
        icon="mdi:cloud-upload",
        native_unit_of_measurement="MB",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        availability_source="cloud",
        value_fn=lambda s: (
            round(s.oss_storage_used / 1048576) if s.oss_storage_used is not None else None
        ),
    ),
    DreameA2SensorEntityDescription(
        key="oss_storage_total",
        name="OSS storage total",
        icon="mdi:cloud",
        native_unit_of_measurement="MB",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        availability_source="cloud",
        value_fn=lambda s: (
            round(s.oss_storage_total / 1048576) if s.oss_storage_total is not None else None
        ),
    ),
    DreameA2SensorEntityDescription(
        key="oss_storage_pct",
        name="OSS storage used percent",
        icon="mdi:cloud-percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        availability_source="cloud",
        value_fn=lambda s: (
            round(s.oss_storage_used / s.oss_storage_total * 100)
            if s.oss_storage_used is not None and s.oss_storage_total
            else None
        ),
    ),

    # ------ Phase C: SIM / messaging diagnostic sensors ------
    DreameA2SensorEntityDescription(
        key="sim_card_id",
        name="SIM ICCID",
        icon="mdi:sim",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.sim_card_id,
    ),
    DreameA2SensorEntityDescription(
        key="sim_left_days",
        name="SIM days remaining",
        icon="mdi:sim-alert",
        native_unit_of_measurement="d",
        entity_category=EntityCategory.DIAGNOSTIC,
        availability_source="cloud",
        value_fn=lambda s: s.sim_left_days,
    ),
    DreameA2SensorEntityDescription(
        key="sim_active_time",
        name="SIM activated",
        icon="mdi:sim",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.sim_active_time,
    ),
    DreameA2SensorEntityDescription(
        key="sim_expired_time",
        name="SIM expires",
        icon="mdi:sim-off",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.sim_expired_time,
    ),
    DreameA2SensorEntityDescription(
        key="service_messages_unread",
        name="Unread messages",
        icon="mdi:email-alert",
        entity_category=EntityCategory.DIAGNOSTIC,
        availability_source="cloud",
        value_fn=lambda s: s.service_messages_unread,
        extra_attributes_fn=lambda s: {
            "system_messages_unread": s.system_messages_unread,
            "latest_message": s.latest_service_message,
        },
    ),
)


DIAGNOSTIC_SENSORS: tuple[DreameA2DiagnosticSensorEntityDescription, ...] = (
    # Battery percentage — reads the persisted snapshot value so it survives
    # HA restarts. The snapshot is loaded from disk via state_machine
    # .load_persisted() and updated on every s3p1 push via
    # _apply_battery_percent; reading coord.data.battery_level would show
    # Unknown after restart until the first push arrives. Note: lives in
    # DIAGNOSTIC_SENSORS only because that tuple uses the coord-aware
    # descriptor (value_fn(coord)). No entity_category is set, so this
    # remains a primary (non-diagnostic) entity.
    DreameA2DiagnosticSensorEntityDescription(
        key="battery_level",
        name="Battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        availability_source="mqtt",
        value_fn=lambda coord: coord.state_machine.snapshot().battery_percent,
    ),
    # Error — reads the state machine's LATCHED fault (snapshot.errors), not
    # the last raw s2p2. No entity_category, so it stays a primary entity.
    # Lives in DIAGNOSTIC_SENSORS (not SENSORS) to get coordinator access
    # for state_machine.snapshot() — same pattern as battery_level above.
    DreameA2DiagnosticSensorEntityDescription(
        key="error_description",
        name="Error",
        availability_source="mqtt",
        value_fn=lambda coord: _active_fault_text(coord.state_machine.snapshot()),
    ),
    # WiFi RSSI — reads the persisted snapshot value so it survives HA
    # restarts. The snapshot is loaded from disk via state_machine
    # .load_persisted() and updated on every s1p1 heartbeat via
    # MowerStateMachine.handle_heartbeat; reading coord.data.wifi_rssi_dbm
    # would show Unknown after restart until the next heartbeat arrives.
    DreameA2DiagnosticSensorEntityDescription(
        key="wifi_rssi_dbm",
        name="WiFi RSSI",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        availability_source="mqtt",
        value_fn=lambda coord: coord.state_machine.snapshot().wifi_rssi_dbm,
    ),
    # Position quartet — all read from the persisted snapshot so values survive
    # HA restarts. position_x_m / position_y_m are written by
    # MowerStateMachine.handle_position on every s1p4 telemetry push;
    # position_north_m / position_east_m are written by the same handler from
    # the compass-frame projection, but only when the station-bearing option is
    # set (else they read None).
    DreameA2DiagnosticSensorEntityDescription(
        key="position_x_m",
        name="Position X",
        native_unit_of_measurement="m",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        availability_source="mqtt",
        value_fn=lambda coord: coord.state_machine.snapshot().position_x_m,
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="position_y_m",
        name="Position Y",
        native_unit_of_measurement="m",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        availability_source="mqtt",
        value_fn=lambda coord: coord.state_machine.snapshot().position_y_m,
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="position_north_m",
        name="Position North",
        native_unit_of_measurement="m",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        availability_source="mqtt",
        value_fn=lambda coord: coord.state_machine.snapshot().position_north_m,
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="position_east_m",
        name="Position East",
        native_unit_of_measurement="m",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        availability_source="mqtt",
        value_fn=lambda coord: coord.state_machine.snapshot().position_east_m,
    ),
    # mowing_phase / task_state_code / slam_task_label — snapshot-backed so
    # last-known values survive HA restart instead of going Unknown until
    # the next live MQTT event. Writers in coordinator.handle_property_push
    # route s1p4 / s2p56 / s2p65 updates through state_machine.handle_misc_persisted.
    DreameA2DiagnosticSensorEntityDescription(
        key="mowing_phase",
        name="Mowing phase",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        availability_source="mqtt",
        value_fn=lambda coord: coord.state_machine.snapshot().mowing_phase,
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="task_state_code",
        translation_key="task_state_code",
        name="Task state (raw)",
        entity_category=EntityCategory.DIAGNOSTIC,
        availability_source="mqtt",
        value_fn=lambda coord: coord.state_machine.snapshot().task_state_code,
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="slam_task_label",
        name="SLAM task",
        entity_category=EntityCategory.DIAGNOSTIC,
        availability_source="mqtt",
        value_fn=lambda coord: coord.state_machine.snapshot().slam_task_label,
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="novel_observations",
        translation_key="novel_observations",
        icon="mdi:eye-question",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=True,
        availability_source="mqtt",
        value_fn=lambda coord: (
            coord.novel_registry.snapshot().count
            if coord.novel_registry.snapshot().count is not None
            else 0
        ),
        extra_state_attributes_fn=lambda coord: {
            "observations": [
                {
                    "category": o.category,
                    "detail": o.detail,
                    "first_seen_unix": o.first_seen_unix,
                }
                for o in coord.novel_registry.snapshot().observations
            ],
        },
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="data_freshness",
        translation_key="data_freshness",
        native_unit_of_measurement="s",
        icon="mdi:clock-alert-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_freshness_value,
        extra_state_attributes_fn=_freshness_attrs,
    ),
    # 2026-05-26: time since last MQTT push from the device. Underlying
    # signal for binary_sensor.cloud_connected; also lets dashboards
    # template freshness directly.
    DreameA2DiagnosticSensorEntityDescription(
        key="mqtt_age_s",
        translation_key="mqtt_age_s",
        native_unit_of_measurement="s",
        icon="mdi:lan-pending",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_mqtt_age_value,
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="api_endpoints_supported",
        translation_key="api_endpoints_supported",
        icon="mdi:api",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_api_endpoints_value,
        extra_state_attributes_fn=_api_endpoints_attrs,
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="hardware_serial",
        translation_key="hardware_serial",
        icon="mdi:identifier",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # Hardware serial as printed on the mower (e.g. `G2408053AEE000nnnn`).
        # Sourced from CFG.DEV.sn (preferred path since v1.0.0a76); same
        # value the device-info card shows under "Serial Number".
        value_fn=lambda coord: getattr(coord.data, "hardware_serial", None),
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="firmware_version_dev",
        translation_key="firmware_version_dev",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # Firmware version reported by CFG.DEV.fw — e.g. "4.3.6_0550".
        # Cross-check against the cloud device record's info.version.
        value_fn=lambda coord: getattr(coord.data, "firmware_version", None),
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="ota_capable_raw",
        translation_key="ota_capable_raw",
        icon="mdi:download-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        availability_source="cloud",
        # CFG.DEV.ota — int, semantic UNCONFIRMED. NOT the Auto-update
        # Firmware app toggle (those values don't match). Likely "OTA
        # capability" or "OTA update available". Surfaced raw so future
        # toggle-correlation can pin down the meaning.
        value_fn=lambda coord: getattr(coord.data, "ota_capable_raw", None),
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="ota_state",
        translation_key="ota_state",
        icon="mdi:progress-download",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # s1p2 live OTA state (1=idle, 2=upgrading, 3=success). None until an
        # OTA push. Wire-confirmed 0550->0625, 2026-06-16.
        value_fn=lambda coord: getattr(coord.data, "ota_state", None),
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="ota_progress",
        translation_key="ota_progress",
        icon="mdi:download-network-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # s1p3 live OTA download percent (0..100). Install % is app-local.
        value_fn=lambda coord: getattr(coord.data, "ota_progress", None),
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="cloud_device_id",
        translation_key="cloud_device_id",
        icon="mdi:cloud-tags",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # The Dreame/Xiaomi cloud's internal device record ID — what the
        # cloud API expects in `did` fields. NOT the hardware serial; it's
        # a 32-bit signed integer (often negative) and is unique to the
        # cloud account record, not the physical device. Surfaced for
        # users who need to query the cloud API directly outside HA.
        value_fn=lambda coord: (
            getattr(getattr(coord, "_cloud", None), "device_id", None)
        ),
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="mac_address",
        translation_key="mac_address",
        icon="mdi:network-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # The mower's WiFi MAC. Pulled from the cloud device record's
        # `mac` field in get_devices() / select_first_g2408(). Also wired
        # into DeviceInfo.connections so HA's device card displays it
        # natively (and so other integrations can match against the same
        # physical device).
        value_fn=lambda coord: (
            getattr(getattr(coord, "_cloud", None), "mac_address", None)
        ),
    ),

    # ------ MPOS: raw cloud position reading ------
    # Raw x/y/yaw from the cloud MPOS endpoint, populated by _refresh_mpos.
    # Frame/units are UNVERIFIED — do NOT treat these as the integration's
    # position. Disabled by default; surface for developers / diagnostics.
    DreameA2DiagnosticSensorEntityDescription(
        key="mpos",
        name="MPOS",
        icon="mdi:crosshairs-gps",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        availability_source="cloud",
        value_fn=_mpos_value,
        extra_state_attributes_fn=_mpos_attrs,
    ),

    # ------ Phase D: per-type photo + video count sensors ------
    # All four read from the coordinator's archive objects so counts reflect
    # the on-disk state without waiting for a MowerState push.

    DreameA2DiagnosticSensorEntityDescription(
        key="photos_obstacle",
        name="Obstacle photos",
        icon="mdi:camera-burst",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coord: coord._photo_archive.count_by_category("obstacle"),
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="photos_patrol",
        name="Patrol photos",
        icon="mdi:camera-marker",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coord: coord._photo_archive.count_by_category("patrol"),
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="photos_person",
        name="Person photos",
        icon="mdi:camera-account",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coord: coord._photo_archive.count_by_category("ai_human"),
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="videos",
        name="Videos",
        icon="mdi:video",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coord: coord._video_archive.count,
    ),
    # latest_video: state = duration (seconds) of the newest clip; attribute
    # "mp4_path" = absolute filesystem path to the MP4 file (for HA media
    # player / downloader integrations). None when archive is empty.
    DreameA2DiagnosticSensorEntityDescription(
        key="latest_video",
        name="Latest video",
        icon="mdi:video-box",
        native_unit_of_measurement="s",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coord: (
            (coord._video_archive.latest() or None) and coord._video_archive.latest().duration
        ),
        extra_state_attributes_fn=lambda coord: (
            {"mp4_path": str(coord._video_archive.root / v.mp4_filename)}
            if (v := coord._video_archive.latest()) is not None
            else {}
        ),
    ),

    # ------ CFG diagnostic observability sensors (added 2026-06-04) ------
    # All three read from MowerState (coord.data) which is populated by
    # cfg_to_state_updates on every 2-min cloud refresh. Disabled by default.

    DreameA2DiagnosticSensorEntityDescription(
        key="weather_forecast_reference",
        translation_key="weather_forecast_reference",
        icon="mdi:weather-partly-cloudy",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        availability_source="cloud",
        # CFG.WRF int {0, 1} → "on" / "off" string. Returns None when not
        # yet received from the cloud (before first 2-min refresh).
        value_fn=lambda coord: (
            "on" if getattr(coord.data, "weather_forecast_reference", None) == 1
            else "off" if getattr(coord.data, "weather_forecast_reference", None) == 0
            else None
        ),
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="timezone",
        translation_key="timezone",
        icon="mdi:earth-clock",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        availability_source="cloud",
        # CFG.TIME — IANA timezone name, e.g. "Europe/Oslo". Returns None
        # until the first cloud refresh delivers the CFG payload.
        value_fn=lambda coord: getattr(coord.data, "timezone", None),
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="cfg_version",
        translation_key="cfg_version",
        icon="mdi:counter",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        availability_source="cloud",
        # CFG.VER — monotonic int counter incremented on every CFG write.
        # Distinct from sensor.firmware_version (which tracks the OTA firmware
        # version from device.info.version, not this CFG-write counter).
        value_fn=lambda coord: getattr(coord.data, "cfg_version", None),
    ),
)


# ---------------------------------------------------------------------------
# Device-level entity classes
# ---------------------------------------------------------------------------

class DreameA2CurrentActivitySensor(_SnapshotEnumSensorBase):
    _attr_name = "Current activity"
    _attr_icon = "mdi:robot-mower"
    _attr_translation_key = "current_activity"
    _SNAPSHOT_FIELD = "current_activity"
    _KEY = "current_activity"
    _attr_options = [
        "mowing", "paused", "repositioning", "returning", "charge_resume",
        "cruising_to_point", "at_point", "fast_mapping",
        "driving_blades_up", "patrol_edge", "patrol_point", "idle",
    ]


class DreameA2LocationSensor(_SnapshotEnumSensorBase):
    _attr_name = "Location"
    _attr_icon = "mdi:map-marker"
    _attr_translation_key = "mower_location"
    _SNAPSHOT_FIELD = "location"
    _KEY = "mower_location"
    _attr_options = ["at_dock", "on_lawn", "at_point", "outside_known_area"]


class DreameA2PositioningHealthSensor(_SnapshotEnumSensorBase):
    _attr_name = "Positioning health"
    _attr_icon = "mdi:radar"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "positioning_health"
    _SNAPSHOT_FIELD = "positioning_health"
    _KEY = "positioning_health"
    _attr_options = ["localized", "relocating", "stuck"]


class DreameA2MqttConnectivitySensor(_SnapshotEnumSensorBase):
    _attr_name = "MQTT connectivity"
    _attr_icon = "mdi:lan-connect"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "mqtt_connectivity"
    _SNAPSHOT_FIELD = "mqtt_connectivity"
    _KEY = "mqtt_connectivity"
    _attr_options = ["online", "stale"]
    # Self-referential link reporter: it REPORTS MQTT freshness, so it must
    # never be gated on it (else it'd vanish exactly when it's useful).
    # Override the _SnapshotEnumSensorBase mqtt default back to None.
    _availability_source = None


class DreameA2PickedSessionSensor(
    _MowerScopedEntity, CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Exposes the picker-selected session as state + attributes.

    State = the picker label (matches the dropdown). Attributes carry
    the full summary dict built by session_card.build_picked_session_summary.
    Used by the Sessions tab's per-session detail cards.
    """

    _attr_has_entity_name = True
    _attr_name = "Picked session"
    _attr_icon = "mdi:history"
    _MOWER_KEY = "picked_session"
    # The summary dict (track/legs/segments) routinely exceeds the recorder's
    # 16 KB per-attribute cap, which logs a WARNING and refuses to store it.
    # These attributes are point-in-time UI payloads, not history — exclude the
    # whole entity's attributes from the recorder. "*" is homeassistant.const
    # MATCH_ALL (the recorder's "exclude every attribute" sentinel); the literal
    # avoids importing a symbol the stubbed-HA test venv doesn't provide.
    _unrecorded_attributes = frozenset({"*"})

    @property
    def native_value(self) -> str | None:
        summary = self.coordinator._picked_session_summary
        return summary.get("label") if summary else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.coordinator._picked_session_summary or {}


class DreameA2PhotoGallerySensor(
    _MowerScopedEntity, CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Exposes the OSS photo/video gallery manifest as state + attributes.

    State = the total item count. Attributes carry the full newest-first
    ``items`` list (photos + videos, each with a signed media URL) built by
    ``_refresh_oss_gallery``. Consumed by the gallery dashboard card.
    """

    _attr_has_entity_name = True
    _attr_name = "Photo gallery"
    _attr_icon = "mdi:image-multiple"
    _MOWER_KEY = "photo_gallery"
    # The items list (one row per archived photo/video, with signed URLs) easily
    # exceeds the recorder's per-attribute cap — keep the whole entity's
    # attributes out of the recorder (mirrors DreameA2PickedSessionSensor). "*"
    # is homeassistant.const MATCH_ALL (the recorder's exclude-all sentinel).
    _unrecorded_attributes = frozenset({"*"})

    @property
    def native_value(self) -> int:
        return len(self.coordinator._photo_gallery)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"items": self.coordinator._photo_gallery}


class DreameA2Sensor(
    _FreshnessAvailableMixin, CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """A coordinator-backed sensor entity."""

    _attr_has_entity_name = True
    entity_description: DreameA2SensorEntityDescription

    def __init__(
        self,
        coordinator: DreameA2MowerCoordinator,
        description: DreameA2SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = mower_unique_id(coordinator, description.key)
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def _availability_source(self) -> str | None:
        # Bridge the per-row descriptor field to the mixin (shadows the
        # mixin's class attr via MRO). Rows with availability_source=None
        # are not freshness-gated.
        return self.entity_description.availability_source

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.extra_attributes_fn
        if fn is None:
            return None
        raw = fn(self.coordinator.data)
        return {k: v for k, v in raw.items() if v is not None} if raw else None


class DreameA2DiagnosticSensor(
    _FreshnessAvailableMixin, CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """A coordinator-backed diagnostic sensor.

    Reads from the coordinator directly (registry, freshness tracker,
    endpoint log) rather than from MowerState. Uses
    ``DreameA2DiagnosticSensorEntityDescription`` with ``value_fn``
    accepting a coordinator and an optional
    ``extra_state_attributes_fn``.
    """

    _attr_has_entity_name = True
    entity_description: DreameA2DiagnosticSensorEntityDescription

    def __init__(
        self,
        coordinator: DreameA2MowerCoordinator,
        description: DreameA2DiagnosticSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = mower_unique_id(coordinator, description.key)
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def _availability_source(self) -> str | None:
        # Bridge the per-row descriptor field to the mixin (shadows the
        # mixin's class attr via MRO). Rows with availability_source=None
        # are not freshness-gated.
        return self.entity_description.availability_source

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.extra_state_attributes_fn
        if fn is None:
            return None
        return fn(self.coordinator)


# ---------------------------------------------------------------------------
# Task 12: cloud_state-driven sensors — OTA status + schedule count.
# These read from coordinator.cloud_state directly (not MowerState).
# ---------------------------------------------------------------------------


class DreameA2OtaStatusSensor(
    _MowerScopedEntity,
    _FreshnessAvailableMixin,
    CoordinatorEntity[DreameA2MowerCoordinator],
    SensorEntity,
):
    """Cloud-reported OTA upgrade status."""

    _attr_has_entity_name = True
    _attr_translation_key = "ota_status"
    _attr_name = "OTA status"
    _attr_should_poll = False
    _availability_source = "cloud"
    _MOWER_KEY = "ota_status"

    @property
    def native_value(self) -> str | int | None:
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is None or cs.ota_status is None:
            return None
        return cs.ota_status[0]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is None or cs.ota_status is None:
            return {}
        return {"percent": cs.ota_status[1]}


class DreameA2ScheduleCountSensor(
    _MowerScopedEntity,
    _FreshnessAvailableMixin,
    CoordinatorEntity[DreameA2MowerCoordinator],
    SensorEntity,
):
    """Number of cloud-side schedule slots."""

    _attr_has_entity_name = True
    _attr_translation_key = "schedule_count"
    _attr_name = "Schedule count"
    _attr_should_poll = False
    _availability_source = "cloud"
    _MOWER_KEY = "schedule_count"

    @property
    def native_value(self) -> int | None:
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is None:
            return None
        return len(cs.schedule.slots)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is None:
            return {}
        return {
            "slots": [
                {
                    "slot_id": s.slot_id,
                    "name": s.name,
                    "plans": [
                        {
                            "time": _fmt_hhmm(p.time_min),
                            "days": _fmt_weekdays(p.weekday_mask),
                            "action": _fmt_action(p.action_type),
                            "zone_id": p.zone_id,
                        }
                        for p in s.plans
                    ],
                }
                for s in cs.schedule.slots
            ],
            "version": cs.schedule.version,
        }


class DreameA2WifiRefreshStatusSensor(
    _MowerScopedEntity, CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Timestamp of the last WiFi archive refresh attempt.

    State is the unix timestamp (as datetime) of the last
    ``coordinator.refresh_wifi_archive`` invocation — typically when
    the user pressed the Refresh button. HA renders this as
    "X minutes ago" in the UI via ``SensorDeviceClass.TIMESTAMP``.

    ``extra_state_attributes`` exposes the per-refresh detail
    (`result`, `fetched`, `new`) for users who want to dig in.
    """

    _attr_has_entity_name = True
    _attr_name = "WiFi map last refresh"
    _attr_icon = "mdi:wifi-refresh"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False
    _MOWER_KEY = "wifi_refresh_status"

    @property
    def native_value(self) -> datetime | None:
        status = getattr(self.coordinator, "_wifi_archive_last_refresh", {})
        ts = status.get("last_attempt_unix")
        if not isinstance(ts, (int, float)) or ts <= 0:
            return None
        return datetime.fromtimestamp(int(ts), tz=UTC)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = getattr(self.coordinator, "_wifi_archive_last_refresh", {})
        # Exclude `last_attempt_unix` from attributes — it's already the state.
        return {k: v for k, v in status.items() if k != "last_attempt_unix"}


class DreameA2RainResumeSensor(
    _MowerScopedEntity, CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """When the mower will retry mowing after a rain-protection delay.

    State is the projected resume time (rain_delay_started_at +
    resume_hours), rendered by HA as a live "in N hours" countdown via
    SensorDeviceClass.TIMESTAMP — no server-side ticking. Unknown when the
    mower is not in a rain delay. See
    docs/superpowers/specs/2026-05-29-event-surface-audit-rework-design.md.
    """

    _attr_has_entity_name = True
    _attr_name = "Rain resume at"
    _attr_icon = "mdi:weather-rainy"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_should_poll = False
    _MOWER_KEY = "rain_resume_at"

    @property
    def native_value(self) -> datetime | None:
        ts = self.coordinator.rain_resume_at_unix
        if ts is None:
            return None
        return datetime.fromtimestamp(int(ts), tz=UTC)


class DreameA2WifiHeatmapAgeSensor(
    _MowerScopedEntity, CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Age (in seconds) of the newest archived WiFi heatmap (v1.0.10a6+).

    State is the elapsed time between *now* and the parsed ``unix_ts``
    of the newest entry in ``coordinator._wifi_archive_index``. Unknown
    when the archive is empty.

    Use case: surface "heatmap is X hours old" so users can spot when
    the cloud's nightly auto-generation has stalled (typically because
    the mower hasn't been online recently).

    Returns ``None`` when the archive is empty or when the newest
    entry has an unparsed timestamp (``unix_ts == 0``).
    """

    _attr_has_entity_name = True
    _attr_name = "WiFi heatmap age"
    _attr_icon = "mdi:wifi-cog"
    _attr_native_unit_of_measurement = "s"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False
    _attr_entity_registry_enabled_default = False
    _MOWER_KEY = "wifi_heatmap_age"

    def _newest_unix_ts(self) -> int | None:
        idx = getattr(self.coordinator, "_wifi_archive_index", None) or []
        if not idx:
            return None
        try:
            newest = max(int(e.unix_ts) for e in idx if int(e.unix_ts) > 0)
        except ValueError:
            return None
        return newest

    @property
    def native_value(self) -> int | None:
        newest = self._newest_unix_ts()
        if newest is None:
            return None
        import time as _time
        now_ts = int(_time.time())
        age = now_ts - newest
        return age if age >= 0 else 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        newest = self._newest_unix_ts()
        if newest is None:
            return {}
        return {
            "newest_unix_ts": newest,
            "newest_iso": datetime.fromtimestamp(newest, tz=UTC).isoformat(),
            "archive_total": len(
                getattr(self.coordinator, "_wifi_archive_index", []) or []
            ),
        }


class DreameA2LastNotificationSensor(
    _MowerScopedEntity,
    _FreshnessAvailableMixin,
    CoordinatorEntity[DreameA2MowerCoordinator],
    SensorEntity,
):
    """Most recent app-style notification synthesized from s2p2 transitions.

    Sticks at the last emitted value; never auto-clears. Shows the
    human-readable text with code + event_type as extra attributes.
    Source: coordinator._last_notification (updated by _fire_alert).
    """

    _attr_has_entity_name = True
    _attr_name = "Last notification"
    _attr_icon = "mdi:bell-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False
    _availability_source = "mqtt"
    _MOWER_KEY = "last_notification"

    @property
    def native_value(self) -> str | None:
        entry = getattr(self.coordinator, "_last_notification", None)
        if not entry:
            return None
        return entry.get("text")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        entry = getattr(self.coordinator, "_last_notification", None)
        if not entry:
            return {}
        return {
            "event_type": entry.get("event_type"),
            "code": entry.get("code"),
            "fired_at": entry.get("fired_at"),
        }


class DreameA2ApiEndpointSensor(
    _MowerScopedEntity, CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Cloud API endpoint host:port the integration is talking to.

    Config/probe-derived (host comes from the cloud client, not a live link),
    so it is intentionally NOT freshness-gated — no ``_availability_source``,
    no ``_FreshnessAvailableMixin``. Confirmed un-gated (P2.4).
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "API endpoint"
    _attr_translation_key = "api_endpoint"
    _attr_icon = "mdi:server-network"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _MOWER_KEY = "api_endpoint"

    @property
    def native_value(self):
        cloud = getattr(self.coordinator, "_cloud", None)
        if cloud is None:
            return None
        host = getattr(cloud, "host", None) or "eu.iot.dreame.tech"
        return f"{host}:19973"


class DreameA2IntegrationVersionSensor(
    _MowerScopedEntity, CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Currently-running integration version, sourced from manifest.json."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Integration version"
    _attr_translation_key = "integration_version"
    _attr_icon = "mdi:package-variant"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _MOWER_KEY = "integration_version"

    @property
    def native_value(self):
        return _manifest_version()


# ---------------------------------------------------------------------------
# Message-list sensors (T6)
# Three read-only parent-device sensors: state = unread count, items attr = list.
# ---------------------------------------------------------------------------

class _DreameA2MessageListSensor(
    _MowerScopedEntity, CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Base: state = unread count, items attr = the normalised list.

    Reads ``self.coordinator.data.<_FIELD>`` (a MowerState list field).
    The full list is excluded from the recorder (mirrors DreameA2PhotoGallerySensor).
    """

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _unrecorded_attributes = frozenset({"*"})
    _FIELD: str = ""  # MowerState list attribute name

    def _items(self) -> list:
        return list(getattr(self.coordinator.data, self._FIELD, None) or [])

    @property
    def native_value(self) -> int:
        # State is the UNREAD count (not total): the actionable signal for
        # messages is "how many are new". Total is len(items) in the attrs.
        return sum(1 for it in self._items() if it.get("unread"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"items": self._items()}


class DreameA2DeviceMessagesSensor(_DreameA2MessageListSensor):
    """Device-targeted messages (device_messages list)."""

    _attr_name = "Device messages"
    _attr_icon = "mdi:robot"
    _MOWER_KEY = "device_messages"
    _FIELD = "device_messages"


class DreameA2ServiceMessagesSensor(_DreameA2MessageListSensor):
    """Service/account messages (service_messages list)."""

    _attr_name = "Service messages"
    _attr_icon = "mdi:email-newsletter"
    # _MOWER_KEY differs from _FIELD ("service_messages") so the unique_id does
    # not collide with the existing descriptor-based service_messages_unread
    # sensor / any future descriptor keyed on "service_messages".
    _MOWER_KEY = "service_messages_list"
    _FIELD = "service_messages"


class DreameA2SharedMessagesSensor(_DreameA2MessageListSensor):
    """Shared messages from other account members (shared_messages list)."""

    _attr_name = "Shared messages"
    _attr_icon = "mdi:account-multiple"
    _MOWER_KEY = "shared_messages"
    _FIELD = "shared_messages"
