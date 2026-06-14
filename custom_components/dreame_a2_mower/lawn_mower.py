"""LawnMower platform for the Dreame A2 Mower integration.

Per spec §5.1: the primary state + control surface. Reads behavioural
state from the state machine snapshot; F3 wires action calls to cloud RPC.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.lawn_mower import (
    LawnMowerActivity,
    LawnMowerEntity,
    LawnMowerEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._availability import _FreshnessAvailableMixin
from ._devices import _MowerScopedEntity
from .const import DOMAIN, LOGGER
from .control_honesty import ControlMode, _ControlHonestyMixin
from .coordinator import DreameA2MowerCoordinator
from .coordinator._write_errors import raise_for_write_result
from .mower.actions import MowerAction
from .mower.state import ActionMode


def project_activity(snapshot) -> LawnMowerActivity:
    """Project StateSnapshot to HA's impoverished LawnMowerActivity enum.

    HA's enum has only MOWING / DOCKED / PAUSED / RETURNING / ERROR
    — no "idle on lawn" or "cruising" states. This function applies
    the projection rules from the spec (§ Entities consuming the
    snapshot, lawn_mower projection rules).
    """
    from .mower.state_snapshot import (
        CurrentActivity as CA, Location as L,
    )
    # An active latched fault OR a PIN-required emergency-stop both mean the
    # mower cannot continue without the user. pin_required is the terminal
    # state of the s1p1 safety chain (tilt/lift/bumper) — surfaced here so the
    # primary entity goes red, not just the diagnostic binary_sensor.
    if snapshot.errors or snapshot.pin_required:
        return LawnMowerActivity.ERROR
    ca = snapshot.current_activity
    if ca == CA.MOWING:
        return LawnMowerActivity.MOWING
    if ca == CA.PAUSED:
        return LawnMowerActivity.PAUSED
    if ca == CA.RETURNING:
        return LawnMowerActivity.RETURNING
    if ca == CA.CHARGE_RESUME:
        # current_activity often stays stuck at CHARGE_RESUME after a
        # mid-mow charge — MQTT only fires on change so the recovery to
        # MOWING never re-pushes. Use location as the tie-breaker: still
        # at the dock means projection-DOCKED is right; back ON_LAWN
        # means the mower is in fact mowing.
        if snapshot.location == L.AT_DOCK:
            return LawnMowerActivity.DOCKED
        return LawnMowerActivity.MOWING
    if ca == CA.IDLE:
        return (
            LawnMowerActivity.DOCKED
            if snapshot.location == L.AT_DOCK
            else LawnMowerActivity.PAUSED
        )
    if ca in (CA.CRUISING_TO_POINT, CA.FAST_MAPPING,
              CA.DRIVING_BLADES_UP, CA.REPOSITIONING,
              CA.PATROL_EDGE, CA.PATROL_POINT):
        return LawnMowerActivity.MOWING
    if ca == CA.AT_POINT:
        return LawnMowerActivity.PAUSED
    return LawnMowerActivity.ERROR


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the lawn_mower platform from a config entry."""
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DreameA2LawnMower(coordinator)])


class DreameA2LawnMower(
    _ControlHonestyMixin,
    _FreshnessAvailableMixin,
    _MowerScopedEntity,
    CoordinatorEntity[DreameA2MowerCoordinator],
    LawnMowerEntity,
):
    """The Dreame A2 mower as an HA lawn_mower entity.

    Behavioural state (activity, location, session) is read from the
    state machine snapshot (coordinator.state_machine.snapshot()).
    State persistence is handled by the state machine itself (SM-9).

    The primary control surface is DEVICE_WRITABLE (`_W` in
    control_honesty.CONTROL_MODES): start/pause/dock route to confirmed
    cloud RPCs. The _ControlHonestyMixin gives it the uniform
    control_mode / read_only / provisional attrs (no padlock for `_W`).
    """

    _attr_has_entity_name = True
    _availability_source = "mqtt"
    _attr_name = None  # use device name
    _control_mode = ControlMode.DEVICE_WRITABLE
    _attr_supported_features = (
        LawnMowerEntityFeature.START_MOWING
        | LawnMowerEntityFeature.PAUSE
        | LawnMowerEntityFeature.DOCK
    )
    _MOWER_KEY = "lawn_mower"

    @property
    def activity(self) -> LawnMowerActivity | None:
        """Project StateSnapshot to LawnMowerActivity via snapshot-based rules."""
        return project_activity(self.coordinator.state_machine.snapshot())

    async def async_start_mowing(self) -> None:
        """Start mowing in the currently-selected action_mode.

        Reads coordinator.data.action_mode + active_selection_zones/spots
        to pick the right opcode. Dispatches via coordinator.dispatch_action
        which routes to the working cloud path on g2408.
        """
        state = self.coordinator.data
        mode = state.action_mode
        if mode == ActionMode.ALL_AREAS:
            result = await self.coordinator.dispatch_action(MowerAction.START_MOWING, {})
            raise_for_write_result(result, "Start mowing", context="entity")
            return
        if mode == ActionMode.EDGE:
            result = await self.coordinator.dispatch_action(MowerAction.START_EDGE_MOW, {})
            raise_for_write_result(result, "Start mowing (edge)", context="entity")
            return
        if mode == ActionMode.ZONE:
            zones = state.active_selection_zones
            if not zones:
                LOGGER.warning("start_mowing: zone mode but no zones selected; no-op")
                return
            result = await self.coordinator.dispatch_action(
                MowerAction.START_ZONE_MOW, {"zones": list(zones)}
            )
            raise_for_write_result(result, "Start mowing (zone)", context="entity")
            return
        if mode == ActionMode.SPOT:
            spots = state.active_selection_spots
            if not spots:
                LOGGER.warning("start_mowing: spot mode but no spots selected; no-op")
                return
            result = await self.coordinator.dispatch_action(
                MowerAction.START_SPOT_MOW, {"spots": list(spots)}
            )
            raise_for_write_result(result, "Start mowing (spot)", context="entity")
            return
        LOGGER.warning("start_mowing: unknown action_mode %r", mode)

    async def async_pause(self) -> None:
        result = await self.coordinator.dispatch_action(MowerAction.PAUSE, {})
        raise_for_write_result(result, "Pause", context="entity")

    async def async_dock(self) -> None:
        result = await self.coordinator.dispatch_action(MowerAction.DOCK, {})
        raise_for_write_result(result, "Dock", context="entity")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Surface cloud-state diagnostics + the control-honesty verdict.

        Merges the _ControlHonestyMixin attrs (control_mode / read_only /
        provisional) with the cloud-side task_id.
        """
        attrs: dict[str, Any] = dict(super().extra_state_attributes)
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is not None:
            attrs["task_id"] = cs.task_id
        return attrs
