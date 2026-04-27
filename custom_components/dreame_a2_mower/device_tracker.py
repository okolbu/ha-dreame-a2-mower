"""Device tracker for Dreame A2 Mower (g2408).

Surfaces the mower's onboard RTK GNSS as a HA `device_tracker` so the
built-in Map card / theft-tracking automations can consume the lat/lon
directly. The position is fetched periodically by the coordinator via
the routed `getCFG t:'LOCN'` endpoint (see `device.refresh_locn()`).

Per the iobroker cross-reference, `LOCN` returns `{lon, lat}` in WGS84.
The user-facing "Real-Time Location" anti-theft toggle (CFG.ATA[2])
gates whether the firmware will respond — when it's off the endpoint
returns a Dreame app-level error and the tracker stays at its last
known position with `latitude/longitude=None`.
"""

from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DreameMowerDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DreameMowerDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DreameMowerGpsTracker(coordinator)])


class DreameMowerGpsTracker(
    CoordinatorEntity[DreameMowerDataUpdateCoordinator], TrackerEntity
):
    _attr_has_entity_name = True
    _attr_name = "GPS"
    _attr_icon = "mdi:crosshairs-gps"

    def __init__(self, coordinator: DreameMowerDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.mac}_gps"

    @property
    def device_info(self) -> DeviceInfo:
        dev = self.coordinator.device
        info = getattr(dev, "info", None)
        return DeviceInfo(
            connections={(CONNECTION_NETWORK_MAC, dev.mac)},
            identifiers={(DOMAIN, dev.mac)},
            name=dev.name,
            manufacturer=getattr(info, "manufacturer", None) if info else None,
            model=getattr(info, "model", None) if info else None,
            sw_version=getattr(info, "firmware_version", None) if info else None,
            hw_version=getattr(info, "hardware_version", None) if info else None,
        )

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        return self.coordinator.device.gps_latitude

    @property
    def longitude(self) -> float | None:
        return self.coordinator.device.gps_longitude

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.coordinator.device.gps_latitude is not None
        )

    @property
    def extra_state_attributes(self) -> dict:
        dev = self.coordinator.device
        return {
            "raw": dict(getattr(dev, "_locn", None) or {}),
            "fetched_at": getattr(dev, "_locn_fetched_at", None),
            "last_error": getattr(dev, "_locn_last_error", None),
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
