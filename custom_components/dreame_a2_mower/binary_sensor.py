"""Binary sensor entities for Dreame A2 Mower (g2408)."""

from __future__ import annotations

import time
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


# Seconds after which a "True" reading is auto-cleared if the mower stops
# re-asserting it. Keyed by entity description.key. The mower's s1p53
# obstacle flag latches at True on detection but does not always send a
# matching False when the obstacle clears, so we guard with a timeout.
AUTO_CLEAR_TIMEOUT: dict[str, float] = {
    "obstacle_detected": 30.0,
}


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
    # Mowing session in progress — True whenever there's an active mow task
    # regardless of physical location. Goes True at session start, stays True
    # through pause/resume, through returning to dock for recharge, through
    # charging (while session remains active), and only goes False when the
    # session completes or is cancelled. Lets dashboards show "session
    # ongoing" orthogonally to the lawn_mower entity's physical activity.
    DreameMowerBinarySensorEntityDescription(
        key="mowing_session_active",
        name="Mowing Session Active",
        icon="mdi:robot-mower",
        # Read both the live state (`started`) and a disk-restored
        # in-progress flag (`has_active_in_progress`, mirrored from
        # live_map). After a reboot mid-run the live state can read
        # False for 30+ seconds while waiting for s2p56 confirmation,
        # but the in-progress entry on disk knows we're in a session
        # — so the disk flag fills in the gap. Once s2p56 lands, both
        # signals agree on True.
        value_fn=lambda value, device: bool(
            device.status.started
            or getattr(device, "has_active_in_progress", False)
        ),
        exists_fn=lambda description, device: True,
    ),
    # Battery-temperature-low charging-pause flag. Sourced from the s1p1
    # heartbeat byte[6]&0x08 bit (see docs/research/g2408-protocol.md §4.4).
    # Reports None until the first heartbeat decode so dashboards render
    # "Unknown" instead of "Off" before the mower first reports. The
    # coordinator fires EVENT_WARNING + a persistent notification on the
    # rising edge.
    DreameMowerBinarySensorEntityDescription(
        key="battery_temp_low",
        name="Battery Temperature Low",
        icon="mdi:battery-alert-variant-outline",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda value, device: device.battery_temp_low,
        exists_fn=lambda description, device: True,
    ),
    # Positioning-failed flag — s2p2 = 71. Dreame app shows *"Positioning
    # Failed"*. While this is true every cloud-issued task (Recharge /
    # Start / Dock) fails until the mower re-anchors via SLAM relocate
    # (§4.8). Cleared when any other s2p2 code arrives.
    DreameMowerBinarySensorEntityDescription(
        key="positioning_failed",
        name="Positioning Failed",
        icon="mdi:map-marker-off",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda value, device: device.positioning_failed,
        exists_fn=lambda description, device: True,
    ),
    # Rain-protection flag — s2p2 = 56. Mower's LiDAR doubles as a
    # rain sensor; when water is detected the firmware returns to the
    # dock and asserts this code until rain clears.
    DreameMowerBinarySensorEntityDescription(
        key="rain_protection_active",
        name="Rain Protection Active",
        icon="mdi:weather-pouring",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda value, device: device.rain_protection_active,
        exists_fn=lambda description, device: True,
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
        """Return True when the underlying flag is truthy, None when unseen.

        Supports auto-clear via AUTO_CLEAR_TIMEOUT for entities whose source
        flag latches without an explicit off event (e.g. s1p53 obstacle).
        If the flag has been True but no re-assertion event arrived for
        longer than the configured timeout, report False.
        """
        # If the description provides a value_fn, use it directly — this
        # supports entities whose source is a device method rather than a
        # raw property in device.data.
        if self.entity_description.value_fn is not None:
            raw = self.entity_description.value_fn(None, self.device)
        else:
            value = self.device.get_property(self.entity_description.property_key)
            raw = bool(value) if value is not None else None

        if raw is None or raw is False:
            return raw

        # raw is True — check auto-clear staleness if configured.
        timeout = AUTO_CLEAR_TIMEOUT.get(self.entity_description.key)
        if timeout is None:
            return True

        prop_key = self.entity_description.property_key
        if prop_key is None:
            return True

        last_seen = getattr(
            self.device, "_property_last_seen_at", {}
        ).get(int(prop_key.value))
        if last_seen is None:
            return True

        if (time.monotonic() - last_seen) > timeout:
            return False
        return True
