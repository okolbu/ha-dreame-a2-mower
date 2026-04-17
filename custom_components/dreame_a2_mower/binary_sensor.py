"""Binary sensor entities for Dreame A2 Mower (g2408)."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DreameMowerDataUpdateCoordinator
from .dreame import DreameMowerProperty
from .entity import DreameMowerEntity, DreameMowerEntityDescription


@dataclass
class DreameMowerBinarySensorEntityDescription(
    DreameMowerEntityDescription, BinarySensorEntityDescription
):
    """Description of a Dreame Mower binary sensor entity."""


BINARY_SENSORS: tuple[DreameMowerBinarySensorEntityDescription, ...] = (
    DreameMowerBinarySensorEntityDescription(
        key="obstacle_detected",
        property_key=DreameMowerProperty.OBSTACLE_FLAG,
        name="Obstacle Detected",
        device_class=BinarySensorDeviceClass.MOTION,
        icon="mdi:alert-octagon",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Dreame Mower binary sensor entities from a config entry."""
    coordinator: DreameMowerDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        DreameMowerBinarySensorEntity(coordinator, description)
        for description in BINARY_SENSORS
    )


class DreameMowerBinarySensorEntity(DreameMowerEntity, BinarySensorEntity):
    """Defines a Dreame Mower binary sensor entity."""

    def __init__(
        self,
        coordinator: DreameMowerDataUpdateCoordinator,
        description: DreameMowerBinarySensorEntityDescription,
    ) -> None:
        """Initialize a Dreame Mower binary sensor entity."""
        super().__init__(coordinator, description)

    @property
    def is_on(self) -> bool | None:
        """Return True when the underlying flag is truthy, None when unseen."""
        value = self.device.get_property(self.entity_description.property_key)
        return bool(value) if value is not None else None
