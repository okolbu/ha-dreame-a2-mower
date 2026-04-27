"""Support for Dreame Mower buttons."""

from __future__ import annotations

from typing import Any
from dataclasses import dataclass
from collections.abc import Callable
from functools import partial
import copy

from homeassistant.components.button import (
    ENTITY_ID_FORMAT,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.config_entries import ConfigEntry

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import entity_registry
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN

from .coordinator import DreameMowerDataUpdateCoordinator
from .entity import DreameMowerEntity, DreameMowerEntityDescription
from .dreame import DreameMowerAction

# Action opcodes for the routed action endpoint (siid:2 aiid:50, m:'a').
# Sourced from apk.md §"Actions". Numbers stay verbatim rather than
# aliased to enums — the apk-side names are the canonical reference.
_OP_FIND_BOT = 9
_OP_LOCK_BOT = 12
_OP_SUPPRESS_FAULT = 11
_OP_GLOBAL_MOWER = 100        # start mowing entire saved lawn
_OP_EDGE_MOWER = 101          # mow only the lawn perimeter
_OP_ZONE_MOWER = 102          # zone mow — needs `{region: [zone_id]}` (use service)
_OP_SPOT_MOWER = 103          # spot mow — needs `{region: [spot_id]}` (use service)
_OP_START_LEARNING_MAP = 110  # manual map-build / Expand Lawn
_OP_TAKE_PIC = 401
_OP_CUTTER_BIAS = 503


@dataclass
class DreameMowerButtonEntityDescription(DreameMowerEntityDescription, ButtonEntityDescription):
    """Describes Dreame Mower Button entity."""

    action_fn: Callable[[object]] = None
    # Note: name_fn(value, device) is inherited from
    # DreameMowerEntityDescription. Buttons that want a dynamic
    # label populate it. The DreameMowerButtonEntity class below
    # overrides `name` so the label re-evaluates per access (the
    # base _set_id only runs once at __init__).


def _fire_zone_mow_selection(device):
    """Launch zoneMower (op 102) with device._zone_mow_selection.
    Clears the list on success so the selection switches reset."""
    selection = list(getattr(device, "_zone_mow_selection", None) or [])
    if not selection:
        return None
    ok = device.call_action_opcode(_OP_ZONE_MOWER, {"region": selection})
    if ok:
        device._zone_mow_selection = []
        device._active_task_kind = "zone"
    return ok


def _fire_spot_mow_selection(device):
    """Launch spotMower (op 103) with device._spot_mow_selection.
    Clears the list on success so the selection switches reset."""
    selection = list(getattr(device, "_spot_mow_selection", None) or [])
    if not selection:
        return None
    ok = device.call_action_opcode(_OP_SPOT_MOWER, {"region": selection})
    if ok:
        device._spot_mow_selection = []
        device._active_task_kind = "spot"
    return ok


def _fire_edge_mow_selection(device):
    """Launch edgeMower (op 101) scoped to device._edge_mow_selection.

    The Dreame app's "Edge" mode prompts the user to pick which zone's
    perimeter to mow — confirmed 2026-04-27 via UI inspection — so the
    routed-action call mirrors zoneMower's `region: [zone_id, ...]`
    payload but with the edge opcode. Clears the list on success and
    flags the device as edge-mowing for the camera renderer."""
    selection = list(getattr(device, "_edge_mow_selection", None) or [])
    if not selection:
        return None
    ok = device.call_action_opcode(_OP_EDGE_MOWER, {"region": selection})
    if ok:
        device._edge_mow_selection = []
        device._active_task_kind = "edge"
    return ok


def _active_action_label(device) -> str:
    """Map the current activity to a verb-noun label so Stop can read
    "Stop Mowing", "Stop Returning", "Stop Patrolling", etc.

    Discriminator order — most-specific first, generic fallback last:
      DreameMowerStatus.SPOT_CLEANING / ZONE_CLEANING / SEGMENT_CLEANING
        / FAST_MAPPING / CRUISING_PATH / CRUISING_POINT — sub-task types
      device.status.returning — returning to dock (any path)
      device.status.cleaning_paused — task paused on lawn
      DreameMowerStatus.CLEANING (generic mow) — fallback verb
    Returns just "Mowing" if no specific activity matches; the caller
    prefixes it with the action verb (e.g. "Stop "). Always returns
    something so the label is never empty.
    """
    from .dreame.types import DreameMowerStatus

    if getattr(device.status, "returning", False):
        return "Returning"
    status = getattr(device.status, "status", None)
    label_by_status = {
        DreameMowerStatus.SPOT_CLEANING: "Spot Mow",
        DreameMowerStatus.ZONE_CLEANING: "Zone Mow",
        DreameMowerStatus.SEGMENT_CLEANING: "Segment Mow",
        DreameMowerStatus.FAST_MAPPING: "Map Learning",
        DreameMowerStatus.CRUISING_PATH: "Patrolling",
        DreameMowerStatus.CRUISING_POINT: "Patrolling",
        DreameMowerStatus.SHORTCUT: "Shortcut",
        DreameMowerStatus.PART_CLEANING: "Mowing",
    }
    if status in label_by_status:
        return label_by_status[status]
    if getattr(device.status, "cleaning_paused", False) or getattr(device.status, "paused", False):
        return "Mowing"
    return "Mowing"


BUTTONS: tuple[ButtonEntityDescription, ...] = (
    # Availability gates — same state model used by all five action
    # buttons so behaviour stays coherent. Notes on the underlying flags:
    #   device.status.started   = task lifecycle is active (covers
    #                             actively-mowing, paused, AND returning-
    #                             to-dock-after-stop). NOT a "currently
    #                             driving" signal.
    #   device.status.paused    = task is paused on the lawn.
    #   device.status.returning = task is winding down (post-Stop or
    #                             auto-recharge).
    #   device.status.docked    = at the charging station.
    #
    # State→gate matrix:
    #                    Mowing  Paused  Returning  Docked  Idle-on-lawn
    #   Start            grey    YES     YES        YES     YES
    #   Edge             grey    grey    YES        YES     YES
    #   Stop             YES     YES     grey       grey    grey
    #   Pause            YES     grey    grey       grey    grey
    #   Dock             YES     YES     grey       grey    YES
    #   MapLearn         grey    grey    YES        YES     YES
    DreameMowerButtonEntityDescription(
        # Renamed 2026-04-27 from "Start Mowing" → "Start All-Area
        # Mowing" so the label distinguishes from the new
        # Start Selected Zone / Spot Mow buttons. The native
        # device.start_mowing() action drives the firmware's default
        # all-area mow (apk WorkingMode.ALL_AREA = 0). Manual mode
        # is BT-only and not exposable from HA.
        key="start_mowing",
        name="Start All-Area Mowing",
        icon="mdi:play",
        action_fn=lambda device: device.start_mowing(),
        # Greys only while an active running task is in progress.
        # Paused/returning/docked/idle all permit start (start_mowing
        # handles resume transparently when paused).
        available_fn=lambda device: not (
            bool(device.status.started)
            and not bool(getattr(device.status, "paused", False))
            and not bool(getattr(device.status, "returning", False))
        ),
    ),
    DreameMowerButtonEntityDescription(
        key="start_edge_mowing",
        name="Start Edge Mowing",
        icon="mdi:vector-square",
        action_fn=lambda device: (
            device.call_action_opcode(_OP_EDGE_MOWER)
            and (setattr(device, "_active_task_kind", "edge") or True)
        ),
        # Edge mow doesn't have a "resume" semantic — only enable when
        # there's no live task at all (returning / docked / idle ok).
        available_fn=lambda device: (
            not bool(device.status.started)
            or bool(getattr(device.status, "returning", False))
        ),
    ),
    # Start the accumulated zone selection (the per-zone "(mow next)"
    # switches in switch.py populate device._zone_mow_selection in
    # toggle order). Greyed out when the selection is empty so we
    # don't waste a routed-action call. Selection is cleared on a
    # successful start.
    DreameMowerButtonEntityDescription(
        key="start_selected_zone_mow",
        name="Start Selected Zone Mow",
        icon="mdi:select-multiple-marker",
        action_fn=lambda device: _fire_zone_mow_selection(device),
        available_fn=lambda device: (
            bool(getattr(device, "_zone_mow_selection", None))
            and (
                not bool(device.status.started)
                or bool(getattr(device.status, "returning", False))
            )
        ),
    ),
    DreameMowerButtonEntityDescription(
        key="start_selected_spot_mow",
        name="Start Selected Spot Mow",
        icon="mdi:bullseye-arrow",
        action_fn=lambda device: _fire_spot_mow_selection(device),
        available_fn=lambda device: (
            bool(getattr(device, "_spot_mow_selection", None))
            and (
                not bool(device.status.started)
                or bool(getattr(device.status, "returning", False))
            )
        ),
    ),
    DreameMowerButtonEntityDescription(
        key="start_selected_edge_mow",
        name="Start Selected Edge Mow",
        icon="mdi:vector-square",
        action_fn=lambda device: _fire_edge_mow_selection(device),
        available_fn=lambda device: (
            bool(getattr(device, "_edge_mow_selection", None))
            and (
                not bool(device.status.started)
                or bool(getattr(device.status, "returning", False))
            )
        ),
    ),
    DreameMowerButtonEntityDescription(
        key="pause_mowing",
        name="Pause Mowing",
        icon="mdi:pause",
        action_fn=lambda device: device.pause(),
        # Only when actively running (not paused, not returning).
        available_fn=lambda device: (
            bool(device.status.started)
            and not bool(getattr(device.status, "paused", False))
            and not bool(getattr(device.status, "returning", False))
        ),
    ),
    DreameMowerButtonEntityDescription(
        # Entity key kept as "dock" for backward-compat with any
        # existing dashboard / automation references; the user-facing
        # name "Recharge" matches the Dreame app's wording (the
        # firmware auto-charges on dock arrival, so semantically
        # identical).
        key="dock",
        name="Recharge",
        icon="mdi:battery-charging-50",
        action_fn=lambda device: device.return_to_base(),
        # Available whenever the mower is somewhere other than the dock
        # AND not already returning. Covers mowing / paused / idle-on-
        # lawn cases without flapping during the actual return.
        available_fn=lambda device: (
            not bool(getattr(device.status, "docked", False))
            and not bool(getattr(device.status, "returning", False))
        ),
    ),
    DreameMowerButtonEntityDescription(
        key="start_learning_map",
        name="Start Map Learning",
        icon="mdi:vector-polyline-edit",
        entity_category=EntityCategory.CONFIG,
        action_fn=lambda device: device.call_action_opcode(_OP_START_LEARNING_MAP),
        # Manual lawn-perimeter walk (BUILDING mode, s2p1=11). Same
        # gate as Edge Mow — needs a clean slate to start.
        available_fn=lambda device: (
            not bool(device.status.started)
            or bool(getattr(device.status, "returning", False))
        ),
    ),
    DreameMowerButtonEntityDescription(
        # Adaptive label — see name_fn. The default "Stop Mowing"
        # below is what HA shows before the device-state context
        # is loaded; once the integration is up, name_fn takes over
        # and rewrites it per the current activity.
        key="stop_mowing",
        name="Stop Mowing",
        icon="mdi:stop",
        action_fn=lambda device: device.stop(),
        # Available whenever the mower is doing SOMETHING — mowing,
        # returning, patrolling, map-learning, paused, etc. The user
        # may want to cancel a return mid-trip ("Stop Returning")
        # exactly as the Dreame app's "End Returning to Station"
        # button supports.
        available_fn=lambda device: bool(
            getattr(device.status, "started", False)
            or getattr(device.status, "returning", False)
            or getattr(device.status, "paused", False)
        ),
        name_fn=lambda value, device: f"Stop {_active_action_label(device)}",
    ),
    DreameMowerButtonEntityDescription(
        action_key=DreameMowerAction.RESET_BLADES,
        icon="mdi:car-turbocharger",
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda description, device: bool(
            DreameMowerEntityDescription().exists_fn(description, device)
            and device.status.blades_life is not None
        ),
    ),
    DreameMowerButtonEntityDescription(
        action_key=DreameMowerAction.RESET_SIDE_BRUSH,
        icon="mdi:pinwheel-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda description, device: bool(
            DreameMowerEntityDescription().exists_fn(description, device)
            and device.status.side_brush_life is not None
        ),
    ),
    DreameMowerButtonEntityDescription(
        action_key=DreameMowerAction.RESET_FILTER,
        icon="mdi:air-filter",
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda description, device: bool(
            DreameMowerEntityDescription().exists_fn(description, device) and device.status.filter_life is not None
        ),
    ),
    DreameMowerButtonEntityDescription(
        action_key=DreameMowerAction.RESET_SENSOR,
        icon="mdi:radar",
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda description, device: not device.capability.disable_sensor_cleaning,
    ),
    # Removed vacuum-only consumable-reset buttons (Cleanup Phase 1,
    # v2.0.0-alpha.32): RESET_SILVER_ION, RESET_LENSBRUSH,
    # RESET_SQUEEGEE. A2 has none of these consumables.
    DreameMowerButtonEntityDescription(
        key="find_bot",
        name="Find Mower",
        icon="mdi:bell-ring",
        action_fn=lambda device: device.call_action_opcode(_OP_FIND_BOT),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerButtonEntityDescription(
        key="lock_bot",
        name="Lock Mower",
        icon="mdi:lock",
        action_fn=lambda device: device.call_action_opcode(_OP_LOCK_BOT),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerButtonEntityDescription(
        key="suppress_fault",
        name="Clear Warning",
        icon="mdi:alert-octagon-outline",
        action_fn=lambda device: device.call_action_opcode(_OP_SUPPRESS_FAULT),
        exists_fn=lambda description, device: True,
    ),
    # Take Picture button removed 2026-04-27 (alpha.164). Op 401 is
    # the MIoT takePic opcode but the Dreame app's actual photo capture
    # bypasses it entirely — A/B test showed the app produced "Image
    # uploaded successful" with zero MQTT footprint while op 401 from
    # HA returned status:false. Real photo upload lives on a separate
    # cloud HTTP / OSS surface we haven't characterised. Re-add when
    # the apk's takePic flow handler is reverse-engineered or actual
    # cloud HTTPS traffic is sniffed via SSL-decrypt on the app.
    # _OP_TAKE_PIC = 401 constant kept at the top of this file for
    # the future re-add.
    DreameMowerButtonEntityDescription(
        key="cutter_bias",
        name="Calibrate Blade",
        icon="mdi:tune-vertical",
        action_fn=lambda device: device.call_action_opcode(_OP_CUTTER_BIAS),
        exists_fn=lambda description, device: True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Dreame Mower Button based on a config entry."""
    coordinator: DreameMowerDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        DreameMowerButtonEntity(coordinator, description)
        for description in BUTTONS
        if description.exists_fn(description, coordinator.device)
    )
    # Finalize-session button: forces a clean close of the in-progress
    # entry when the cloud event window is missed (HA down through the
    # actual end of mowing, mower offline at the moment of dock-up,
    # etc). Always present so the user can reach for it whenever the
    # picker shows a stuck "still running" entry that won't clear.
    async_add_entities([DreameMowerFinalizeSessionButton(coordinator)])

    if coordinator.device.capability.shortcuts or coordinator.device.capability.backup_map:
        update_buttons = partial(async_update_buttons, coordinator, {}, {}, async_add_entities)
        coordinator.async_add_listener(update_buttons)
        update_buttons()



@callback
def async_update_buttons(
    coordinator: DreameMowerDataUpdateCoordinator,
    current_shortcut: dict[str, list[DreameMowerShortcutButtonEntity]],
    current_map: dict[str, list[DreameMowerMapButtonEntity]],
    async_add_entities,
) -> None:
    new_entities = []
    if coordinator.device.capability.shortcuts:
        if coordinator.device.status.shortcuts:
            new_ids = set([k for k, v in coordinator.device.status.shortcuts.items()])
        else:
            new_ids = set([])

        current_ids = set(current_shortcut)

        for shortcut_id in current_ids - new_ids:
            async_remove_buttons(shortcut_id, coordinator, current_shortcut)

        for shortcut_id in new_ids - current_ids:
            current_shortcut[shortcut_id] = [
                DreameMowerShortcutButtonEntity(
                    coordinator,
                    DreameMowerButtonEntityDescription(
                        key="shortcut",
                        icon="mdi:play-speed",
                        available_fn=lambda device: not device.status.started
                        and not device.status.shortcut_task,
                    ),
                    shortcut_id,
                )
            ]
            new_entities = new_entities + current_shortcut[shortcut_id]

    if coordinator.device.capability.backup_map:
        new_indexes = set([k for k in range(1, len(coordinator.device.status.map_list) + 1)])
        current_ids = set(current_map)

        for map_index in current_ids - new_indexes:
            async_remove_buttons(map_index, coordinator, current_map)

        for map_index in new_indexes - current_ids:
            current_map[map_index] = [
                DreameMowerMapButtonEntity(
                    coordinator,
                    DreameMowerButtonEntityDescription(
                        key="backup",
                        icon="mdi:content-save",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        available_fn=lambda device: not device.status.started and not device.status.map_backup_status,
                    ),
                    map_index,
                )
            ]

            new_entities = new_entities + current_map[map_index]

    if new_entities:
        async_add_entities(new_entities)


def async_remove_buttons(
    id: str,
    coordinator: DreameMowerDataUpdateCoordinator,
    current: dict[str, DreameMowerButtonEntity],
) -> None:
    registry = entity_registry.async_get(coordinator.hass)
    entities = current[id]
    for entity in entities:
        if entity.entity_id in registry.entities:
            registry.async_remove(entity.entity_id)
    del current[id]


class DreameMowerButtonEntity(DreameMowerEntity, ButtonEntity):
    """Defines a Dreame Mower Button entity."""

    def __init__(
        self,
        coordinator: DreameMowerDataUpdateCoordinator,
        description: DreameMowerButtonEntityDescription,
    ) -> None:
        """Initialize a Dreame Mower Button entity."""
        super().__init__(coordinator, description)
        self._generate_entity_id(ENTITY_ID_FORMAT)

    @property
    def name(self) -> str | None:
        """Return the entity name. Defers to name_fn when the
        description provides one (so e.g. Stop Mowing can become
        "Stop Returning" mid-trip), otherwise falls back to the
        static base-class name. Mirrors the base _set_id call
        signature `(native_value, device)`."""
        name_fn = getattr(self.entity_description, "name_fn", None)
        if name_fn is not None:
            try:
                dynamic = name_fn(None, self.device)
            except Exception:  # pragma: no cover — defensive
                dynamic = None
            if dynamic:
                return f"{self.device.name} {dynamic}"
        return super().name

    async def async_press(self, **kwargs: Any) -> None:
        """Press the button."""
        if not self.available:
            raise HomeAssistantError("Entity unavailable")

        if self.entity_description.action_fn is not None:
            await self._try_command(
                "Unable to call %s",
                self.entity_description.action_fn,
                self.device,
            )
        elif self.entity_description.action_key is not None:
            await self._try_command(
                "Unable to call %s",
                self.device.call_action,
                self.entity_description.action_key,
            )


class DreameMowerShortcutButtonEntity(DreameMowerEntity, ButtonEntity):
    """Defines a Dreame Mower Shortcut Button entity."""

    def __init__(
        self,
        coordinator: DreameMowerDataUpdateCoordinator,
        description: DreameMowerButtonEntityDescription,
        shortcut_id: int,
    ) -> None:
        """Initialize a Dreame Mower Shortcut Button entity."""
        self.shortcut_id = shortcut_id
        self.shortcut = None
        self.shortcuts = None
        if coordinator.device and coordinator.device.status.shortcuts:
            self.shortcuts = copy.deepcopy(coordinator.device.status.shortcuts)
            for k, v in self.shortcuts.items():
                if k == self.shortcut_id:
                    self.shortcut = v
                    break

        super().__init__(coordinator, description)
        self.id = shortcut_id
        if self.id >= 32:
            self.id = self.id - 31
        self._attr_unique_id = f"{self.device.mac}_shortcut_{self.id}"
        self.entity_id = f"button.{self.device.name.lower()}_shortcut_{self.id}"

    def _set_id(self) -> None:
        """Set name of the entity"""
        key = "shortcut"
        if self.shortcut:
            name = self.shortcut.name
            if name.lower().startswith(key):
                name = name[8:]
            name = f"{key}_{name}"
        else:
            name = f"{key}_{self.id}"

        self._attr_name = f"{self.device.name} {name.replace('_', ' ').title()}"

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.shortcuts != self.device.status.shortcuts:
            self.shortcuts = copy.deepcopy(self.device.status.shortcuts)
            if self.shortcuts and self.shortcut_id in self.shortcuts:
                if self.shortcut != self.shortcuts[self.shortcut_id]:
                    self.shortcut = self.shortcuts[self.shortcut_id]
                    self._set_id()
            elif self.shortcut:
                self.shortcut = None
                self._set_id()

        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Return the extra state attributes of the entity."""
        return self.shortcut.__dict__

    async def async_press(self, **kwargs: Any) -> None:
        """Press the button."""
        if not self.available:
            raise HomeAssistantError("Entity unavailable")

        await self._try_command(
            "Unable to call %s",
            self.device.start_shortcut,
            self.shortcut_id,
        )


class DreameMowerMapButtonEntity(DreameMowerEntity, ButtonEntity):
    """Defines a Dreame Mower Map Button entity."""

    def __init__(
        self,
        coordinator: DreameMowerDataUpdateCoordinator,
        description: DreameMowerButtonEntityDescription,
        map_index: int,
    ) -> None:
        """Initialize a Dreame Mower Map Button entity."""
        self.map_index = map_index
        map_data = coordinator.device.get_map(self.map_index)
        self._map_name = map_data.custom_name if map_data else None
        super().__init__(coordinator, description)
        self._set_id()
        self._attr_unique_id = f"{self.device.mac}_backup_map_{self.map_index}"
        self.entity_id = f"button.{self.device.name.lower()}_backup_map_{self.map_index}"

    def _set_id(self) -> None:
        """Set name of the entity"""
        name = (
            f"{self.map_index}"
            if self._map_name is None
            else f"{self._map_name.replace('_', ' ').replace('-', ' ').title()}"
        )
        self._attr_name = f"{self.device.name} Backup Saved Map {name}"

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.device:
            map_data = self.device.get_map(self.map_index)
            if map_data and self._map_name != map_data.custom_name:
                self._map_name = map_data.custom_name
                self._set_id()

        self.async_write_ha_state()

    async def async_press(self, **kwargs: Any) -> None:
        """Press the button."""
        if not self.available:
            raise HomeAssistantError("Entity unavailable")

        await self._try_command(
            "Unable to call %s",
            self.device.backup_map,
            self.device.get_map(self.map_index).map_id,
        )


class DreameMowerFinalizeSessionButton(ButtonEntity):
    """Manually close out an in-progress mow.

    Used when the integration's auto-close (s2p56 says "no task" while
    `_prev_session_active=True`) won't fire — typical case is the mower
    being offline so s2p56 never recovers, leaving a "still running"
    entry in the picker indefinitely. Pressing the button calls
    `live_map.finalize_session()`, which:

    - drops the in-progress aggregator file, and
    - if no leg summary ever fired, synthesizes an "(incomplete)"
      archive entry from the captured live path so the run still
      shows up in the replay picker.

    Available whenever an in-progress entry exists on disk; otherwise
    greyed out.
    """

    _attr_icon = "mdi:stop-circle-outline"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(self, coordinator: DreameMowerDataUpdateCoordinator) -> None:
        self._coordinator = coordinator
        device = coordinator.device
        info = getattr(device, "info", None)
        self._attr_name = "Finalize Session"
        self._attr_unique_id = f"{device.mac}_finalize_session"
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

    @property
    def available(self) -> bool:
        archive = getattr(self._coordinator, "session_archive", None)
        if archive is None:
            return False
        return archive.in_progress_entry() is not None

    async def async_added_to_hass(self) -> None:
        # Refresh availability when an in-progress entry appears or
        # disappears (so the button enables/disables in real time).
        self.async_on_remove(
            self._coordinator.async_add_listener(self.async_write_ha_state)
        )

    async def async_press(self, **kwargs: Any) -> None:
        live_map = getattr(self._coordinator, "live_map", None)
        if live_map is None:
            raise HomeAssistantError("Live map is not available on this device")
        result = await self.hass.async_add_executor_job(live_map.finalize_session)
        if result.get("result") == "no_in_progress":
            raise HomeAssistantError("No in-progress session to finalize")
        # Force the picker / camera to refresh now that the entry has
        # vanished (or been promoted to an "(incomplete)" archive row).
        await self._coordinator.async_request_refresh()
