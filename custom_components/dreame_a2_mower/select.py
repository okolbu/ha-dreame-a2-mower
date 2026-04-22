"""Support for Dreame Mower selects."""

from __future__ import annotations

from enum import IntEnum
import voluptuous as vol
from typing import Any
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.select import (
    ENTITY_ID_FORMAT,
    SelectEntity,
    SelectEntityDescription,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform

from .const import (
    DOMAIN,
    INPUT_CYCLE,
    SERVICE_SELECT_NEXT,
    SERVICE_SELECT_PREVIOUS,
    SERVICE_SELECT_FIRST,
    SERVICE_SELECT_LAST,
)

from .coordinator import DreameMowerDataUpdateCoordinator
from .entity import (
    DreameMowerEntity,
    DreameMowerEntityDescription,
)

from .dreame.const import ATTR_VALUE
from .dreame.types import ATTR_MAP_INDEX, ATTR_MAP_ID
from .dreame import (
    DreameMowerProperty,
    DreameMowerAutoSwitchProperty,
    DreameMowerCleaningMode,
    DreameMowerCleaningRoute,
    DreameMowerCleanGenius,
)

CLEANING_MODE_TO_ICON = {
    DreameMowerCleaningMode.MOWING: "mdi:broom",
}

CLEANING_ROUTE_TO_ICON = {
    DreameMowerCleaningRoute.STANDARD: "mdi:sine-wave",
    DreameMowerCleaningRoute.INTENSIVE: "mdi:swap-vertical-variant",
    DreameMowerCleaningRoute.DEEP: "mdi:heating-coil",
    DreameMowerCleaningRoute.QUICK: "mdi:truck-fast-outline",
}


@dataclass
class DreameMowerSelectEntityDescription(DreameMowerEntityDescription, SelectEntityDescription):
    """Describes Dreame Mower Select entity."""

    set_fn: Callable[[object, int, int]] = None
    options: Callable[[object, object], list[str]] = None


SELECTS: tuple[DreameMowerSelectEntityDescription, ...] = (
    DreameMowerSelectEntityDescription(
        property_key=DreameMowerProperty.CLEANING_MODE,
        icon_fn=lambda value, device: CLEANING_MODE_TO_ICON.get(device.status.cleaning_mode, "mdi:broom"),
        value_int_fn=lambda value, device: DreameMowerCleaningMode[value.upper()].value,
    ),
    DreameMowerSelectEntityDescription(
        property_key=DreameMowerProperty.VOICE_ASSISTANT_LANGUAGE,
        icon="mdi:translate-variant",
        entity_category=EntityCategory.CONFIG,
        exists_fn=lambda description, device: device.capability.voice_assistant,
    ),
    DreameMowerSelectEntityDescription(
        property_key=DreameMowerAutoSwitchProperty.CLEANING_ROUTE,
        entity_category=None,
        icon_fn=lambda value, device: CLEANING_ROUTE_TO_ICON.get(device.status.cleaning_route, "mdi:routes"),
        value_int_fn=lambda value, device: DreameMowerCleaningRoute[value.upper()].value,
        exists_fn=lambda description, device: bool(
            device.capability.cleaning_route and DreameMowerEntityDescription().exists_fn(description, device)
        ),
    ),
    DreameMowerSelectEntityDescription(
        property_key=DreameMowerAutoSwitchProperty.CLEANGENIUS,
        icon="mdi:atom",
        entity_category=None,
        value_int_fn=lambda value, device: DreameMowerCleanGenius[value.upper()].value,
        exists_fn=lambda description, device: bool(
            device.capability.cleangenius and DreameMowerEntityDescription().exists_fn(description, device)
        ),
    ),
    DreameMowerSelectEntityDescription(
        key="selected_map",
        icon="mdi:map-check",
        options=lambda device, segment: [v.map_name for k, v in device.status.map_data_list.items()],
        entity_category=None,
        value_fn=lambda value, device: (
            device.status.selected_map.map_name
            if device.status.selected_map and device.status.selected_map.map_name
            else ""
        ),
        exists_fn=lambda description, device: device.capability.map and device.capability.multi_floor_map,
        value_int_fn=lambda value, device: next(
            (k for k, v in device.status.map_data_list.items() if v.map_name == value),
            None,
        ),
        attrs_fn=lambda device: (
            {
                ATTR_MAP_ID: device.status.selected_map.map_id,
                ATTR_MAP_INDEX: device.status.selected_map.map_index,
            }
            if device.status.selected_map
            else None
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Dreame Mower select based on a config entry."""
    coordinator: DreameMowerDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        DreameMowerSelectEntity(coordinator, description)
        for description in SELECTS
        if description.exists_fn(description, coordinator.device)
    )
    # Session-replay picker — dynamically populated from the on-disk
    # session archive so the Lovelace dashboard can pick a historical
    # run to overlay on the map without the user having to type a
    # filename into a service call.
    if getattr(coordinator, "session_archive", None) is not None:
        async_add_entities([DreameReplaySessionSelect(coordinator)])
    platform = entity_platform.current_platform.get()
    platform.async_register_entity_service(
        SERVICE_SELECT_NEXT,
        {vol.Optional(INPUT_CYCLE, default=True): bool},
        DreameMowerSelectEntity.async_next.__name__,
    )
    platform.async_register_entity_service(
        SERVICE_SELECT_PREVIOUS,
        {vol.Optional(INPUT_CYCLE, default=True): bool},
        DreameMowerSelectEntity.async_previous.__name__,
    )
    platform.async_register_entity_service(SERVICE_SELECT_FIRST, {}, DreameMowerSelectEntity.async_first.__name__)
    platform.async_register_entity_service(SERVICE_SELECT_LAST, {}, DreameMowerSelectEntity.async_last.__name__)


class DreameMowerSelectEntity(DreameMowerEntity, SelectEntity):
    """Defines a Dreame Mower select."""

    def __init__(
        self,
        coordinator: DreameMowerDataUpdateCoordinator,
        description: SelectEntityDescription,
    ) -> None:
        """Initialize Dreame Mower select."""
        if description.value_fn is None and (description.property_key is not None or description.key is not None):
            if description.property_key is not None:
                prop = f"{description.property_key.name.lower()}_name"
            else:
                prop = f"{description.key.lower()}_name"
            if hasattr(coordinator.device.status, prop):
                description.value_fn = lambda value, device: getattr(device.status, prop)

        if description.set_fn is None and (description.property_key is not None or description.key is not None):
            if description.property_key is not None:
                set_prop = f"set_{description.property_key.name.lower()}"
            else:
                set_prop = f"set_{description.key.lower()}"
            if hasattr(coordinator.device, set_prop):
                description.set_fn = lambda device, segment_id, value: getattr(device, set_prop)(value)

        if description.options is None and (description.property_key is not None or description.key is not None):
            if description.property_key is not None:
                options_prop = f"{description.property_key.name.lower()}_list"
            else:
                options_prop = f"{description.key.lower()}_list"
            if hasattr(coordinator.device.status, options_prop):
                description.options = lambda device, segment: list(getattr(device.status, options_prop))

        super().__init__(coordinator, description)
        self._generate_entity_id(ENTITY_ID_FORMAT)
        if description.options is not None:
            self._attr_options = description.options(coordinator.device, None)
        self._attr_current_option = self.native_value

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.entity_description.options is not None:
            self._attr_options = self.entity_description.options(self.device, None)
        self._attr_current_option = self.native_value
        super()._handle_coordinator_update()

    @callback
    async def async_select_index(self, idx: int) -> None:
        """Select new option by index."""
        new_index = idx % len(self._attr_options)
        await self.async_select_option(self._attr_options[new_index])

    @callback
    async def async_offset_index(self, offset: int, cycle: bool) -> None:
        """Offset current index."""
        current_index = self._attr_options.index(self._attr_current_option)
        new_index = current_index + offset
        if cycle:
            new_index = new_index % len(self._attr_options)
        elif new_index < 0:
            new_index = 0
        elif new_index >= len(self._attr_options):
            new_index = len(self._attr_options) - 1

        if cycle or current_index != new_index:
            await self.async_select_option(self._attr_options[new_index])

    @callback
    async def async_first(self) -> None:
        """Select first option."""
        await self.async_select_index(0)

    @callback
    async def async_last(self) -> None:
        """Select last option."""
        await self.async_select_index(-1)

    @callback
    async def async_next(self, cycle: bool) -> None:
        """Select next option."""
        await self.async_offset_index(1, cycle)

    @callback
    async def async_previous(self, cycle: bool) -> None:
        """Select previous option."""
        await self.async_offset_index(-1, cycle)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if not self.available:
            raise HomeAssistantError("Entity unavailable")

        if option not in self._attr_options:
            raise HomeAssistantError(
                f"Invalid option for {self.entity_description.name} {option}. Valid options: {self._attr_options}"
            )

        value = option
        if self.entity_description.value_int_fn is not None:
            value = self.entity_description.value_int_fn(option, self.device)

        if value is None:
            raise HomeAssistantError(
                f"Invalid option for {self.entity_description.name} {option}. Valid options: {self._attr_options}"
            )

        if not isinstance(value, int) and (
            isinstance(value, IntEnum) or (isinstance(value, str) and value.isnumeric())
        ):
            value = int(value)

        if self.entity_description.set_fn is not None:
            await self._try_command(
                "Unable to call %s",
                self.entity_description.set_fn,
                self.device,
                0,
                value,
            )
        elif self.entity_description.property_key is not None:
            await self._try_command(
                "Unable to call %s",
                self.device.set_property,
                self.entity_description.property_key,
                value,
            )




class DreameReplaySessionSelect(SelectEntity):
    """Dashboard picker for live-map mode.

    Options:

        "Latest"  — default. Auto-tracks the current run, or the newest
                    archived session if no run is active. When a new run
                    starts the map clears and begins drawing the new run
                    live. Survives archive growth automatically.
        "Blank"   — empty canvas (for screenshots). Not touched by
                    mower activity or archive events.
        "<date>"  — pinned to one archived session, newest-first. Frozen
                    until another mode is selected.

    Selecting an option calls ``live_map.set_mode(...)`` on an executor
    thread (blocking JSON parse keeps off the event loop). A sticky
    md5 pin preserves a date selection across archive growth even if
    the displayed label changes (area / duration can drift if the
    summary is re-ingested).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:history"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    _OPT_LATEST = "Latest"
    _OPT_BLANK = "Blank"

    def __init__(self, coordinator: DreameMowerDataUpdateCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_name = "Replay Session"
        self._attr_unique_id = f"{coordinator.device.mac}_replay_session"
        # Link to the Dreame A2 device so HA generates the entity_id with
        # the device-name prefix (`select.dreame_a2_mower_replay_session`)
        # and groups this picker under the mower in the device page.
        device = coordinator.device
        info = getattr(device, "info", None)
        from homeassistant.helpers.entity import DeviceInfo
        from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_NETWORK_MAC, device.mac)},
            identifiers={(DOMAIN, device.mac)},
            name=device.name,
            manufacturer=getattr(info, "manufacturer", None),
            model=getattr(info, "model", None),
            sw_version=getattr(info, "firmware_version", None),
            hw_version=getattr(info, "hardware_version", None),
        )
        self._attr_current_option = self._OPT_LATEST
        # Sticky pin for date selections, by md5 (completed) or by
        # start_ts (in-progress, no md5 yet). Survives label drift.
        self._pinned_md5: str | None = None
        self._pinned_start_ts: int | None = None
        self._refresh_options()

    @staticmethod
    def _format_label(entry) -> str:
        import datetime as _dt
        if getattr(entry, "still_running", False):
            # In-progress: anchor the label on start time, since end_ts
            # changes every tick. Show duration so far + a clear
            # "still running" suffix; area is the rough live estimate
            # (path length × deck swath) until the cloud lands a
            # leg summary.
            ts = _dt.datetime.fromtimestamp(entry.start_ts).strftime("%Y-%m-%d %H:%M")
            return (
                f"{ts} — {entry.area_mowed_m2:.2f} m² "
                f"({entry.duration_min} min, still running)"
            )
        ts = _dt.datetime.fromtimestamp(entry.end_ts).strftime("%Y-%m-%d %H:%M")
        return f"{ts} — {entry.area_mowed_m2:.2f} m² ({entry.duration_min} min)"

    def _entry_pin_id(self, entry) -> tuple[str, str | int]:
        """Stable identity tuple for an entry — md5 if known, start_ts otherwise.

        Used so the user's pin survives both label drift (in-progress
        ticks bump duration / area) and the eventual md5 assignment
        when a leg summary lands on a previously-pinned in-progress
        entry. Returns ``("md5", "<hex>")`` for completed entries and
        ``("start_ts", <int>)`` for in-progress entries.
        """
        if getattr(entry, "still_running", False):
            return ("start_ts", int(entry.start_ts))
        return ("md5", str(entry.md5))

    def _refresh_options(self) -> None:
        archive = self._coordinator.session_archive
        all_sessions = archive.list_sessions() if archive else []
        # Hard cap so the dropdown doesn't become a scroll nightmare
        # even if the user opted out of disk retention
        # (`session_archive_keep = 0`). list_sessions() is already
        # sorted newest-first (in-progress entry, when present, is at
        # the front via SessionArchive.list_sessions()).
        from .const import SESSION_REPLAY_PICKER_HARD_CAP
        sessions = all_sessions[:SESSION_REPLAY_PICKER_HARD_CAP]
        self._label_to_entry = {self._format_label(s): s for s in sessions}
        self._attr_options = [
            self._OPT_LATEST,
            self._OPT_BLANK,
            *self._label_to_entry.keys(),
        ]

    @property
    def available(self) -> bool:
        return self._coordinator.session_archive is not None

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_coordinator_update)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        prev_opts = tuple(self._attr_options)
        self._refresh_options()
        if tuple(self._attr_options) == prev_opts:
            return

        # Sticky pin: keep the user's selection alive across label drift
        # (in-progress entries change every tick as duration grows) and
        # across the in-progress → completed transition (md5 lands when
        # the leg summary arrives). Match by md5 first, then by start_ts.
        if self._pinned_md5 is not None or self._pinned_start_ts is not None:
            for label, entry in self._label_to_entry.items():
                if (
                    self._pinned_md5 is not None
                    and entry.md5 == self._pinned_md5
                ) or (
                    self._pinned_start_ts is not None
                    and int(entry.start_ts) == self._pinned_start_ts
                ):
                    self._attr_current_option = label
                    # Promote pin if the entry has acquired an md5 since
                    # we pinned it.
                    if entry.md5 and self._pinned_md5 is None:
                        self._pinned_md5 = entry.md5
                        self._pinned_start_ts = None
                    self.async_write_ha_state()
                    return
            # Pinned entry got evicted (retention) or was an in-progress
            # one that just disappeared without being promoted — drop
            # the pin and fall back to Latest.
            self._pinned_md5 = None
            self._pinned_start_ts = None
            self._attr_current_option = self._OPT_LATEST
            self.async_write_ha_state()
            return

        # Non-pinned (Latest / Blank) are always valid — no change.
        if self._attr_current_option not in self._attr_options:
            self._attr_current_option = self._OPT_LATEST
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options:
            raise HomeAssistantError(f"Unknown replay option: {option}")

        live_map = getattr(self._coordinator, "live_map", None)
        if live_map is None:
            raise HomeAssistantError("Live map is not available on this device")

        from .live_map import MapMode

        if option == self._OPT_LATEST:
            await self.hass.async_add_executor_job(live_map.set_mode, MapMode.LATEST)
            self._pinned_md5 = None
            self._pinned_start_ts = None
        elif option == self._OPT_BLANK:
            await self.hass.async_add_executor_job(live_map.set_mode, MapMode.BLANK)
            self._pinned_md5 = None
            self._pinned_start_ts = None
        else:
            entry = self._label_to_entry.get(option)
            if entry is None:
                raise HomeAssistantError(f"No archive entry for option {option}")
            if getattr(entry, "still_running", False):
                # In-progress entry can't freeze (no static wire-format
                # JSON to load) — picking it is semantically the same
                # as Latest. Pin by start_ts so the row stays visually
                # selected; LATEST mode auto-tracks the live path.
                await self.hass.async_add_executor_job(
                    live_map.set_mode, MapMode.LATEST
                )
                self._pinned_md5 = None
                self._pinned_start_ts = int(entry.start_ts)
            else:
                await self.hass.async_add_executor_job(
                    live_map.set_mode, MapMode.SESSION, entry
                )
                self._pinned_md5 = str(entry.md5)
                self._pinned_start_ts = None

        self._attr_current_option = option
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self._attr_current_option in (self._OPT_LATEST, self._OPT_BLANK):
            return {"pinned_md5": None}
        return {"pinned_md5": self._pinned_md5}
