"""Support for Dreame Mower sensors."""

from __future__ import annotations

import math
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
    y_m = telemetry.y_mm * 0.000625  # same calibration factor as Position Y
    if axis == "north":
        return round(x_m * math.cos(theta) - y_m * math.sin(theta), 2)
    if axis == "east":
        return round(x_m * math.sin(theta) + y_m * math.cos(theta), 2)
    return None

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
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.TANK_FILTER_LEFT,
        icon="mdi:air-filter",
        native_unit_of_measurement=UNIT_PERCENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        # entity_registry_enabled_default=False,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.TANK_FILTER_TIME_LEFT,
        icon="mdi:air-filter",
        native_unit_of_measurement=UNIT_HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        # entity_registry_enabled_default=False,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.SILVER_ION_LEFT,
        icon="mdi:shimmer",
        native_unit_of_measurement=UNIT_PERCENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        # entity_registry_enabled_default=False,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.SILVER_ION_TIME_LEFT,
        icon="mdi:shimmer",
        native_unit_of_measurement=UNIT_DAYS,
        entity_category=EntityCategory.DIAGNOSTIC,
        # entity_registry_enabled_default=False,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.LENSBRUSH_LEFT,
        icon="mdi:brush",
        native_unit_of_measurement=UNIT_PERCENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda description, device: bool(
            DreameMowerEntityDescription().exists_fn(description, device) and device.capability.lensbrush
        )
        # entity_registry_enabled_default=False,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.LENSBRUSH_TIME_LEFT,
        icon="mdi:brush-outline",
        native_unit_of_measurement=UNIT_DAYS,
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda description, device: bool(
            DreameMowerEntityDescription().exists_fn(description, device) and device.capability.lensbrush
        )
        # entity_registry_enabled_default=False,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.SQUEEGEE_LEFT,
        icon="mdi:squeegee",
        native_unit_of_measurement=UNIT_PERCENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        # entity_registry_enabled_default=False,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.SQUEEGEE_TIME_LEFT,
        icon="mdi:squeegee",
        native_unit_of_measurement=UNIT_DAYS,
        entity_category=EntityCategory.DIAGNOSTIC,
        # entity_registry_enabled_default=False,
    ),
    # Legacy `first_cleaning_date` / `total_cleaning_time` /
    # `cleaning_count` / `total_cleaned_area` — vacuum-era names that
    # the g2408-specific mowing_* siblings below supersede. Removed
    # 2026-04-20 (v2.0.0-alpha.27) per user preference: this fork is
    # A2-only, backward-compat with the upstream vacuum integration is
    # a non-goal. The "mowing" variants are defined a few entries
    # above and pull from the same underlying properties via the
    # `*_name` computed attributes on `device.status`.
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
        value_fn=lambda value, device: round(value.y_mm * 0.000625, 2) if value is not None else None,
    ),
    # Raw axis values for diagnostics — preserved alongside the calibrated
    # sensors so future work can re-derive calibration factors from fresh
    # data. X is reported by the firmware in cm, Y in mm.
    #
    # Disabled by default: these flip on every s1p4 push (~5 s during
    # mowing) and otherwise flood the Activity / logbook views with
    # pairs of `X (raw, cm): -742 → -738` lines. Existing installs
    # can disable them manually from the device page if they upgrade;
    # new installs get them off. Users doing calibration work can
    # re-enable either one from the entity's config screen.
    DreameMowerSensorEntityDescription(
        key="mowing_x_raw",
        property_key=DreameMowerProperty.MOWING_TELEMETRY,
        name="X (raw, cm)",
        icon="mdi:help-circle",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        exists_fn=lambda description, device: True,
        value_fn=lambda value, device: value.x_cm if value is not None else None,
    ),
    DreameMowerSensorEntityDescription(
        key="mowing_y_raw",
        property_key=DreameMowerProperty.MOWING_TELEMETRY,
        name="Y (raw, mm)",
        icon="mdi:help-circle",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        exists_fn=lambda description, device: True,
        value_fn=lambda value, device: value.y_mm if value is not None else None,
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

    @property
    def available(self) -> bool:
        return self._coordinator.session_archive is not None

    @property
    def native_value(self) -> int:
        archive = self._coordinator.session_archive
        return archive.count if archive else 0

    @property
    def extra_state_attributes(self) -> dict:
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

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


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

    @property
    def available(self) -> bool:
        return self._coordinator.lidar_archive is not None

    @property
    def native_value(self) -> int:
        archive = self._coordinator.lidar_archive
        return archive.count if archive else 0

    @property
    def extra_state_attributes(self) -> dict:
        archive = self._coordinator.lidar_archive
        if not archive:
            return {}
        latest = archive.latest()
        scans = archive.list_scans()[: self.MAX_LISTED]
        return {
            "archive_root": str(archive.root),
            "latest": latest.to_dict() if latest else None,
            "recent_scans": [s.to_dict() for s in scans],
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
