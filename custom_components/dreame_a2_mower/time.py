"""Time platform — schedule slot entities for the Dreame A2 Mower.

F4.6.4 / Phase A1: Six TimeEntity instances backed by MowerState's
integer-minute fields. Writable entities write via coordinator.write_setting
using RMW builders from protocol.cfg_payloads.

  - time.dnd_start_time / dnd_end_time         (CFG.DND)
  - time.low_speed_at_night_start_time / _end  (CFG.LOW)
  - time.charging_start_time / _end_time       (CFG.BAT)

LIT start/end time entities do NOT exist here (no MowerState fields for
LIT start_min / end_min — those are controlled via the switch platform).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import time
from typing import Any

from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._devices import mower_device_info, mower_unique_id
from .const import DOMAIN, LOGGER
from .control_honesty import _ControlHonestyMixin, resolve_control_mode
from .coordinator import DreameA2MowerCoordinator
from .mower.state import MowerState
from .protocol import cfg_payloads as _cfgp

# ---------------------------------------------------------------------------
# Descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class DreameA2TimeEntityDescription(TimeEntityDescription):
    """Time entity descriptor with a typed minutes_fn and optional write helpers.

    ``minutes_fn``       — extracts the int-minutes field from MowerState.
    ``cfg_key``          — if set, the entity is writable via
                           coordinator.write_setting(cfg_key, full_value).
                           If None, the entity is read-only.
    ``build_from_cfg_fn``— RMW builder: takes (raw_cfg_list, minutes_int)
                           and returns the wire dict (or None to abort).
    ``field_updates_fn`` — optional optimistic MowerState updates applied
                           by write_setting; omit if the field isn't stored
                           in MowerState.
    """

    minutes_fn: Callable[[MowerState], int | None]
    cfg_key: str | None = None
    build_from_cfg_fn: Callable[[Any, int], Any] | None = None
    field_updates_fn: Callable[[MowerState, int], dict[str, Any]] | None = None


# ---------------------------------------------------------------------------
# Helper: convert minutes-since-midnight to datetime.time
# ---------------------------------------------------------------------------


def _to_time(minutes: int | None) -> time | None:
    """Convert integer minutes-since-midnight to datetime.time object.

    Args:
        minutes: 0..1439 (0 = 00:00, 1439 = 23:59). None is returned as None.

    Returns:
        A datetime.time object, or None if minutes is None or out of range.
    """
    if minutes is None or not (0 <= minutes <= 1439):
        return None
    return time(hour=minutes // 60, minute=minutes % 60)


# ---------------------------------------------------------------------------
# Entity descriptors
# ---------------------------------------------------------------------------


TIMES: tuple[DreameA2TimeEntityDescription, ...] = (
    DreameA2TimeEntityDescription(
        key="dnd_start_time",
        name="DND start time",
        entity_category=EntityCategory.CONFIG,
        minutes_fn=lambda s: s.dnd_start_min,
        cfg_key="DND",
        build_from_cfg_fn=lambda raw, m: _cfgp.build_dnd(raw, start=m),
        field_updates_fn=lambda s, m: {"dnd_start_min": m},
    ),
    DreameA2TimeEntityDescription(
        key="dnd_end_time",
        name="DND end time",
        entity_category=EntityCategory.CONFIG,
        minutes_fn=lambda s: s.dnd_end_min,
        cfg_key="DND",
        build_from_cfg_fn=lambda raw, m: _cfgp.build_dnd(raw, end=m),
        field_updates_fn=lambda s, m: {"dnd_end_min": m},
    ),
    DreameA2TimeEntityDescription(
        key="low_speed_at_night_start_time",
        name="Low speed at night start time",
        entity_category=EntityCategory.CONFIG,
        minutes_fn=lambda s: s.low_speed_at_night_start_min,
        cfg_key="LOW",
        build_from_cfg_fn=lambda raw, m: _cfgp.build_low(raw, start=m),
        field_updates_fn=lambda s, m: {"low_speed_at_night_start_min": m},
    ),
    DreameA2TimeEntityDescription(
        key="low_speed_at_night_end_time",
        name="Low speed at night end time",
        entity_category=EntityCategory.CONFIG,
        minutes_fn=lambda s: s.low_speed_at_night_end_min,
        cfg_key="LOW",
        build_from_cfg_fn=lambda raw, m: _cfgp.build_low(raw, end=m),
        field_updates_fn=lambda s, m: {"low_speed_at_night_end_min": m},
    ),
    DreameA2TimeEntityDescription(
        key="charging_start_time",
        name="Charging start time",
        entity_category=EntityCategory.CONFIG,
        minutes_fn=lambda s: s.charging_start_min,
        cfg_key="BAT",
        build_from_cfg_fn=lambda raw, m: _cfgp.build_bat_charging(raw, start=m),
        field_updates_fn=lambda s, m: {"charging_start_min": m},
    ),
    DreameA2TimeEntityDescription(
        key="charging_end_time",
        name="Charging end time",
        entity_category=EntityCategory.CONFIG,
        minutes_fn=lambda s: s.charging_end_min,
        cfg_key="BAT",
        build_from_cfg_fn=lambda raw, m: _cfgp.build_bat_charging(raw, end=m),
        field_updates_fn=lambda s, m: {"charging_end_min": m},
    ),
)


# ---------------------------------------------------------------------------
# Entity class
# ---------------------------------------------------------------------------


class DreameA2Time(_ControlHonestyMixin, CoordinatorEntity[DreameA2MowerCoordinator], TimeEntity):
    """Read-only time entity backed by MowerState int-minutes field.

    Backs DND / charging / low-speed-at-night CFG time fields (NOT the mow
    schedule). Writable entities write via coordinator.write_setting; the
    rest reject writes via the control-honesty mixin.
    """

    _attr_has_entity_name = True
    entity_description: DreameA2TimeEntityDescription

    def __init__(
        self,
        coordinator: DreameA2MowerCoordinator,
        description: DreameA2TimeEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = mower_unique_id(coordinator, description.key)
        self._attr_device_info = mower_device_info(coordinator)
        self._control_mode = resolve_control_mode(platform="time", key=description.key)

    @property
    def native_value(self) -> time | None:
        """Return the current time value (HH:MM) or None."""
        minutes = self.entity_description.minutes_fn(self.coordinator.data)
        return _to_time(minutes)

    async def async_set_value(self, value: time) -> None:
        """Write the new time to the mower via the coordinator."""
        if self.read_only:
            return await self._reject_readonly_write()
        desc = self.entity_description
        if desc.cfg_key is None or desc.build_from_cfg_fn is None:
            LOGGER.warning(
                "time.%s: no write path configured; ignoring set_value(%r)",
                desc.key,
                value,
            )
            return

        # Convert datetime.time → minutes-since-midnight for the builder.
        m = value.hour * 60 + value.minute

        # RMW path: build wire value from raw cfg base (preserves undecoded slots).
        cs = getattr(self.coordinator, "cloud_state", None)
        raw = cs.cfg.get(desc.cfg_key) if cs is not None else None
        wire_value = desc.build_from_cfg_fn(raw, m)
        if wire_value is None:
            LOGGER.warning(
                "time.%s: no cfg base for %s; write aborted",
                getattr(self, "entity_id", desc.key), desc.cfg_key,
            )
            self.async_write_ha_state()  # snap back
            return

        # Collect optimistic field updates (optional).
        field_updates: dict[str, Any] | None = None
        if desc.field_updates_fn is not None:
            field_updates = desc.field_updates_fn(self.coordinator.data, m)

        success = await self.coordinator.write_setting(
            desc.cfg_key,
            wire_value,
            field_updates=field_updates,
        )
        if not success:
            LOGGER.warning(
                "time.%s: write_setting(%r, %r) returned False",
                desc.key,
                desc.cfg_key,
                wire_value,
            )


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up time entities from the config entry."""
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DreameA2Time(coordinator, desc) for desc in TIMES])
