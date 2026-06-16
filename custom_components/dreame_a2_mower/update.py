"""Update platform — device firmware OTA.

Mirrors the Dreame app's firmware-update view. Availability + latest version come
from the cloud iotuserbind/checkDeviceVersion poll (6 h, via _refresh_dev); live
progress from s1p2/s1p3 MQTT pushes. install() fires manualFirmwareUpdate; the
device gates acceptance on WiFi/charge, so a refusal surfaces as HomeAssistantError.

NOT the HACS integration-version update (that tracks this repo). This tracks the
mower's own firmware (e.g. 4.3.6_0550 -> 4.3.6_0625).
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._devices import mower_device_info, mower_unique_id
from .const import DOMAIN, LOGGER
from .coordinator import DreameA2MowerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the firmware update entity."""
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DreameA2FirmwareUpdateEntity(coordinator)])


class DreameA2FirmwareUpdateEntity(
    CoordinatorEntity[DreameA2MowerCoordinator], UpdateEntity
):
    """Mower firmware OTA, driven by checkDeviceVersion + s1p2/s1p3."""

    _attr_has_entity_name = True
    _attr_translation_key = "firmware"
    _attr_title = "Mower firmware"
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.PROGRESS
        | UpdateEntityFeature.RELEASE_NOTES
    )

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "firmware")
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def installed_version(self) -> str | None:
        return getattr(self.coordinator.data, "firmware_version", None)

    @property
    def latest_version(self) -> str | None:
        latest = getattr(self.coordinator.data, "firmware_latest", None)
        available = getattr(self.coordinator.data, "firmware_update_available", None)
        if available and isinstance(latest, str) and latest:
            return latest
        # Not available / unknown -> report installed so HA shows "up to date".
        return self.installed_version

    @property
    def in_progress(self) -> bool:
        return getattr(self.coordinator.data, "ota_state", None) == 2

    @property
    def update_percentage(self) -> int | None:
        pct = getattr(self.coordinator.data, "ota_progress", None)
        if isinstance(pct, int):
            return pct
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is not None and getattr(cs, "ota_status", None):
            return cs.ota_status[1]
        return None

    async def async_release_notes(self) -> str | None:
        return getattr(self.coordinator.data, "firmware_release_notes", None)

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        LOGGER.info("update.firmware: install requested")
        accepted = await self.coordinator.async_trigger_firmware_update()
        if not accepted:
            raise HomeAssistantError(
                "Mower refused the firmware update -- it gates OTA on WiFi signal "
                "and charge. Move it closer to the AP / dock it and retry."
            )
