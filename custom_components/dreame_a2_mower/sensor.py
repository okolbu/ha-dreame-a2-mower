"""Support for Dreame Mower sensors."""

from __future__ import annotations

import json as _json
import math
import time
from dataclasses import dataclass
from datetime import datetime


def _mowing_zone_display(telemetry, device):
    """Map the raw phase byte from s1p4 to a user-readable zone label.

    Prefers the zone name from the cloud-built map's segments dict
    (e.g. "Zone1", or a user-renamed custom label); falls back to a
    1-indexed numeric string ("1", "2", ...) so the sensor never
    shows "0" — mower firmware numbers zones from 0, but the app and
    humans number from 1.
    """
    if telemetry is None:
        return None
    raw = getattr(telemetry, "phase_raw", None)
    if raw is None:
        return None
    try:
        zone_ix = int(raw)
    except (TypeError, ValueError):
        return None
    zone_id_1based = zone_ix + 1
    # Attempt to resolve via segment/zone metadata if the cloud-built
    # map supplied names. `device.status.segments` is a dict keyed by
    # zone_id (1-based). Silent fallback if anything's missing.
    try:
        segments = getattr(device.status, "segments", None) or {}
        seg = segments.get(zone_id_1based)
        if seg is not None:
            name = getattr(seg, "custom_name", None) or getattr(seg, "name", None)
            if name:
                return str(name)
    except Exception:
        pass
    return str(zone_id_1based)


def _project_to_compass(telemetry, device, axis: str):
    """Project mower-frame (x_m, y_m_calibrated) onto a compass axis.

    Mower +X points in the dock's facing direction, encoded in
    ``device.station_bearing_deg`` (0°=N, 90°=E, 180°=S, 270°=W).
    Mower +Y is 90° clockwise from +X. Projection formulas:
        north = x·cos(θ) − y·sin(θ)
        east  = x·sin(θ) + y·cos(θ)
    """
    if telemetry is None:
        return None
    bearing = float(getattr(device, "station_bearing_deg", 0.0) or 0.0)
    theta = math.radians(bearing)
    x_m = telemetry.x_m
    y_m = telemetry.y_m
    if axis == "north":
        return round(x_m * math.cos(theta) - y_m * math.sin(theta), 2)
    if axis == "east":
        return round(x_m * math.sin(theta) + y_m * math.cos(theta), 2)
    return None


def _format_time_window(lst, start_idx=1, end_idx=2):
    """Format `[..., start_min, end_min, ...]` as 'HH:MM-HH:MM'.
    Returns None when input is missing or malformed."""
    if not isinstance(lst, list) or len(lst) <= max(start_idx, end_idx):
        return None
    s = lst[start_idx]
    e = lst[end_idx]
    if not (isinstance(s, int) and isinstance(e, int)):
        return None
    return f"{s // 60:02d}:{s % 60:02d}-{e // 60:02d}:{e % 60:02d}"


def _wear_health(cms_list, idx, max_minutes):
    """Convert wear minutes at `cms_list[idx]` to remaining-life %.
    Returns None for missing/malformed input."""
    if not isinstance(cms_list, list) or idx >= len(cms_list):
        return None
    minutes = cms_list[idx]
    if not isinstance(minutes, (int, float)):
        return None
    return max(0, round((1 - minutes / max_minutes) * 100))


from homeassistant.components.sensor import (
    ENTITY_ID_FORMAT,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    UNIT_MINUTES,
    UNIT_HOURS,
    UNIT_PERCENT,
    UNIT_AREA,
    UNIT_TIMES,
    UNIT_DAYS,
)
from .dreame import (
    DreameMowerProperty,
    DreameMowerRelocationStatus,
    DreameMowerStreamStatus,
)
from .dreame.const import ATTR_VALUE

from .coordinator import DreameMowerDataUpdateCoordinator
from .entity import DreameMowerEntity, DreameMowerEntityDescription


STREAM_STATUS_TO_ICON = {
    DreameMowerStreamStatus.IDLE: "mdi:webcam",
    DreameMowerStreamStatus.VIDEO: "mdi:cctv",
    DreameMowerStreamStatus.AUDIO: "mdi:microphone",
    DreameMowerStreamStatus.RECORDING: "mdi:record-rec",
}

RELOCATION_STATUS_TO_ICON = {
    DreameMowerRelocationStatus.LOCATED: "mdi:map-marker-radius",
    DreameMowerRelocationStatus.SUCCESS: "mdi:map-marker-check",
    DreameMowerRelocationStatus.FAILED: "mdi:map-marker-alert",
    DreameMowerRelocationStatus.LOCATING: "mdi:map-marker-distance",
}


@dataclass
class DreameMowerSensorEntityDescription(DreameMowerEntityDescription, SensorEntityDescription):
    """Describes DreameMower sensor entity."""


def _truncate_map_attrs_fn(device):
    """Build the map_keys_raw attrs dict, truncating each per-key
    value to a JSON string of at most 800 chars so the total fits
    under HA's 16 KB recorder limit. The dashboard renders code
    blocks at the same 800-char truncation, so no visual loss.

    Small scalar values pass through unchanged. Bulky dicts/lists
    (mowingAreas, contours, paths) become JSON strings — still
    Markdown-friendly in the dashboard.
    """
    payload = getattr(device, "_latest_cloud_map_payload", None) or {}
    out: dict = {}
    for k, v in payload.items():
        if isinstance(v, (int, float, bool, str)) or v is None:
            out[k] = v
            continue
        try:
            s = _json.dumps(v, default=str)
        except Exception:
            s = repr(v)
        if len(s) > 800:
            out[k] = s[:800] + f"… (truncated, full len={len(s)})"
        else:
            out[k] = v  # small enough to keep native
    # Truncate old/new values inside _recent_changes the same way as
    # top-level keys, otherwise a single big-key edit can blow past
    # the 16 KB attrs limit on its own. Dashboard renders 800-char
    # code blocks so no visual loss.
    def _trunc(v):
        if isinstance(v, (int, float, bool, str)) or v is None:
            return v
        try:
            s = _json.dumps(v, default=str)
        except Exception:
            s = repr(v)
        if len(s) > 800:
            return s[:800] + f"… (truncated, full len={len(s)})"
        return v
    out["_recent_changes"] = {
        k: {**d, "old": _trunc(d.get("old")), "new": _trunc(d.get("new"))}
        for k, d in (getattr(device, "_map_recent_changes", None) or {}).items()
    }
    out["_last_diff"] = list(getattr(device, "_map_last_diff", None) or [])
    out["_last_diff_at"] = getattr(device, "_map_last_diff_at", None)
    return out


def _cfg_key_present(key: str, min_len: int = 0):
    """available_fn factory: gate an entity on the named CFG key actually
    being present in the device's last getCFG snapshot.

    Without this gate CFG-derived sensors would materialise immediately and
    sit with state=None until the first successful `refresh_cfg`, which HA
    renders as "Unknown". Using `available=False` instead shows the clearer
    "Unavailable" until data arrives, and also hides the entity on
    firmwares that simply don't return the key.
    """
    def _check(device) -> bool:
        cfg = getattr(device, "cfg", None) or {}
        val = cfg.get(key)
        if val is None:
            return False
        if min_len > 0:
            return isinstance(val, (list, tuple)) and len(val) >= min_len
        return True
    return _check


def _dock_pos_present(device) -> bool:
    """available_fn: dock-position dict populated by the getDockPos action."""
    return isinstance(getattr(device, "dock_pos", None), dict) and bool(device.dock_pos)


