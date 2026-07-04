"""Shared base classes and description dataclass for the switch platform.

This module is a helper — NOT a HA platform — so HA will not attempt to
load it as a switch platform.  It is imported by entities/switch/global_.py,
entities/switch/map.py, and switch.py.

Acyclic import order:
    entities.switch.base  ←  entities.switch.global_ / .map  ←  switch.py
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from collections.abc import Callable

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..._availability import _FreshnessAvailableMixin
from ..._devices import map_device_info, map_unique_id, mower_device_info, mower_unique_id
from ...const import LOGGER
from ...control_honesty import _ControlHonestyMixin, resolve_control_mode
from ...coordinator import DreameA2MowerCoordinator
from ...coordinator._write_errors import raise_for_write_result
from ...mower.state import MowerState
from ..._settings_writes import pre_settings_optimistic_write


# ---------------------------------------------------------------------------
# Descriptor
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class DreameA2SwitchEntityDescription(SwitchEntityDescription):
    """Switch descriptor with typed value_fn and optional write helpers.

    ``value_fn``       — reads the current bool from MowerState.
    ``cfg_key``        — if set, the entity is writable via
                         coordinator.write_setting(cfg_key, full_value).
                         If None, the switch is read-only in F4.
    ``build_value_fn`` — builds the full wire value to pass to write_setting.
                         Takes (current_state, new_enabled_bool).
    ``field_updates_fn`` — returns {field_name: value} for the optimistic
                            state update applied by coordinator.write_setting.
    """

    value_fn: Callable[[MowerState], bool | None]
    cfg_key: str | None = None
    build_value_fn: Callable[[MowerState, bool], Any] | None = None
    build_from_cfg_fn: Callable[[Any, bool], Any] | None = None
    field_updates_fn: Callable[[MowerState, bool], dict[str, Any]] | None = None


# ---------------------------------------------------------------------------
# Entity class
# ---------------------------------------------------------------------------

class DreameA2Switch(
    _FreshnessAvailableMixin,
    _ControlHonestyMixin,
    CoordinatorEntity[DreameA2MowerCoordinator],
    SwitchEntity,
):
    """A coordinator-backed switch entity.

    Settable entities call coordinator.write_setting; read-only entities
    log a warning and no-op when async_turn_on / async_turn_off is called.
    """

    _attr_has_entity_name = True
    # All SWITCHES rows are CFG-fed — cloud-sourced.
    _availability_source = "cloud"
    entity_description: DreameA2SwitchEntityDescription

    def __init__(
        self,
        coordinator: DreameA2MowerCoordinator,
        description: DreameA2SwitchEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = mower_unique_id(coordinator, description.key)
        self._attr_device_info = mower_device_info(coordinator)
        self._control_mode = resolve_control_mode(platform="switch", key=description.key)

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def available(self) -> bool:
        """Mark unavailable until the first state read populates ``is_on``.

        HA renders a SwitchEntity with ``is_on=None`` using its
        assumed-state widget (two separate Turn-On / Turn-Off buttons),
        which loses the visual state-on-page. Returning ``available=False``
        instead surfaces the entity as a greyed-out single toggle until
        the periodic CFG fetch populates the backing field — much closer
        to the user expectation of "a switch I can read and write".
        Once the value is non-None, super().available reflects the
        coordinator's normal availability logic.
        """
        if self.entity_description.value_fn(self.coordinator.data) is None:
            return False
        return super().available

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._async_set_value(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._async_set_value(False)

    async def _async_set_value(self, enabled: bool) -> None:
        """Write the new state to the mower via the coordinator."""
        if self.read_only:
            return await self._reject_readonly_write()
        desc = self.entity_description
        if desc.cfg_key is None:
            LOGGER.warning(
                "switch.%s: no write path configured (read-only in F4); "
                "ignoring turn_%s",
                desc.key,
                "on" if enabled else "off",
            )
            return

        # Build the full wire value expected by the firmware.
        if desc.build_from_cfg_fn is not None:
            cs = getattr(self.coordinator, "cloud_state", None)
            raw = cs.cfg.get(desc.cfg_key) if cs is not None else None
            wire_value = desc.build_from_cfg_fn(raw, enabled)
            if wire_value is None:
                # No cached base to RMW from — don't send a partial payload.
                LOGGER.warning(
                    "switch.%s: no cfg base for %s; write aborted",
                    getattr(self, "entity_id", desc.key), desc.cfg_key,
                )
                self.async_write_ha_state()  # snap back
                return
        elif desc.build_value_fn is not None:
            wire_value = desc.build_value_fn(self.coordinator.data, enabled)
        else:
            wire_value = int(enabled)

        # Collect optimistic field updates (optional).
        field_updates: dict[str, Any] | None = None
        if desc.field_updates_fn is not None:
            field_updates = desc.field_updates_fn(self.coordinator.data, enabled)

        result = await self.coordinator.write_setting(
            desc.cfg_key,
            wire_value,
            field_updates=field_updates,
        )
        # P2 Task 5: surface the honest device verdict — a rejected/undelivered
        # CFG write raises instead of silently snapping back (T3-3).
        # write_setting already reverted any optimistic field_updates.
        raise_for_write_result(
            result, f"Set {desc.cfg_key} ({desc.key})", context="entity"
        )


# ---------------------------------------------------------------------------
# AI obstacle recognition bit-switches (Task 14) — shared base
# ---------------------------------------------------------------------------

_AI_HUMANS_BIT = 1 << 0
_AI_ANIMALS_BIT = 1 << 1
_AI_OBJECTS_BIT = 1 << 2


class _AiRecognitionBitSwitch(
    _FreshnessAvailableMixin,
    _ControlHonestyMixin,
    CoordinatorEntity[DreameA2MowerCoordinator],
    SwitchEntity,
):
    """Common base for the 3 AI obstacle recognition bit switches.

    Each subclass sets _BIT (one of _AI_HUMANS_BIT / _ANIMALS_BIT /
    _OBJECTS_BIT) and the entity-name / unique-id attrs.
    Per-map: each instance is bound to a specific map_id.
    """

    _BIT: int = 0
    _HONESTY_LEAF: str = ""
    _attr_has_entity_name = True
    _attr_should_poll = False
    # Reads cloud_state.settings (SETTINGS.obstacleAvoidanceAi) — cloud.
    _availability_source = "cloud"

    def __init__(self, coordinator: DreameA2MowerCoordinator, *, map_id: int) -> None:
        super().__init__(coordinator)
        self._map_id = map_id
        self._attr_device_info = map_device_info(
            coordinator, map_id,
            name=getattr(coordinator.cloud_state.maps_by_id.get(map_id), "name", None),
        )
        self._control_mode = resolve_control_mode(
            platform="switch", key=f"map_N_{self._HONESTY_LEAF}"
        )

    @property
    def is_on(self) -> bool | None:
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is None:
            return None
        raw = cs.settings.by_map_id_canonical.get(self._map_id, {}).get("obstacleAvoidanceAi")
        if raw is None:
            return None
        return bool(raw & self._BIT)

    @property
    def available(self) -> bool:
        if self.is_on is None:
            return False
        return super().available

    async def _toggle(self, on: bool) -> None:
        if self.read_only:
            return await self._reject_readonly_write()
        coord = self.coordinator
        cs = getattr(coord, "cloud_state", None)
        if cs is None:
            LOGGER.warning("%s: no cloud_state — toggle deferred", self.entity_id)
            return
        old = cs.settings.by_map_id_canonical.get(self._map_id, {}).get("obstacleAvoidanceAi") or 0
        new_mask = (old | self._BIT) if on else (old & ~self._BIT)
        if new_mask == old:
            return
        # _BIT is a mask (1/2/4); bit_length()-1 gives the 0-based bit index (0/1/2).
        bit = self._BIT.bit_length() - 1
        # Optimistic update on MowerState mirror (settings_obstacle_avoidance_ai stores the
        # full bitmask int; we write the new combined mask here, not a per-bit bool).
        # Route through async_set_updated_data (P2-inherit): the P3.1 listener-aware
        # stub notifies, so a bare `coord.data =` + local async_write_ha_state no
        # longer under-notifies siblings — the coordinator broadcast covers this
        # entity AND its siblings in one hop.
        coord.async_set_updated_data(
            dataclasses.replace(coord.data, settings_obstacle_avoidance_ai=new_mask)
        )
        result = await coord.write_map_general_ai_bit(
            map_id=self._map_id,
            bit=bit,
            on=on,
            settings_value=new_mask,
        )
        if result.accepted:
            return
        coord.async_set_updated_data(
            dataclasses.replace(coord.data, settings_obstacle_avoidance_ai=old)
        )
        await self.hass.services.async_call(
            "persistent_notification", "create",
            service_data={
                "title": "Dreame A2 Mower: setting write rejected",
                "message": (
                    f"The mower rejected the AI recognition toggle. "
                    f"Previous bitfield value: 0b{old:03b}."
                ),
                "notification_id": f"dreame_a2_write_fail_{self.entity_id}",
            },
            blocking=False,
        )
        # P2 Task 5: after the revert + notification, also raise so the UI
        # action that triggered the write shows the honest device verdict.
        raise_for_write_result(result, "Set AI recognition", context="entity")

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._toggle(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._toggle(False)


# ---------------------------------------------------------------------------
# Per-map SETTINGS switches (Task 8) — shared base + descriptor table
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class _PerMapSettingsSwitchSpec:
    """Static descriptor for a per-map SETTINGS switch.

    All four per-map SETTINGS switches share identical structure; they differ
    only in these fields:

    ``key``            — unique_id suffix + translation_key + MowerState
                         settings_field (all three are the same string, e.g.
                         ``settings_edge_mowing_auto``).
    ``name``           — entity-name only (device name is prepended by HA).
    ``settings_field`` — the cloud SETTINGS canonical key (e.g.
                         ``edgeMowingAuto``).
    ``pre_index``      — the PRE-array index the write patches.
    ``honesty_leaf``   — the control-mode leaf passed to ``resolve_control_mode``
                         (``map_N_<leaf>``).
    """

    key: str
    name: str
    settings_field: str
    pre_index: int
    honesty_leaf: str


# Order preserved from the original switch_global.py definitions so entity
# discovery order (and any registry ordering side effects) is unchanged.
PER_MAP_SETTINGS_SWITCHES: tuple[_PerMapSettingsSwitchSpec, ...] = (
    _PerMapSettingsSwitchSpec(
        key="settings_edge_mowing_auto",
        name="Automatic Edge Mowing",
        settings_field="edgeMowingAuto",
        pre_index=7,
        honesty_leaf="automatic_edge_mowing",
    ),
    _PerMapSettingsSwitchSpec(
        key="settings_edge_mowing_safe",
        name="Safe Edge Mowing",
        settings_field="edgeMowingSafe",
        pre_index=16,
        honesty_leaf="safe_edge_mowing",
    ),
    _PerMapSettingsSwitchSpec(
        key="settings_edge_mowing_obstacle_avoidance",
        name="Obstacle Avoidance on Edges",
        settings_field="edgeMowingObstacleAvoidance",
        pre_index=9,
        honesty_leaf="obstacle_avoidance_on_edges",
    ),
    _PerMapSettingsSwitchSpec(
        key="settings_obstacle_avoidance_enabled",
        name="LiDAR Obstacle Recognition",
        settings_field="obstacleAvoidanceEnabled",
        pre_index=12,
        honesty_leaf="lidar_obstacle_recognition",
    ),
)


class _PerMapSettingsSwitchBase(
    _FreshnessAvailableMixin,
    _ControlHonestyMixin,
    CoordinatorEntity[DreameA2MowerCoordinator],
    SwitchEntity,
):
    """Shared base for the per-map SETTINGS switches.

    Each concrete subclass binds a ``_SPEC`` (a ``_PerMapSettingsSwitchSpec``)
    and is instantiated per map_id. Reads from
    ``cloud_state.settings.by_map_id_canonical[map_id][settings_field]``;
    writes via ``pre_settings_optimistic_write`` (dual PRE + SETTINGS write).

    The ``_SPEC.key`` doubles as the unique_id suffix, the translation_key, and
    the MowerState ``state_field`` — all three were already equal in the
    original per-switch classes, so collapsing them here keeps every
    unique_id / entity_id / control_mode byte-identical.
    """

    _SPEC: _PerMapSettingsSwitchSpec

    _attr_has_entity_name = True
    _availability_source = "cloud"
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator, *, map_id: int) -> None:
        super().__init__(coordinator)
        spec = self._SPEC
        self._map_id = map_id
        self._attr_translation_key = spec.key
        self._attr_unique_id = map_unique_id(coordinator, map_id, spec.key)
        # has_entity_name=True; device_name is prepended automatically.
        self._attr_name = spec.name
        self._attr_device_info = map_device_info(
            coordinator, map_id,
            name=getattr(coordinator.cloud_state.maps_by_id.get(map_id), "name", None),
        )
        self._control_mode = resolve_control_mode(
            platform="switch", key=f"map_N_{spec.honesty_leaf}"
        )

    @property
    def is_on(self) -> bool | None:
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is None:
            return None
        raw = cs.settings.by_map_id_canonical.get(self._map_id, {}).get(
            self._SPEC.settings_field
        )
        return None if raw is None else bool(raw)

    @property
    def available(self) -> bool:
        # See DreameA2Switch.available — return False on None to collapse
        # HA's two-button assumed-state widget into a single greyed-out toggle.
        if self.is_on is None:
            return False
        return super().available

    async def _write(self, new_value: bool) -> None:
        if self.read_only:
            return await self._reject_readonly_write()
        spec = self._SPEC
        await pre_settings_optimistic_write(
            self, state_field=spec.key, new_value=new_value,
            map_id=self._map_id, pre_index=spec.pre_index,
            pre_value=int(new_value),
            settings_field=spec.settings_field, settings_value=int(new_value),
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._write(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._write(False)
