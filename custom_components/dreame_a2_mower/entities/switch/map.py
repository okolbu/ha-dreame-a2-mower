"""Per-map switch entities for the Dreame A2 Mower.

This module is a helper — NOT a HA platform — so HA will not attempt to
load it as a switch platform.  It is imported by switch.py (the real
platform entry).

Contains:
  - DreameA2MapEdgemasterSwitch  (the only per-map switch)
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..._availability import _FreshnessAvailableMixin
from ..._devices import map_device_info, map_unique_id
from ...const import LOGGER
from ...control_honesty import _ControlHonestyMixin, resolve_control_mode
from ...coordinator import DreameA2MowerCoordinator


class DreameA2MapEdgemasterSwitch(
    _FreshnessAvailableMixin,
    _ControlHonestyMixin,
    CoordinatorEntity[DreameA2MowerCoordinator],
    SwitchEntity,
):
    """Per-map EdgeMaster — PRE-only write (DEVICE_WRITABLE).

    Reads from the s6.2 PRE shadow (state_machine.snapshot().pre_shadow_by_map_id).
    Each s6.2 push from the device is tagged with the active map_id at push
    time, so this entity converges per-map as the user saves Mowing-Settings
    in the Dreame app on each map. Unavailable until the first save on that
    map has been observed since install.

    Writes via coordinator.write_map_general_setting(map_id=..., pre_index=10,
    pre_value=int(enabled)) — PRE-only, no SETTINGS field (edgemaster has no
    SETTINGS surface on g2408 firmware; the device's s6.2 push refreshes the
    shadow after the PRE write is accepted).
    """

    _attr_has_entity_name = True
    # Reads the s6.2 PRE shadow (MQTT push), not the cloud SETTINGS fetch.
    _availability_source = "mqtt"
    _attr_translation_key = "settings_edgemaster"
    _attr_should_poll = False
    _attr_icon = "mdi:mower"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: DreameA2MowerCoordinator, *, map_id: int) -> None:
        super().__init__(coordinator)
        self._map_id = map_id
        self._attr_unique_id = map_unique_id(coordinator, map_id, "settings_edgemaster")
        map_obj = coordinator.cloud_state.maps_by_id.get(map_id)
        # has_entity_name=True; device_name is prepended automatically.
        self._attr_name = "EdgeMaster"
        self._attr_device_info = map_device_info(
            coordinator, map_id, name=getattr(map_obj, "name", None),
        )
        self._control_mode = resolve_control_mode(platform="switch", key="map_N_edgemaster")

    def _shadow_value(self) -> bool | None:
        sm = getattr(self.coordinator, "state_machine", None)
        if sm is None:
            return None
        try:
            snap = sm.snapshot()
        except Exception:
            return None
        shadow = getattr(snap, "pre_shadow_by_map_id", None) or {}
        entry = shadow.get(self._map_id)
        if not isinstance(entry, dict):
            return None
        v = entry.get("edgemaster")
        return None if v is None else bool(v)

    @property
    def is_on(self) -> bool | None:
        return self._shadow_value()

    @property
    def available(self) -> bool:
        if self._shadow_value() is None:
            return False
        return super().available

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, enabled: bool) -> None:
        if self.read_only:
            return await self._reject_readonly_write()
        ok = await self.coordinator.write_map_general_setting(
            map_id=self._map_id, pre_index=10, pre_value=int(enabled),
        )  # PRE-only: no settings_field (edgemaster has no SETTINGS field; reads s6p2 shadow)
        if not ok:
            await self.hass.services.async_call(
                "persistent_notification", "create",
                service_data={
                    "title": "Dreame A2 Mower: setting write rejected",
                    "message": f"The mower rejected EdgeMaster={enabled}.",
                    "notification_id": f"dreame_a2_write_fail_{self.entity_id}",
                },
                blocking=False,
            )
        self.async_write_ha_state()  # re-read shadow (refreshes from s6p2 push)
