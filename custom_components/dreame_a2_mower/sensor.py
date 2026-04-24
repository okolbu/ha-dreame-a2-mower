"""Support for Dreame Mower sensors."""

from __future__ import annotations

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
    # PRE-backed mow_mode — g2408 PRE = [zone_id, mode] (2 elements,
    # not the 10-element apk schema). PRE[1] is the mode index.
    # Removed in alpha.86: cutting_height_mm / obstacle_distance_mm /
    # mow_coverage_pct / direction_change / edge_mowing / edge_detection
    # — those apk indexes (2-9) don't exist on g2408's PRE. They may
    # be reachable via a different CFG key or Bluetooth-only path.
    DreameMowerSensorEntityDescription(
        key="mow_mode",
        icon="mdi:robot-mower",
        value_fn=lambda value, device: (
            {0: "standard", 1: "efficient"}.get(
                device.cfg.get("PRE", [None, None])[1]
            )
            if isinstance(device.cfg.get("PRE"), list)
            and len(device.cfg.get("PRE", [])) >= 2
            else None
        ),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("PRE", min_len=2),
    ),
    # --- Headlight (LIT = [enabled, start_min, end_min, ...])
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
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("LIT", min_len=3),
    ),
    # --- Anti-theft + other single-scalar CFG flags
    DreameMowerSensorEntityDescription(
        key="anti_theft",
        icon="mdi:shield-lock",
        value_fn=lambda value, device: (
            "on" if device.cfg.get("STUN") == 1 else
            "off" if device.cfg.get("STUN") == 0 else None
        ),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("STUN"),
    ),
    DreameMowerSensorEntityDescription(
        key="auto_task_adjust",
        icon="mdi:tune",
        # ATA schema unknown — surface raw repr until decoded.
        value_fn=lambda value, device: (
            str(device.cfg.get("ATA")) if device.cfg.get("ATA") is not None else None
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
        # **Tentative** Navigation Path label. Two toggle-test
        # correlations (2026-04-25) showed CFG.PROT flipping when the
        # user toggled Navigation Path in the app, while CFG.PATH
        # stayed stable. But the field name "PROT" is suspiciously
        # cryptic for such a user-visible setting, so this mapping
        # warrants repeat toggle-tests before being treated as
        # authoritative. Previous alpha.89 "PROT = Frost Protection"
        # guess already proved wrong via the same methodology; a
        # similar surprise here is still possible. Diagnostic:
        # `sensor.cfg_keys_raw` (alpha.116+) dumps the full CFG so
        # any mislabelling is one attribute-compare away from visible.
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
    # through a Navigation Path toggle test, so NOT the Navigation Path
    # setting. Semantic TBD. Surfaced as a diagnostic-only sensor with
    # the raw int so future toggle tests can spot what flips it. The
    # earlier "sensor.frost_protection" entity is removed — it was
    # misnamed (PROT turned out to be Navigation Path). Actual Frost
    # Protection's CFG key is still unknown.
    DreameMowerSensorEntityDescription(
        key="cfg_path_raw",
        icon="mdi:help-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda value, device: device.cfg.get("PATH"),
        exists_fn=lambda description, device: True,
        available_fn=_cfg_key_present("PATH"),
    ),
    # Raw CFG dump — disabled-by-default diagnostic. Enable from the
    # device page to see every CFG key + value as entity attributes,
    # useful for toggle-correlation research (which CFG key is Frost
    # Protection / Child Lock / etc.). Sensor state = count of CFG
    # keys so any "CFG refetched" tick is visible in the state
    # history; attributes carry the full dict as (key → value) pairs.
    DreameMowerSensorEntityDescription(
        key="cfg_keys_raw",
        icon="mdi:code-json",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
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
            "attempt_count": getattr(device, "_cfg_attempt_count", 0),
            "short_circuit_counts": dict(
                getattr(device, "_cfg_short_circuit_counts", None) or {}
            ),
            "last_attempt_ts": getattr(device, "_cfg_last_attempt_ts", None),
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
