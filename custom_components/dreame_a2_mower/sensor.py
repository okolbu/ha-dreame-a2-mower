"""Support for Dreame Mower sensors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.ERROR,
        icon_fn=lambda value, device: (
            "mdi:alert-circle-outline"
            if device.status.has_error
            else "mdi:alert-outline" if device.status.has_warning else "mdi:check-circle-outline"
        ),
        attrs_fn=lambda device: {
            ATTR_VALUE: device.status.error,
            "faults": device.status.faults,
            "description": device.status.error_description[0],
        },
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.CHARGING_STATUS,
        icon="mdi:home-lightning-bolt",
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
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.FIRST_CLEANING_DATE,
        icon="mdi:calendar-start",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda value, device: datetime.fromtimestamp(value).replace(
            tzinfo=datetime.now().astimezone().tzinfo
        ),
        # entity_registry_enabled_default=False,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.TOTAL_CLEANING_TIME,
        icon="mdi:timer-outline",
        native_unit_of_measurement=UNIT_MINUTES,
        device_class=SensorDeviceClass.DURATION,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.CLEANING_COUNT,
        icon="mdi:counter",
        native_unit_of_measurement=UNIT_TIMES,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    DreameMowerSensorEntityDescription(
        property_key=DreameMowerProperty.TOTAL_CLEANED_AREA,
        icon="mdi:set-square",
        native_unit_of_measurement=UNIT_AREA,
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
        value_fn=lambda value, device: round(value.y_mm * 0.000625, 2) if value is not None else None,
    ),
    # Raw axis values for diagnostics — preserved alongside the calibrated
    # sensors so future work can re-derive calibration factors from fresh
    # data. X is reported by the firmware in cm, Y in mm.
    DreameMowerSensorEntityDescription(
        key="mowing_x_raw",
        property_key=DreameMowerProperty.MOWING_TELEMETRY,
        name="X (raw, cm)",
        icon="mdi:help-circle",
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda description, device: True,
        value_fn=lambda value, device: value.x_cm if value is not None else None,
    ),
    DreameMowerSensorEntityDescription(
        key="mowing_y_raw",
        property_key=DreameMowerProperty.MOWING_TELEMETRY,
        name="Y (raw, mm)",
        icon="mdi:help-circle",
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda description, device: True,
        value_fn=lambda value, device: value.y_mm if value is not None else None,
    ),
    # Exposed as "Mowing Zone" because byte [8] of s1p4 is the internal
    # zone-ID the mower firmware is currently mowing in — each distinct
    # value corresponds to a distinct non-overlapping X/Y region on the
    # lawn. The entity key stays `mowing_phase` so existing automations
    # keep working. Enum labels (`mowing`, `transit`, etc.) are historical
    # placeholders; see docs/research/g2408-protocol.md.
    DreameMowerSensorEntityDescription(
        key="mowing_phase",
        property_key=DreameMowerProperty.MOWING_TELEMETRY,
        name="Mowing Zone",
        icon="mdi:vector-square",
        exists_fn=lambda description, device: True,
        value_fn=lambda value, device: value.phase_raw if value is not None else None,
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
