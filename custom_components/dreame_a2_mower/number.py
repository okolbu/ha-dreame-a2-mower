"""Support for Dreame Mower numbers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.number import (
    ENTITY_ID_FORMAT,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, UNIT_PERCENT

from .coordinator import DreameMowerDataUpdateCoordinator
from .entity import DreameMowerEntity, DreameMowerEntityDescription
from .dreame import DreameMowerAction, DreameMowerProperty

@dataclass
class DreameMowerNumberEntityDescription(DreameMowerEntityDescription, NumberEntityDescription):
    """Describes Dreame Mower Number entity."""

    mode: NumberMode = NumberMode.AUTO
    post_action: DreameMowerAction = None
    set_fn: Callable[[object, int]] = None
    max_value_fn: Callable[[object], int] = None
    min_value_fn: Callable[[object], int] = None


NUMBERS: tuple[DreameMowerNumberEntityDescription, ...] = (
    DreameMowerNumberEntityDescription(
        property_key=DreameMowerProperty.VOLUME,
        icon_fn=lambda value, device: "mdi:volume-off" if value == 0 else "mdi:volume-high",
        mode=NumberMode.SLIDER,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=UNIT_PERCENT,
        entity_category=EntityCategory.CONFIG,
        post_action=DreameMowerAction.TEST_SOUND,
    ),
    DreameMowerNumberEntityDescription(
        key="set_cutting_height",
        icon="mdi:scissors-cutting",
        mode=NumberMode.SLIDER,
        native_min_value=30,
        native_max_value=70,
        native_step=5,
        native_unit_of_measurement="mm",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda value, device: (
            device.cfg.get("PRE", [None] * 10)[2]
            if isinstance(device.cfg.get("PRE"), list)
            and len(device.cfg.get("PRE", [])) >= 10
            else None
        ),
        set_fn=lambda device, value: device.write_pre(2, int(value)),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerNumberEntityDescription(
        key="set_obstacle_distance",
        icon="mdi:ruler",
        mode=NumberMode.SLIDER,
        native_min_value=10,
        native_max_value=20,
        native_step=5,
        native_unit_of_measurement="cm",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda value, device: (
            device.cfg.get("PRE", [None] * 10)[3]
            if isinstance(device.cfg.get("PRE"), list)
            and len(device.cfg.get("PRE", [])) >= 10
            else None
        ),
        set_fn=lambda device, value: device.write_pre(3, int(value)),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerNumberEntityDescription(
        key="set_mow_coverage",
        icon="mdi:percent",
        mode=NumberMode.SLIDER,
        native_min_value=50,
        native_max_value=100,
        native_step=10,
        native_unit_of_measurement="%",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda value, device: (
            device.cfg.get("PRE", [None] * 10)[4]
            if isinstance(device.cfg.get("PRE"), list)
            and len(device.cfg.get("PRE", [])) >= 10
            else None
        ),
        set_fn=lambda device, value: device.write_pre(4, int(value)),
        exists_fn=lambda description, device: True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Dreame Mower number based on a config entry."""
    coordinator: DreameMowerDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        DreameMowerNumberEntity(coordinator, description)
        for description in NUMBERS
        if description.exists_fn(description, coordinator.device)
    )
    async_add_entities([DreameMowerStationBearingNumber(hass, entry, coordinator)])


class DreameMowerNumberEntity(DreameMowerEntity, NumberEntity):
    """Defines a Dreame Mower number."""

    def __init__(
        self,
        coordinator: DreameMowerDataUpdateCoordinator,
        description: DreameMowerNumberEntityDescription,
    ) -> None:
        """Initialize Dreame Mower number."""
        if description.set_fn is None and (description.property_key is not None or description.key is not None):
            if description.property_key is not None:
                prop = f"set_{description.property_key.name.lower()}"
            else:
                prop = f"set_{description.key.lower()}"
            if hasattr(coordinator.device, prop):
                description.set_fn = lambda device, value: getattr(device, prop)(value)

        if description.min_value_fn:
            description.native_min_value = description.min_value_fn(coordinator.device)
        if description.max_value_fn:
            description.native_max_value = description.max_value_fn(coordinator.device)

        super().__init__(coordinator, description)
        self._generate_entity_id(ENTITY_ID_FORMAT)
        self._attr_mode = description.mode
        self._attr_native_value = super().native_value

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_native_value = super().native_value
        if self.entity_description.min_value_fn:
            self.entity_description.native_min_value = self.entity_description.min_value_fn(self.device)
        if self.entity_description.max_value_fn:
            self.entity_description.native_max_value = self.entity_description.max_value_fn(self.device)
        super()._handle_coordinator_update()

    async def async_set_native_value(self, value: float) -> None:
        """Set the Dreame Mower number value."""
        if not self.available:
            raise HomeAssistantError("Entity unavailable")

        value = int(value)
        if self.entity_description.format_fn is not None:
            value = self.entity_description.format_fn(value, self.device)

        if value is None:
            raise HomeAssistantError("Invalid value")

        result = False

        if self.entity_description.set_fn is not None:
            result = await self._try_command("Unable to call: %s", self.entity_description.set_fn, self.device, value)
        elif self.entity_description.property_key is not None:
            result = await self._try_command(
                "Unable to call: %s",
                self.device.set_property,
                self.entity_description.property_key,
                value,
            )

        if result and self.entity_description.post_action is not None:
            await self._try_command(
                "Unable to call %s",
                self.device.call_action,
                self.entity_description.post_action,
            )

    @property
    def native_value(self) -> int | None:
        """Return the current Dreame Mower number value."""
        return self._attr_native_value


class DreameMowerStationBearingNumber(NumberEntity):
    """Station Direction bearing, editable from the device config card.

    This is an HA-only setting (never flows to the mower — the mower
    doesn't know its physical compass bearing). We store it on the
    config entry's options so it survives restarts; the
    `options_updated` listener in __init__.py picks it up and pushes
    onto `device.station_bearing_deg`, where the Position North/East
    sensors read it.
    """

    _attr_has_entity_name = True
    _attr_name = "Station Direction"
    _attr_icon = "mdi:compass-outline"
    _attr_native_min_value = 0
    _attr_native_max_value = 360
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "°"
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: DreameMowerDataUpdateCoordinator,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.device.mac}_station_bearing"

    @property
    def device_info(self):
        # Link to the same HA device as the rest of the entities.
        from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
        return {
            "connections": {(CONNECTION_NETWORK_MAC, self._coordinator.device.mac)},
            "identifiers": {(DOMAIN, self._coordinator.device.mac)},
            "name": self._coordinator.device.name,
        }

    @property
    def native_value(self) -> float:
        from .const import CONF_STATION_BEARING
        return float(self._entry.options.get(CONF_STATION_BEARING, 0.0) or 0.0)

    async def async_set_native_value(self, value: float) -> None:
        from .const import CONF_STATION_BEARING
        # Clamp and wrap to [0, 360)
        v = float(value) % 360.0
        new_options = {**self._entry.options, CONF_STATION_BEARING: v}
        self._hass.config_entries.async_update_entry(self._entry, options=new_options)
        # `options_updated` listener will push the value onto
        # device.station_bearing_deg; write our own state too so the
        # UI reflects immediately.
        self._coordinator.device.station_bearing_deg = v
        self.async_write_ha_state()