SENSORS: tuple[DreameMowerSensorEntityDescription, ...] = (
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.CLEANING_TIME,
        icon="mdi:timer-sand",
        native_unit_of_measurement=UNIT_MINUTES,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.CLEANED_AREA,
        icon="mdi:ruler-square",
        native_unit_of_measurement=UNIT_AREA,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.STATE,
        icon="mdi:robot-mower",
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.STATUS,
        icon="mdi:mower",
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.RELOCATION_STATUS,
        icon_fn=lambda value, device: RELOCATION_STATUS_TO_ICON.get(
            device.status.relocation_status, "mdi:map-marker-radius"
        ),
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.TASK_TYPE,
        icon="mdi:sitemap",
        exists_fn=lambda description, device: device.capability.task_type,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.STREAM_STATUS,
        icon_fn=lambda value, device: STREAM_STATUS_TO_ICON.get(device.status.stream_status, "mdi:webcam-off"),
        exists_fn=lambda description, device: device.capability.camera_streaming
        or DreameMowerEntityDescription().exists_fn(description, device),
    ),
    # `sensor.error` — disabled for g2408. The upstream ERROR property
    # maps to `s2p2` which carries SECONDARY state codes on this mower
    # (27/31/33/43/48/50/53/54/56/70/71/75 — mowing phase / start /
    # return / rain / positioning-failed / MP-arrived / low-temp …),
    # not a real fault enum. The g2408 overlay redirects ERROR to
    # siid/piid 999/999 (a slot the mower never emits on) to keep the
    # upstream translator from mislabelling valid state codes as
    # specific faults. As a result this sensor was permanently
    # "Unavailable" on the device page — worse than useless since
    # users expect to look here for error information.
    #
    # Instead, the real g2408 error conditions surface as dedicated
    # binary_sensors (PROBLEM device_class): `battery_temp_low`,
    # `positioning_failed`, `rain_protection_active`. SLAM task
    # activity goes to `sensor.slam_activity`.
    # See docs/research/g2408-protocol.md §4.1 for the s2p2 catalogue
    # and §4.4 / §4.8 for the condition semantics.
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.CHARGING_STATUS,
        icon="mdi:home-lightning-bolt",
        # Redundant with sensor.state during normal charging (both say
        # "charging"), but the two channels can diverge — e.g. after a
        # user-cancel on the lawn state=idle while charging_status=not
        # charging. Keep it, but park it under Diagnostic so it doesn't
        # clutter the main dashboard next to `sensor.state`.
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # SLAM activity — g2408-specific. s2p65 on this mower is a string
    # property that carries the task-type label for the current SLAM
    # operation (e.g. `TASK_SLAM_RELOCATE` during LiDAR relocalization,
    # see §4.8). The value is a latched "most-recent" — the mower does
    # not fire this while at rest, so a stale reading means "last SLAM
    # task we saw", not "currently active".
    DreameMowerSensorEntityDescription(
        key="slam_activity",
        name="SLAM Activity",
        icon="mdi:crosshairs-gps",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda value, device: device.slam_activity,
        exists_fn=lambda description, device: True,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.BATTERY_LEVEL,
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=UNIT_PERCENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.BLADES_LEFT,
        icon="mdi:car-turbocharger",
        native_unit_of_measurement=UNIT_PERCENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        # entity_registry_enabled_default=False,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.BLADES_TIME_LEFT,
        icon="mdi:car-turbocharger",
        native_unit_of_measurement=UNIT_HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        # entity_registry_enabled_default=False,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.SIDE_BRUSH_LEFT,
        icon="mdi:pinwheel-outline",
        native_unit_of_measurement=UNIT_PERCENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        # entity_registry_enabled_default=False,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.SIDE_BRUSH_TIME_LEFT,
        icon="mdi:pinwheel-outline",
        native_unit_of_measurement=UNIT_HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        # entity_registry_enabled_default=False,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.FILTER_LEFT,
        icon="mdi:air-filter",
        native_unit_of_measurement=UNIT_PERCENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        # entity_registry_enabled_default=False,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.FILTER_TIME_LEFT,
        icon="mdi:air-filter",
        native_unit_of_measurement=UNIT_HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        # entity_registry_enabled_default=False,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.SENSOR_DIRTY_LEFT,
        icon="mdi:radar",
        native_unit_of_measurement=UNIT_PERCENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        # entity_registry_enabled_default=False,
        exists_fn=lambda description, device: not device.capability.disable_sensor_cleaning,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.SENSOR_DIRTY_TIME_LEFT,
        icon="mdi:radar",
        native_unit_of_measurement=UNIT_HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        # entity_registry_enabled_default=False,
        exists_fn=lambda description, device: not device.capability.disable_sensor_cleaning,
    ),
    # Removed vacuum-only consumable sensors (Cleanup Phase 1,
    # v2.0.0-alpha.32): TANK_FILTER_LEFT / TANK_FILTER_TIME_LEFT,
    # SILVER_ION_LEFT / SILVER_ION_TIME_LEFT, LENSBRUSH_LEFT /
    # LENSBRUSH_TIME_LEFT, SQUEEGEE_LEFT / SQUEEGEE_TIME_LEFT. The
    # A2 mower has no water tank, no UV silver-ion sanitiser, no
    # lens brush, no squeegee — these properties never fire on
    # g2408 and the corresponding entities were permanently
    # "Unavailable" on the device page.
    # Lifetime-totals from siid=12 (cleaning-history service).
    # - FIRST_CLEANING_DATE → sensor.first_mowing_date (timestamp)
    # - TOTAL_CLEANING_TIME → sensor.total_mowing_time  (minutes)
    # - CLEANING_COUNT      → sensor.mowing_count       (count)
    # - TOTAL_CLEANED_AREA  → sensor.total_mowed_area   (m²)
    # Entity keys come from PROPERTY_TO_NAME (mower-themed names).
    # Removed in alpha.27 because siid=12 wasn't returning data; re-added
    # in alpha.102 after the alpha.78-81 cloud-URL breakthrough that
    # unblocked a whole category of previously-failing RPCs. If siid=12
    # still returns nothing on g2408 firmware, these will show as
    # Unavailable — safe to leave in place either way.
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.FIRST_CLEANING_DATE,
        icon="mdi:calendar-start",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda value, device: (
            datetime.fromtimestamp(value).replace(
                tzinfo=datetime.now().astimezone().tzinfo
            )
            if isinstance(value, (int, float)) and value > 0 else None
        ),
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.TOTAL_CLEANING_TIME,
        icon="mdi:timer-outline",
        native_unit_of_measurement=UNIT_MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.CLEANING_COUNT,
        icon="mdi:counter",
        native_unit_of_measurement=UNIT_TIMES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.TOTAL_CLEANED_AREA,
        icon="mdi:set-square",
        native_unit_of_measurement=UNIT_AREA,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    DreameMowerSensorEntityDescription(
        key="cruising_history",
        icon="mdi:map-marker-path",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda value, device: device.status.last_cruising_time,
        exists_fn=lambda description, device: device.capability.map and device.capability.cruising,
        attrs_fn=lambda device: device.status.cruising_history,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.CLEANING_PROGRESS,
        icon="mdi:home-percent",
        native_unit_of_measurement=UNIT_PERCENT,
        entity_category=None,
    ),
    DreameMowerSensorEntityDescription(
        key="firmware_version",
        icon="mdi:chip",
        value_fn=lambda value, device: device.info.version,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # --- g2408 mowing telemetry sensors (decoded from s1p4 blob) ---
    # exists_fn=always-True: s1p4 is only broadcast during active mowing, so
    # device.data[MOWING_TELEMETRY] is empty when the entity setup runs after
    # HA restart on a docked mower. Without this override the telemetry
    # sensors never register and never appear in the UI.
    DreameMowerSensorEntityDescription(
        key="mowing_position_x",
        property_key=DreameMowerProperty.MOWING_TELEMETRY,
        name="Position X",
        icon="mdi:axis-x-arrow",
        native_unit_of_measurement="m",
        exists_fn=lambda description, device: True,
        value_fn=lambda value, device: round(value.x_m, 2) if value is not None else None,
    ),
    # Position Y (calibrated): raw Y value × 0.625 → metres.
    # Raw Y at bytes [3-4] systematically over-reads by ~60% compared to
    # tape-measured physical position. Two independent data points agree
    # (raw 15855 ≈ 10 m, raw 16624 = 10.3 m tape-measured) → factor 0.625.
    # Likely a mower-firmware calibration constant (wheel circumference
    # or encoder pulses/rev slightly off). Apply the factor so the Y
    # sensor shows physically meaningful metres. If future data shows
    # the factor drifting with session length / grass height / pattern,
    # revisit and make per-device configurable.
    DreameMowerSensorEntityDescription(
        key="mowing_position_y",
        property_key=DreameMowerProperty.MOWING_TELEMETRY,
        name="Position Y",
        icon="mdi:axis-y-arrow",
        native_unit_of_measurement="m",
        exists_fn=lambda description, device: True,
        value_fn=lambda value, device: round(value.y_m, 2) if value is not None else None,
    ),
    # X/Y raw diagnostic sensors removed in alpha.101 — they existed
    # during the pre-alpha.98 decoder-bug-hunting period (user watching
    # the 16× overshoot live). With the decoder now correct and matching
    # the apk spec, the metres-scale `Position X` / `Position Y` sensors
    # above are sufficient.

    # Path-point sequence counter from s1p4 bytes [7-9]. Monotonically
    # increasing within a session, resets on new session. Diagnostic-only:
    # useful for spotting dropped frames and cross-referencing cloud
    # path data by index.
    DreameMowerSensorEntityDescription(
        key="mowing_trace_index",
        property_key=DreameMowerProperty.MOWING_TELEMETRY,
        name="Trace Index",
        icon="mdi:counter",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        exists_fn=lambda description, device: True,
        value_fn=lambda value, device: (
            value.trace_start_index if value is not None else None
        ),
    ),
    # Compass-projected sensors — useful when the user has oriented the
    # dock in a known compass direction (configured via the "Station
    # Direction (°)" option). Projects the mower-frame (x, y) into
    # world (north, east) metres. Mower +X points in the dock's facing
    # direction = `station_bearing_deg` on the compass; mower +Y is
    # 90° clockwise from +X. bearing=0 (default, "station faces north")
    # means north=x_m, east=y_m — useful even without calibration.
    DreameMowerSensorEntityDescription(
        key="mowing_position_north_m",
        property_key=DreameMowerProperty.MOWING_TELEMETRY,
        name="Position North",
        icon="mdi:compass",
        native_unit_of_measurement="m",
        exists_fn=lambda description, device: True,
        value_fn=lambda value, device: _project_to_compass(value, device, axis="north"),
    ),
    DreameMowerSensorEntityDescription(
        key="mowing_position_east_m",
        property_key=DreameMowerProperty.MOWING_TELEMETRY,
        name="Position East",
        icon="mdi:compass",
        native_unit_of_measurement="m",
        exists_fn=lambda description, device: True,
        value_fn=lambda value, device: _project_to_compass(value, device, axis="east"),
    ),
    # Exposed as "Mowing Zone" because byte [8] of s1p4 is the internal
    # zone-ID the mower firmware is currently mowing in — each distinct
    # value corresponds to a distinct non-overlapping X/Y region on the
    # lawn. The entity key stays `mowing_phase` so existing automations
    # keep working. Resolves the zone name from `device.status.segments`
    # when available (cloud-built map provides segment definitions),
    # otherwise falls back to a 1-indexed zone number so the state is
    # never "0" (user-reported that was confusing; mower firmware
    # numbers zones from 0 but the app and humans number from 1).
    DreameMowerSensorEntityDescription(
        key="mowing_phase",
        property_key=DreameMowerProperty.MOWING_TELEMETRY,
        name="Mowing Zone",
        icon="mdi:vector-square",
        exists_fn=lambda description, device: True,
        value_fn=lambda value, device: _mowing_zone_display(value, device),
    ),
    DreameMowerSensorEntityDescription(
        key="session_area_mowed",
        property_key=DreameMowerProperty.MOWING_TELEMETRY,
        name="Session Area Mowed",
        icon="mdi:texture-box",
        native_unit_of_measurement=UNIT_AREA,
        exists_fn=lambda description, device: True,
        value_fn=lambda value, device: value.area_mowed_m2 if value is not None else None,
    ),
    DreameMowerSensorEntityDescription(
        key="session_distance",
        property_key=DreameMowerProperty.MOWING_TELEMETRY,
        name="Session Distance",
        icon="mdi:map-marker-distance",
        native_unit_of_measurement="m",
        exists_fn=lambda description, device: True,
        value_fn=lambda value, device: value.distance_m if value is not None else None,
    ),
    # Mower heading from s1p4 byte [6] (0..255 -> 0..360°). Dock-relative
    # frame: 0° points along the dock's +X direction, NOT compass north.
    # Users wanting a compass heading can offset by `station_bearing_deg`
    # (same trick as the Position North / East sensors).
    # Decode confirmed 2026-04-24 via motion-direction correlation across
    # 5586 samples (median error 13°). See docs/research/g2408-protocol.md
    # §2.1 s1p4 row for the validation methodology.
    DreameMowerSensorEntityDescription(
        key="heading_deg",
        property_key=DreameMowerProperty.MOWING_TELEMETRY,
        name="Heading",
        icon="mdi:compass",
        native_unit_of_measurement="°",
        exists_fn=lambda description, device: True,
        value_fn=lambda value, device: (
            round(value.heading_deg, 1) if value is not None else None
        ),
    ),
    # edgemaster is s6p2 element[2] on g2408 (confirmed 2026-04-26 by
    # toggle: True → False → True → False with no other change). Was
    # previously thought to be a constant "True" frame validity flag —
    # all earlier captures had EdgeMaster ON. Bool, no further decode.
    DreameMowerSensorEntityDescription(
        key="edgemaster",
        icon="mdi:vector-square",
        value_fn=lambda value, device: (
            ("on" if device.get_property(DreameMowerProperty.FRAME_INFO)[2] else "off")
            if isinstance(device.get_property(DreameMowerProperty.FRAME_INFO), list)
            and len(device.get_property(DreameMowerProperty.FRAME_INFO)) >= 3
            else None
        ),
        exists_fn=lambda description, device: True,
    ),
    # mowing_height is in s6p2 element[0] on g2408 (confirmed 2026-04-26):
    # value is height in millimetres (range 30-70mm = 3.0-7.0cm in 5mm
    # steps). The earlier "profile_id" hypothesis was wrong — it always
    # was the height. Surfaced in cm as a float for app-matching.
    DreameMowerSensorEntityDescription(
        key="mowing_height",
        icon="mdi:ruler",
        native_unit_of_measurement="cm",
        value_fn=lambda value, device: (
            device.get_property(DreameMowerProperty.FRAME_INFO)[0] / 10.0
            if isinstance(device.get_property(DreameMowerProperty.FRAME_INFO), list)
            and len(device.get_property(DreameMowerProperty.FRAME_INFO)) >= 1
            and isinstance(device.get_property(DreameMowerProperty.FRAME_INFO)[0], int)
            else None
        ),
        attrs_fn=lambda device: (
            {"raw_mm": device.get_property(DreameMowerProperty.FRAME_INFO)[0]}
            if isinstance(device.get_property(DreameMowerProperty.FRAME_INFO), list)
            and len(device.get_property(DreameMowerProperty.FRAME_INFO)) >= 1
            else {}
        ),
        exists_fn=lambda description, device: True,
    ),
    # mow_mode is in s6p2 element[1] on g2408 (confirmed 2026-04-26):
    #   s6p2 = [profile_id, mow_mode, True, 2]
    # where mow_mode 0=Standard, 1=Efficient. The apk's PRE[1] mapping
    # is wrong on g2408 — PRE stays [0,0] regardless of efficiency
    # setting; only s6p2[1] tracks it. s6p2 is mapped as
    # DreameMowerProperty.FRAME_INFO and stored in device.data, so
    # we read it directly without an inline cache.
    DreameMowerSensorEntityDescription(
        key="mow_mode",
        icon="mdi:robot-mower",
        value_fn=lambda value, device: (
            {0: "standard", 1: "efficient"}.get(
                device.get_property(DreameMowerProperty.FRAME_INFO)[1]
            )
            if isinstance(device.get_property(DreameMowerProperty.FRAME_INFO), list)
            and len(device.get_property(DreameMowerProperty.FRAME_INFO)) >= 2
            and isinstance(device.get_property(DreameMowerProperty.FRAME_INFO)[1], int)
            else None
        ),
        attrs_fn=lambda device: (
            {
                "frame_profile_id": device.get_property(DreameMowerProperty.FRAME_INFO)[0],
                "frame_raw": list(device.get_property(DreameMowerProperty.FRAME_INFO)),
            }
            if isinstance(device.get_property(DreameMowerProperty.FRAME_INFO), list)
            and len(device.get_property(DreameMowerProperty.FRAME_INFO)) >= 2
            else {}
        ),
        exists_fn=lambda description, device: True,
    ),
    # CFG.LIT is the app's "Lights" setting (confirmed 2026-04-24).
    # Shape [enabled, start_min, end_min, standby, working, charging,
    # error, unknown] matches the s2p51 LED_PERIOD decoder exactly.
    # - LIT[0]: Custom LED Activation Period on/off
    # - LIT[1]: start_min (window start)
    # - LIT[2]: end_min (window end)
    # - LIT[3]: scenario "In Standby"
    # - LIT[4]: scenario "In Working"
    # - LIT[5]: scenario "In Charging"
    # - LIT[6]: scenario "In Error State"
    # - LIT[7]: unknown toggle — user reported a last field in the app
    #   whose purpose isn't clear; watch for changes during toggle tests.
    #
    # Entity keys kept as "headlight_*" for backward-compat with
    # existing dashboards; the app term is "Lights". Consider a
    # future rename cycle once entity aliases are in place.
    DreameMowerSensorEntityDescription(
        key="headlight_enabled",
        icon="mdi:car-light-high",
        value_fn=lambda value, device: (
            "on" if (
                isinstance(device.cfg.get("LIT"), list)
                and len(device.cfg.get("LIT", [])) >= 1
                and device.cfg["LIT"][0]
            ) else "off" if isinstance(device.cfg.get("LIT"), list) else None
        ),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("LIT", min_len=1),
    ),
    DreameMowerSensorEntityDescription(
        key="headlight_schedule",
        icon="mdi:clock-outline",
        value_fn=lambda value, device: _format_time_window(device.cfg.get("LIT")),
        attrs_fn=lambda device: (
            {
                "enabled": bool(device.cfg["LIT"][0]),
                "start_min": int(device.cfg["LIT"][1]),
                "end_min": int(device.cfg["LIT"][2]),
                "scenario_standby": bool(device.cfg["LIT"][3]),
                "scenario_working": bool(device.cfg["LIT"][4]),
                "scenario_charging": bool(device.cfg["LIT"][5]),
                "scenario_error": bool(device.cfg["LIT"][6]),
                "reserved_unknown": int(device.cfg["LIT"][7]),
            }
            if isinstance(device.cfg.get("LIT"), list)
            and len(device.cfg["LIT"]) >= 8
            and all(isinstance(x, int) for x in device.cfg["LIT"][:8])
            else {}
        ),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("LIT", min_len=3),
    ),
    # CFG.STUN is Auto Recharge After Extended Standby (confirmed
    # 2026-04-24 — previously mislabelled as "anti_theft" based on
    # the upstream vacuum codebase's naming; that mapping was wrong
    # on g2408). Mapping {0: off, 1: on}.
    DreameMowerSensorEntityDescription(
        key="auto_recharge_standby",
        icon="mdi:battery-clock",
        value_fn=lambda value, device: (
            "on" if device.cfg.get("STUN") == 1 else
            "off" if device.cfg.get("STUN") == 0 else None
        ),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("STUN"),
    ),
    # CFG.ATA is Anti-Theft Alarm (confirmed 2026-04-24). Shape
    # [lift_alarm, offmap_alarm, realtime_location] — matches the
    # s2p51 ANTI_THEFT decoder exactly. State shows "on" if any sub-
    # flag is enabled, "off" if all are zero. Per-flag state in
    # attributes.
    DreameMowerSensorEntityDescription(
        key="anti_theft",
        icon="mdi:shield-lock",
        value_fn=lambda value, device: (
            ("on" if any(device.cfg["ATA"][:3]) else "off")
            if isinstance(device.cfg.get("ATA"), list)
            and len(device.cfg["ATA"]) >= 3
            and all(isinstance(x, int) for x in device.cfg["ATA"][:3])
            else None
        ),
        attrs_fn=lambda device: (
            {
                "lift_alarm": bool(device.cfg["ATA"][0]),
                "offmap_alarm": bool(device.cfg["ATA"][1]),
                "realtime_location": bool(device.cfg["ATA"][2]),
            }
            if isinstance(device.cfg.get("ATA"), list)
            and len(device.cfg["ATA"]) >= 3
            and all(isinstance(x, int) for x in device.cfg["ATA"][:3])
            else {}
        ),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("ATA"),
    ),
    DreameMowerSensorEntityDescription(
        key="weather_reference",
        icon="mdi:weather-partly-cloudy",
        value_fn=lambda value, device: (
            "on" if device.cfg.get("WRF") else
            "off" if device.cfg.get("WRF") is False else None
        ),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("WRF"),
    ),
    DreameMowerSensorEntityDescription(
        # CFG.PROT is Navigation Path. Confirmed 2026-04-24 via
        # isolated single-toggle with cfg_keys_raw diff visible:
        # nav smart → direct flipped PROT 1 → 0 with no other CFG key
        # moving. Value mapping {0: "direct", 1: "smart"} matches the
        # order shown in the app.
        key="navigation_path",
        icon="mdi:map-marker-path",
        value_fn=lambda value, device: (
            {0: "direct", 1: "smart"}.get(device.cfg.get("PROT"))
            if isinstance(device.cfg.get("PROT"), int)
            else None
        ),
        attrs_fn=lambda device: (
            {"raw_prot": device.cfg.get("PROT")}
            if isinstance(device.cfg.get("PROT"), int) else {}
        ),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("PROT"),
    ),
    # CFG.PATH — known int {0,1} on g2408 but observed stable at 1
    # through the Navigation Path toggle test, so NOT the Navigation
    # Path setting. Semantic TBD. Surfaced as a diagnostic sensor so
    # future toggle tests can spot what flips it.
    DreameMowerSensorEntityDescription(
        key="cfg_path_raw",
        icon="mdi:help-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda value, device: device.cfg.get("PATH"),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("PATH"),
    ),
    # CFG.CLS is Child Lock (confirmed 2026-04-24). Mapping
    # {0: off, 1: on}. There is also a switch.child_lock entity
    # wired to DreameMowerProperty.CHILD_LOCK — on g2408 the
    # authoritative read path is CFG.CLS, so this sensor provides
    # the visible state regardless of whether the switch's s2p
    # backing property is actually emitted on this firmware.
    DreameMowerSensorEntityDescription(
        key="child_lock_cfg",
        icon="mdi:lock",
        value_fn=lambda value, device: (
            "on" if device.cfg.get("CLS") == 1 else
            "off" if device.cfg.get("CLS") == 0 else None
        ),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("CLS"),
    ),
    # CFG.AOP is "Capture Photos of AI-Detected Obstacles" (confirmed
    # 2026-04-24). Mapping {0: off, 1: on}.
    DreameMowerSensorEntityDescription(
        key="ai_obstacle_photos",
        icon="mdi:camera-image",
        value_fn=lambda value, device: (
            "on" if device.cfg.get("AOP") == 1 else
            "off" if device.cfg.get("AOP") == 0 else None
        ),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("AOP"),
    ),
    # CFG.FDP is Frost Protection (confirmed 2026-04-24 via isolated
    # single-toggle with cfg_keys_raw diff visible). Mapping {0: off,
    # 1: on} matches the app's switch.
    DreameMowerSensorEntityDescription(
        key="frost_protection",
        icon="mdi:snowflake",
        value_fn=lambda value, device: (
            {0: "off", 1: "on"}.get(device.cfg.get("FDP"))
            if isinstance(device.cfg.get("FDP"), int)
            else None
        ),
        attrs_fn=lambda device: (
            {"raw_fdp": device.cfg.get("FDP")}
            if isinstance(device.cfg.get("FDP"), int) else {}
        ),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("FDP"),
    ),
    # CFG.REC is Human Presence Detection Alert (confirmed 2026-04-24).
    # 9-element shape matches the s2p51 HUMAN_PRESENCE_ALERT decoder:
    # - REC[0]: main toggle
    # - REC[1]: detection sensitivity {0: low, 1: medium, 2: high}
    # - REC[2]: activation scenario "In Standby"
    # - REC[3]: activation scenario "In Mowing"
    # - REC[4]: activation scenario "Recharge"
    # - REC[5]: activation scenario "In Point Patrol"
    # - REC[6]: voice prompts + in-app notifications
    # - REC[7]: agreement for sending human photos (privacy consent)
    # - REC[8]: push interval in minutes (observed 3 / 10 / 20)
    DreameMowerSensorEntityDescription(
        key="human_presence_alert",
        icon="mdi:motion-sensor",
        value_fn=lambda value, device: (
            ("on" if device.cfg["REC"][0] else "off")
            if isinstance(device.cfg.get("REC"), list)
            and len(device.cfg["REC"]) >= 1
            and isinstance(device.cfg["REC"][0], int)
            else None
        ),
        attrs_fn=lambda device: (
            {
                "enabled": bool(device.cfg["REC"][0]),
                "sensitivity": {0: "low", 1: "medium", 2: "high"}.get(
                    int(device.cfg["REC"][1]), device.cfg["REC"][1]
                ),
                "scenario_standby": bool(device.cfg["REC"][2]),
                "scenario_mowing": bool(device.cfg["REC"][3]),
                "scenario_recharge": bool(device.cfg["REC"][4]),
                "scenario_patrol": bool(device.cfg["REC"][5]),
                "voice_and_notifications": bool(device.cfg["REC"][6]),
                "photo_consent": bool(device.cfg["REC"][7]),
                "push_interval_min": int(device.cfg["REC"][8]),
            }
            if isinstance(device.cfg.get("REC"), list)
            and len(device.cfg["REC"]) >= 9
            and all(isinstance(x, int) for x in device.cfg["REC"][:9])
            else {}
        ),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("REC", min_len=9),
    ),
    # CFG.DND is Do Not Disturb (confirmed 2026-04-24). Shape
    # [enabled, start_min, end_min] with start/end in minutes-from-
    # midnight. Note the element ORDER differs from the s2p51 DND
    # event-payload shape, which uses a dict `{end, start, value}`;
    # here it's a positional list. State shows the time window
    # ("21:00-07:00") when enabled, "off" when disabled. The existing
    # switch.dnd is the on/off control; this sensor surfaces the
    # schedule + full state.
    DreameMowerSensorEntityDescription(
        key="dnd_schedule",
        icon="mdi:sleep",
        value_fn=lambda value, device: (
            _format_time_window(device.cfg["DND"], start_idx=1, end_idx=2)
            if isinstance(device.cfg.get("DND"), list)
            and len(device.cfg["DND"]) >= 3
            and device.cfg["DND"][0] == 1
            else (
                "off"
                if isinstance(device.cfg.get("DND"), list)
                and len(device.cfg["DND"]) >= 1
                and device.cfg["DND"][0] == 0
                else None
            )
        ),
        attrs_fn=lambda device: (
            {
                "enabled": bool(device.cfg["DND"][0]),
                "start_min": int(device.cfg["DND"][1]),
                "end_min": int(device.cfg["DND"][2]),
            }
            if isinstance(device.cfg.get("DND"), list)
            and len(device.cfg["DND"]) >= 3
            and all(isinstance(x, int) for x in device.cfg["DND"][:3])
            else {}
        ),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("DND", min_len=3),
    ),
    # CFG.LOW is Low-Speed Nighttime (confirmed 2026-04-24). Shape
    # [enabled, start_min, end_min] matches the s2p51 LOW_SPEED_NIGHT
    # decoder. State shows the time window ("20:00-08:00") when
    # enabled, or "off" when disabled. Raw fields in attributes.
    DreameMowerSensorEntityDescription(
        key="low_speed_nighttime",
        icon="mdi:speedometer-slow",
        value_fn=lambda value, device: (
            _format_time_window(device.cfg["LOW"], start_idx=1, end_idx=2)
            if isinstance(device.cfg.get("LOW"), list)
            and len(device.cfg["LOW"]) >= 3
            and device.cfg["LOW"][0] == 1
            else (
                "off"
                if isinstance(device.cfg.get("LOW"), list)
                and len(device.cfg["LOW"]) >= 1
                and device.cfg["LOW"][0] == 0
                else None
            )
        ),
        attrs_fn=lambda device: (
            {
                "enabled": bool(device.cfg["LOW"][0]),
                "start_min": int(device.cfg["LOW"][1]),
                "end_min": int(device.cfg["LOW"][2]),
            }
            if isinstance(device.cfg.get("LOW"), list)
            and len(device.cfg["LOW"]) >= 3
            and all(isinstance(x, int) for x in device.cfg["LOW"][:3])
            else {}
        ),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("LOW", min_len=3),
    ),
    # CFG.WRP is Rain Protection — [enabled, resume_hours] (confirmed
    # 2026-04-24). Shape matches the s2p51 RAIN_PROTECTION decoder.
    # Hours: 0 means "Don't Mow After Rain" (no auto-resume); 1..24
    # means resume N hours after rain ends. State shows off/on; the
    # raw values are exposed as attributes.
    #
    # Distinct from binary_sensor.rain_protection_active which tracks
    # whether it's raining right now (s2p2=56).
    DreameMowerSensorEntityDescription(
        key="rain_protection",
        icon="mdi:weather-pouring",
        value_fn=lambda value, device: (
            ("on" if device.cfg.get("WRP")[0] else "off")
            if isinstance(device.cfg.get("WRP"), list)
            and len(device.cfg["WRP"]) >= 1
            and isinstance(device.cfg["WRP"][0], int)
            else None
        ),
        attrs_fn=lambda device: (
            {
                "enabled": bool(device.cfg["WRP"][0]),
                "resume_hours": int(device.cfg["WRP"][1]),
                "auto_resume": int(device.cfg["WRP"][1]) > 0,
            }
            if isinstance(device.cfg.get("WRP"), list)
            and len(device.cfg["WRP"]) >= 2
            and all(isinstance(x, int) for x in device.cfg["WRP"][:2])
            else {}
        ),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("WRP", min_len=2),
    ),
    # Raw CFG dump — disabled-by-default diagnostic. Enable from the
    # device page to see every CFG key + value as entity attributes,
    # useful for toggle-correlation research (which CFG key is Frost
    # Protection / Child Lock / etc.). Sensor state = count of CFG
    # keys so any "CFG refetched" tick is visible in the state
    # history; attributes carry the full dict as (key → value) pairs.
    # CFG.BAT is the Charging config (confirmed 2026-04-24). 6-element
    # shape matches the s2p51 CHARGING decoder:
    # - BAT[0]: recharge_pct (auto-recharge when battery below this)
    # - BAT[1]: resume_pct (resume mowing when battery above this)
    # - BAT[2]: unknown flag (observed =1)
    # - BAT[3]: custom charging period toggle
    # - BAT[4]: custom charging window start_min
    # - BAT[5]: custom charging window end_min
    # State shows the time window when custom charging is enabled
    # ("18:00-08:00"), "off" when disabled. Per-field values in attrs.
    DreameMowerSensorEntityDescription(
        key="charging_config",
        icon="mdi:battery-charging-80",
        value_fn=lambda value, device: (
            _format_time_window(device.cfg["BAT"], start_idx=4, end_idx=5)
            if isinstance(device.cfg.get("BAT"), list)
            and len(device.cfg["BAT"]) >= 6
            and device.cfg["BAT"][3] == 1
            else (
                "off"
                if isinstance(device.cfg.get("BAT"), list)
                and len(device.cfg["BAT"]) >= 4
                and device.cfg["BAT"][3] == 0
                else None
            )
        ),
        attrs_fn=lambda device: (
            {
                "recharge_pct": int(device.cfg["BAT"][0]),
                "resume_pct": int(device.cfg["BAT"][1]),
                "unknown_flag": int(device.cfg["BAT"][2]),
                "custom_charging_enabled": bool(device.cfg["BAT"][3]),
                "start_min": int(device.cfg["BAT"][4]),
                "end_min": int(device.cfg["BAT"][5]),
            }
            if isinstance(device.cfg.get("BAT"), list)
            and len(device.cfg["BAT"]) >= 6
            and all(isinstance(x, int) for x in device.cfg["BAT"][:6])
            else {}
        ),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("BAT", min_len=6),
    ),
    # CFG.LANG is [text_idx, voice_idx] (confirmed 2026-04-24 via live
    # Robot Voice toggle). text_idx drives the app / UI language;
    # voice_idx drives the robot's spoken voice. Observed: voice_idx=7
    # = Norwegian. Matches the s2p51 LANGUAGE event shape
    # `{"text": N, "voice": M}`. The full index → name mapping is
    # firmware-side — we surface the raw ints and a human-readable
    # Norwegian label where known.
    DreameMowerSensorEntityDescription(
        key="robot_voice",
        icon="mdi:account-voice",
        value_fn=lambda value, device: (
            {0: "default", 7: "Norwegian"}.get(
                device.cfg["LANG"][1], f"index_{device.cfg['LANG'][1]}"
            )
            if isinstance(device.cfg.get("LANG"), list)
            and len(device.cfg["LANG"]) >= 2
            and isinstance(device.cfg["LANG"][1], int)
            else None
        ),
        attrs_fn=lambda device: (
            {
                "text_idx": int(device.cfg["LANG"][0]),
                "voice_idx": int(device.cfg["LANG"][1]),
            }
            if isinstance(device.cfg.get("LANG"), list)
            and len(device.cfg["LANG"]) >= 2
            and all(isinstance(x, int) for x in device.cfg["LANG"][:2])
            else {}
        ),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("LANG", min_len=2),
    ),
    # CFG.VOICE is the 4 Voice Prompt Mode toggles (confirmed
    # 2026-04-24). Shape [regular, work_status, special_status,
    # error_status] — all bools. State = enabled-count (0..4);
    # per-mode detail in attributes.
    DreameMowerSensorEntityDescription(
        key="voice_prompt_modes",
        icon="mdi:bullhorn",
        value_fn=lambda value, device: (
            sum(bool(x) for x in device.cfg["VOICE"][:4])
            if isinstance(device.cfg.get("VOICE"), list)
            and len(device.cfg["VOICE"]) >= 4
            and all(isinstance(x, int) for x in device.cfg["VOICE"][:4])
            else None
        ),
        attrs_fn=lambda device: (
            {
                "regular_notification": bool(device.cfg["VOICE"][0]),
                "work_status": bool(device.cfg["VOICE"][1]),
                "special_status": bool(device.cfg["VOICE"][2]),
                "error_status": bool(device.cfg["VOICE"][3]),
            }
            if isinstance(device.cfg.get("VOICE"), list)
            and len(device.cfg["VOICE"]) >= 4
            and all(isinstance(x, int) for x in device.cfg["VOICE"][:4])
            else {}
        ),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("VOICE", min_len=4),
    ),
    # CFG.VOL is Robot Voice volume 0-100 (confirmed 2026-04-24).
    DreameMowerSensorEntityDescription(
        key="robot_voice_volume",
        icon="mdi:volume-high",
        native_unit_of_measurement="%",
        value_fn=lambda value, device: (
            int(device.cfg["VOL"])
            if isinstance(device.cfg.get("VOL"), int)
            else None
        ),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("VOL"),
    ),
    # CFG.VER is a CFG-update revision counter (confirmed 2026-04-24,
    # NOT firmware version as previously documented). Bumps by 1 on
    # every successful CFG write; useful as a tripwire to correlate
    # toggle activity. Exposed as a diagnostic sensor so the change
    # history is visible in HA's state history graph.
    DreameMowerSensorEntityDescription(
        key="cfg_version",
        icon="mdi:counter",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda value, device: (
            int(device.cfg.get("VER"))
            if isinstance(device.cfg.get("VER"), int)
            else None
        ),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("VER"),
    ),
    # Raw OBS dump — same pattern as cfg_keys_raw. Populated by
    # device.refresh_obs() (apk endpoint getOBS = obstacle-avoidance
    # settings: Pathway Obstacle Avoidance, Obstacle Avoidance
    # Distance / Height / On Edges, etc.). State = key count when
    # populated, else the last app-level error message. Disabled-by-
    # default diagnostic.
    DreameMowerSensorEntityDescription(
        key="obs_keys_raw",
        icon="mdi:wall",
        entity_category=EntityCategory.DIAGNOSTIC,
        # Enabled by default — this is research-active territory; the
        # whole point is to surface OBS payload to the user. Diagnostic
        # category keeps it out of the main entity list.
        value_fn=lambda value, device: (
            len(getattr(device, "_obs", None) or {})
            if (getattr(device, "_obs", None) or getattr(device, "_obs_fetched_at", None))
            else (getattr(device, "_obs_last_error", None) or "no_data")
        ),
        attrs_fn=lambda device: {
            **(dict(getattr(device, "_obs", None) or {})),
            "_last_error": getattr(device, "_obs_last_error", None),
            "_fetched_at": getattr(device, "_obs_fetched_at", None),
        },
        exists_fn=lambda description, device: True,
    ),
    # Raw AIOBS dump — apk endpoint getAIOBS = AI obstacle settings
    # (AI Obstacle Recognition: Humans / Animals / Objects, photo
    # consent, etc.). Same state semantics as obs_keys_raw.
    DreameMowerSensorEntityDescription(
        key="aiobs_keys_raw",
        icon="mdi:eye",
        entity_category=EntityCategory.DIAGNOSTIC,
        # Enabled by default — research-active.
        value_fn=lambda value, device: (
            len(getattr(device, "_aiobs", None) or {})
            if (getattr(device, "_aiobs", None) or getattr(device, "_aiobs_fetched_at", None))
            else (getattr(device, "_aiobs_last_error", None) or "no_data")
        ),
        attrs_fn=lambda device: {
            **(dict(getattr(device, "_aiobs", None) or {})),
            "_last_error": getattr(device, "_aiobs_last_error", None),
            "_fetched_at": getattr(device, "_aiobs_fetched_at", None),
        },
        exists_fn=lambda description, device: True,
    ),
    # Raw cloud MAP.* payload dump — exposes all 17 top-level keys
    # the Dreame cloud returns so toggle-correlation research can
    # see which keys flip when settings or zones change. Disabled-by-
    # default diagnostic; expect ~150-300 KB of attribute data when
    # enabled.
    # Designated Ignore Obstacle Zones — read from the cloud MAP.*
    # forbiddenAreas key (confirmed 2026-04-26). Each zone is a
    # 2-element [id, {id, type, shapeType, path, angle}] entry.
    # The `id` here matches the s2p50 entity id from the create
    # event, so this sensor + the s2p50 opcode log together give
    # full lifecycle visibility.
    #
    # State = number of zones currently defined.
    # Attributes:
    #   zones: list of {id, type, shape_type, corner_count, angle_deg,
    #          path: [...]} — full geometry preserved for downstream
    #          consumers (automations, custom cards).
    DreameMowerSensorEntityDescription(
        key="designated_ignore_zones",
        icon="mdi:shape-polygon-plus",
        value_fn=lambda value, device: len(
            (
                getattr(device, "_latest_cloud_map_payload", None)
                or {}
            ).get("forbiddenAreas", {}).get("value", [])
            if isinstance(
                (
                    getattr(device, "_latest_cloud_map_payload", None)
                    or {}
                ).get("forbiddenAreas"),
                dict,
            )
            else []
        ),
        attrs_fn=lambda device: {
            "zones": [
                {
                    "id": (entry[1] if isinstance(entry, list) else entry).get("id"),
                    "type": (entry[1] if isinstance(entry, list) else entry).get("type"),
                    "shape_type": (entry[1] if isinstance(entry, list) else entry).get("shapeType"),
                    "corner_count": len(
                        (entry[1] if isinstance(entry, list) else entry).get("path") or []
                    ),
                    "angle_deg": (entry[1] if isinstance(entry, list) else entry).get("angle"),
                    "path": (entry[1] if isinstance(entry, list) else entry).get("path", []),
                }
                for entry in (
                    (
                        getattr(device, "_latest_cloud_map_payload", None) or {}
                    ).get("forbiddenAreas", {}).get("value", [])
                    if isinstance(
                        (
                            getattr(device, "_latest_cloud_map_payload", None) or {}
                        ).get("forbiddenAreas"),
                        dict,
                    )
                    else []
                )
                if isinstance(entry, (list, dict))
            ],
        },
        exists_fn=lambda description, device: True,
    ),
    DreameMowerSensorEntityDescription(
        key="map_keys_raw",
        icon="mdi:map-search",
        entity_category=EntityCategory.DIAGNOSTIC,
        # Enabled by default — research-active. The raw cloud-map
        # payload can be 50-300 KB; HA's recorder rejects state
        # attributes over 16 KB, so we serialise each key to JSON
        # and truncate at 800 chars. The dashboard markdown card
        # already truncates display at 800 too, so no visual loss.
        value_fn=lambda value, device: len(
            getattr(device, "_latest_cloud_map_payload", None) or {}
        ),
        attrs_fn=lambda device: _truncate_map_attrs_fn(device),
        exists_fn=lambda description, device: True,
    ),
    # One-shot startup probe of every apk-listed routed-action GET
    # endpoint. State = count of endpoints that returned a non-error
    # payload. Attributes carry the per-endpoint result (or _error
    # marker). Lets us see at a glance which apk endpoints g2408
    # supports without wiring each to a dedicated sensor.
    DreameMowerSensorEntityDescription(
        key="routed_endpoints_probe",
        icon="mdi:radar",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda value, device: sum(
            1 for v in (getattr(device, "_routed_endpoint_probe", None) or {}).values()
            if not (isinstance(v, dict) and "_error" in v)
        ),
        attrs_fn=lambda device: dict(
            getattr(device, "_routed_endpoint_probe", None) or {}
        ),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerSensorEntityDescription(
        key="cfg_keys_raw",
        icon="mdi:code-json",
        entity_category=EntityCategory.DIAGNOSTIC,
        # Enabled by default — research-active and feeds the
        # CFG toggle-research dashboard card.
        value_fn=lambda value, device: len(
            getattr(device, "cfg", None) or {}
        ),
        attrs_fn=lambda device: {
            **dict(getattr(device, "cfg", None) or {}),
            "_recent_changes": dict(
                getattr(device, "_cfg_recent_changes", None) or {}
            ),
            "_last_diff": {
                k: {"old": old, "new": new}
                for k, (old, new) in (
                    getattr(device, "_cfg_last_diff", None) or {}
                ).items()
            },
            "_last_diff_at": getattr(device, "_cfg_last_diff_at", None),
        },
        exists_fn=lambda description, device: True,
    ),
    # Routed-action fetch health. State is "ok" / "backoff" / "disabled";
    # attributes expose counters and the pending retry window so toggle-
    # research users can tell at a glance whether CFG fetching is alive.
    # Matters because a silent hard-disable previously blinded all
    # CFG-derived entities with no user-visible signal (see device.py
    # _routed_action_note_failure).
    # MAP fetch health — explicit instrumentation so the user can tell
    # whether the integration's cloud-MAP refetches are succeeding (and
    # returning unchanged md5 = no new data) vs failing silently. The
    # alpha.148 s1p50 → cloud-map-poll wiring relies on this surface
    # being healthy. Enabled by default since silent-failure is the
    # whole bug class this sensor exists to surface.
    DreameMowerSensorEntityDescription(
        key="map_fetch_health",
        icon="mdi:map-clock",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda value, device: (
            "ok"
            if (
                getattr(device, "_map_fetch_attempts", 0) > 0
                and getattr(device, "_map_fetch_last_error", None) is None
            )
            else (
                "error"
                if getattr(device, "_map_fetch_last_error", None)
                else "no_data"
            )
        ),
        attrs_fn=lambda device: {
            "attempts": getattr(device, "_map_fetch_attempts", 0),
            "successes": getattr(device, "_map_fetch_successes", 0),
            "unchanged": getattr(device, "_map_fetch_unchanged", 0),
            "failures": getattr(device, "_map_fetch_failures", 0),
            "last_md5": getattr(device, "_map_fetch_last_md5", None),
            "last_error": getattr(device, "_map_fetch_last_error", None),
            "last_error_ts": getattr(device, "_map_fetch_last_error_ts", None),
            "last_attempt_ts": getattr(device, "_map_fetch_last_attempt_ts", None),
        },
        exists_fn=lambda description, device: True,
    ),
    DreameMowerSensorEntityDescription(
        key="cfg_fetch_health",
        icon="mdi:cloud-sync",
        entity_category=EntityCategory.DIAGNOSTIC,
        # Enabled by default — the whole point of this sensor is to make
        # silent CFG-fetch failures visible; disabled-by-default defeats
        # that. Ships under the Diagnostic category so it doesn't clutter
        # the main device view.
        value_fn=lambda value, device: (
            "disabled" if getattr(device, "_routed_actions_supported", None) is False
            else ("backoff" if getattr(device, "_cfg_consecutive_failures", 0) > 0 else "ok")
        ),
        attrs_fn=lambda device: {
            "routed_actions_supported": getattr(device, "_routed_actions_supported", None),
            "consecutive_failures": getattr(device, "_cfg_consecutive_failures", 0),
            "success_count": getattr(device, "_cfg_success_count", 0),
            "failure_count": getattr(device, "_cfg_failure_count", 0),
            "last_failure_reason": getattr(device, "_cfg_last_failure_reason", None),
            "last_failure_ts": getattr(device, "_cfg_last_failure_ts", None),
            "cfg_fetched_at": getattr(device, "_cfg_fetched_at", None),
            "next_retry_in_s": max(
                0,
                int(getattr(device, "_cfg_next_retry_at", 0.0) - time.time())
            ),
        },
        exists_fn=lambda description, device: True,
    ),
    # --- Wear meters. Apk catalogs CMS=[blade,brush,robot] but g2408
    # returns CMS=[blade,brush,robot,aux]. Confirmed on g2408: all three
    # shipped sensors match the app exactly (57% / 91% / 29%).
    # Max-minute thresholds per apk; aux max-minute guess = 6000
    # (matches blade; revise once schema confirmed).
    DreameMowerSensorEntityDescription(
        key="blade_health_pct",
        icon="mdi:scissors-cutting",
        native_unit_of_measurement="%",
        value_fn=lambda value, device: _wear_health(device.cfg.get("CMS"), 0, 6000),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("CMS", min_len=1),
    ),
    DreameMowerSensorEntityDescription(
        key="brush_health_pct",
        icon="mdi:broom",
        native_unit_of_measurement="%",
        value_fn=lambda value, device: _wear_health(device.cfg.get("CMS"), 1, 30000),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("CMS", min_len=2),
    ),
    DreameMowerSensorEntityDescription(
        key="robot_maintenance_health_pct",
        icon="mdi:wrench",
        native_unit_of_measurement="%",
        value_fn=lambda value, device: _wear_health(device.cfg.get("CMS"), 2, 3600),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("CMS", min_len=3),
    ),
    # 4th CMS slot — semantics TBD. On g2408 alpha.85 it was 0.
    DreameMowerSensorEntityDescription(
        key="aux_wear_health_pct",
        icon="mdi:counter",
        native_unit_of_measurement="%",
        value_fn=lambda value, device: _wear_health(device.cfg.get("CMS"), 3, 6000),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("CMS", min_len=4),
    ),
    # --- Timezone (CFG.TIME str, e.g. "Europe/Oslo")
    DreameMowerSensorEntityDescription(
        key="mower_timezone",
        icon="mdi:map-clock",
        value_fn=lambda value, device: (
            device.cfg.get("TIME") if isinstance(device.cfg.get("TIME"), str) else None
        ),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("TIME"),
    ),
    DreameMowerSensorEntityDescription(
        key="dock_x_cm",
        icon="mdi:home-import-outline",
        native_unit_of_measurement="cm",
        value_fn=lambda value, device: (
            device.dock_pos.get("x") if isinstance(device.dock_pos, dict) else None
        ),
        exists_fn=lambda description, device: True,
        available_fn=_dock_pos_present,
    ),
    DreameMowerSensorEntityDescription(
        key="dock_y_cm",
        icon="mdi:home-import-outline",
        native_unit_of_measurement="cm",
        value_fn=lambda value, device: (
            device.dock_pos.get("y") if isinstance(device.dock_pos, dict) else None
        ),
        exists_fn=lambda description, device: True,
        available_fn=_dock_pos_present,
    ),
    DreameMowerSensorEntityDescription(
        key="dock_yaw_deg",
        icon="mdi:compass",
        native_unit_of_measurement="°",
        # apk says yaw / 10 -> degrees
        value_fn=lambda value, device: (
            (device.dock_pos.get("yaw", 0) / 10.0)
            if isinstance(device.dock_pos, dict) and device.dock_pos.get("yaw") is not None
            else None
        ),
        exists_fn=lambda description, device: True,
        available_fn=_dock_pos_present,
    ),
    DreameMowerSensorEntityDescription(
        key="dock_lawn_connected",
        icon="mdi:link-variant",
        value_fn=lambda value, device: (
            "yes" if isinstance(device.dock_pos, dict) and device.dock_pos.get("connect_status")
            else "no" if isinstance(device.dock_pos, dict)
            else None
        ),
        exists_fn=lambda description, device: True,
        available_fn=_dock_pos_present,
    ),
    # Maintenance Points (cloud MAP.* cleanPoints). Set in the Dreame
    # app; multiple are allowed. `device.maintenance_points` stores raw
    # cloud-frame mm (what `device.go_to` expects); sensor attributes
    # present metres for display consistency with Position X/Y and
    # dock sensors.
    #
    # State = count of points. Attributes carry the full list as
    # (id, x, y) tuples — the authoritative representation. Dashboards
    # render via a markdown card that iterates the list (example in
    # dashboards/mower.yaml). Alpha.93–101 also shipped first-point
    # convenience sensors (`maintenance_point_x`, `_y`) but those
    # only ever mirrored point 1, which turned out misleading on
    # multi-point setups. Removed alpha.113 — pull from the list
    # attribute instead.
    DreameMowerSensorEntityDescription(
        key="maintenance_points_count",
        icon="mdi:map-marker-multiple",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda value, device: len(
            getattr(device, "maintenance_points", []) or []
        ),
        attrs_fn=lambda device: {
            "points": [
                {
                    "id": p.get("id"),
                    "x": round(p.get("x_mm", 0) / 1000.0, 3),
                    "y": round(p.get("y_mm", 0) / 1000.0, 3),
                }
                for p in (getattr(device, "maintenance_points", []) or [])
            ],
        },
        exists_fn=lambda description, device: True,
    ),
    DreameMowerSensorEntityDescription(
        key="voice_download_progress",
        icon="mdi:download",
        native_unit_of_measurement="%",
        value_fn=lambda value, device: device.voice_dl_progress,
        exists_fn=lambda description, device: True,
        available_fn=lambda device: getattr(device, "voice_dl_progress", None) is not None,
    ),
    DreameMowerSensorEntityDescription(
        key="self_check_result",
        icon="mdi:stethoscope",
        # Show 'pass' when result == 0, else the raw result int as str.
        # Full dict is available via device.self_check_result if an
        # attribute-based entity is added later.
        value_fn=lambda value, device: (
            "pass" if isinstance(device.self_check_result, dict)
            and device.self_check_result.get("result") == 0
            else str(device.self_check_result.get("result"))
            if isinstance(device.self_check_result, dict)
            else None
        ),
        exists_fn=lambda description, device: True,
        available_fn=lambda device: isinstance(
            getattr(device, "self_check_result", None), dict
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Dreame Mower sensor based on a config entry."""
    coordinator: DreameMowerDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        DreameMowerSensorEntity(coordinator, description)
        for description in SENSORS
        if description.exists_fn(description, coordinator.device)
    )
    # Standalone diagnostic: archived-sessions counter. Only shows up on
    # devices that actually have an archive (g2408 path).
    if getattr(coordinator, "session_archive", None) is not None:
        async_add_entities([DreameArchivedSessionsSensor(coordinator)])
    # Same thing for LiDAR scans — enabled as soon as the mower has
    # uploaded at least one PCD blob (siid=99 path).
    if getattr(coordinator, "lidar_archive", None) is not None:
        async_add_entities([DreameArchivedLidarScansSensor(coordinator)])


class DreameMowerSensorEntity(DreameMowerEntity, SensorEntity):
    """Defines a Dreame Mower sensor entity."""

    def __init__(
        self,
        coordinator: DreameMowerDataUpdateCoordinator,
        description: DreameMowerSensorEntityDescription,
    ) -> None:
        """Initialize a Dreame Mower sensor entity."""
        if description.value_fn is None and (description.property_key is not None or description.key is not None):
            if description.property_key is not None:
                prop = f"{description.property_key.name.lower()}_name"
            else:
                prop = f"{description.key.lower()}_name"
            if hasattr(coordinator.device.status, prop):
                description.value_fn = lambda value, device: getattr(device.status, prop)

        super().__init__(coordinator, description)
        self._generate_entity_id(ENTITY_ID_FORMAT)


class DreameArchivedSessionsSensor(SensorEntity):
    """Diagnostic sensor: count of archived session summaries.

    State is the integer count. `extra_state_attributes` surfaces the
    latest archived session's metadata plus a list of the N most recent
    entries (trimmed to keep the attrs dict small).
    """

    MAX_LISTED = 20

    def __init__(self, coordinator: DreameMowerDataUpdateCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_has_entity_name = True
        self._attr_name = "Archived Mowing Sessions"
        self._attr_unique_id = f"{coordinator.device.mac}_archived_sessions"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:archive-outline"
        self._attr_native_unit_of_measurement = UNIT_TIMES
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_should_poll = False
        # Cached extra_state_attributes — ONLY ever mutated from the
        # executor-side rebuild path (`_rebuild_attrs_if_changed`).
        # `extra_state_attributes` returns this dict directly without
        # any disk I/O so HA's event-loop detector never trips on us,
        # even at platform-setup time before the first coordinator tick
        # lands (alpha.112 fix — earlier versions built on-demand here
        # which triggered blocking-read warnings on slow disks).
        self._cached_attrs: dict = {}
        # Last (count, in_progress_start_ts) signature we built for.
        # Skip rebuild when the underlying archive hasn't changed.
        self._cached_sig: tuple | None = None

    @property
    def available(self) -> bool:
        return self._coordinator.session_archive is not None

    @property
    def native_value(self) -> int:
        archive = self._coordinator.session_archive
        return archive.count if archive else 0

    def _build_attrs(self) -> dict:
        """Build the attribute dict. Callable from an executor thread;
        does disk I/O via archive.list_sessions / archive.latest."""
        archive = self._coordinator.session_archive
        if not archive:
            return {}
        latest = archive.latest()
        sessions = archive.list_sessions()[: self.MAX_LISTED]
        return {
            "archive_root": str(archive.root),
            "latest": latest.to_dict() if latest else None,
            "recent_sessions": [s.to_dict() for s in sessions],
        }

    @property
    def extra_state_attributes(self) -> dict:
        # NEVER touches disk. Returns whatever the latest executor-side
        # rebuild wrote into `_cached_attrs`. Initial render (before
        # first coordinator tick) returns {} which HA is happy with.
        return self._cached_attrs

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_coordinator_update)
        )
        # Kick a rebuild on the first tick after entity mount so we
        # don't wait for the next coordinator refresh (which can be
        # seconds away on a quiet mower).
        self.hass.async_add_executor_job(self._rebuild_attrs_if_changed)

    def _handle_coordinator_update(self) -> None:
        # Offload the signature check + possible rebuild to the
        # executor. `archive.in_progress_entry` reads in_progress.json
        # from disk (with a 5 s TTL cache that may have expired during
        # HA boot), so doing it inline here used to trip the event-loop
        # blocking detector (alpha.112 fix).
        self.hass.async_add_executor_job(self._rebuild_attrs_if_changed)

    def _rebuild_attrs_if_changed(self) -> None:
        """Executor-side: check archive signature, rebuild + dispatch
        state if it changed. No-op if nothing moved."""
        archive = self._coordinator.session_archive
        if archive is not None:
            in_progress = archive.in_progress_entry()
            new_sig = (
                archive.count,
                in_progress.start_ts if in_progress else None,
            )
        else:
            new_sig = (0, None)
        if new_sig == self._cached_sig:
            return
        self._cached_sig = new_sig
        self._cached_attrs = self._build_attrs()
        # Back to the event loop for the state write.
        self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)


class DreameArchivedLidarScansSensor(SensorEntity):
    """Diagnostic sensor: count of archived LiDAR point-cloud scans."""

    MAX_LISTED = 20

    def __init__(self, coordinator: DreameMowerDataUpdateCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_has_entity_name = True
        self._attr_name = "Archived LiDAR Scans"
        self._attr_unique_id = f"{coordinator.device.mac}_archived_lidar"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:rotate-3d-variant"
        self._attr_native_unit_of_measurement = UNIT_TIMES
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_should_poll = False
        # Same cached-via-executor pattern as DreameArchivedSessionsSensor
        # (alpha.112). Lidar archive's `latest` / `list_scans` don't
        # currently read disk (load_index is idempotent + in-memory after
        # coordinator.async_setup warms it), but keeping the access
        # pattern uniform across the two sensors prevents future
        # refactors from accidentally re-introducing event-loop disk I/O.
        self._cached_attrs: dict = {}
        self._cached_sig: tuple | None = None

    @property
    def available(self) -> bool:
        return self._coordinator.lidar_archive is not None

    @property
    def native_value(self) -> int:
        archive = self._coordinator.lidar_archive
        return archive.count if archive else 0

    @property
    def extra_state_attributes(self) -> dict:
        return self._cached_attrs

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_coordinator_update)
        )
        self.hass.async_add_executor_job(self._rebuild_attrs_if_changed)

    def _handle_coordinator_update(self) -> None:
        self.hass.async_add_executor_job(self._rebuild_attrs_if_changed)

    def _rebuild_attrs_if_changed(self) -> None:
        archive = self._coordinator.lidar_archive
        if archive is None:
            return
        latest = archive.latest()
        new_sig = (archive.count, latest.md5 if latest else None)
        if new_sig == self._cached_sig:
            return
        self._cached_sig = new_sig
        scans = archive.list_scans()[: self.MAX_LISTED]
        self._cached_attrs = {
            "archive_root": str(archive.root),
            "latest": latest.to_dict() if latest else None,
            "recent_scans": [s.to_dict() for s in scans],
        }
        self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)
