"""Identifier and DeviceInfo factories for the mower + map sub-devices.

Centralises the SN-based keying introduced in Phase 2. All entities
should construct their unique_id and device_info via these helpers so
unique_id patterns have a single source of truth.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
)

from .const import DEFAULT_MODEL, DEFAULT_NAME, DOMAIN, MANUFACTURER

if TYPE_CHECKING:
    from .coordinator import DreameA2MowerCoordinator


def _stable_id(coord: DreameA2MowerCoordinator) -> str:
    """Return the most stable identifier available for this mower.

    Prefers the hardware SN. Falls back to mac (prefixed `mac:`) and
    finally to the config entry id (`entry:`). The fallback prefixes
    keep the namespace explicit so the migration can detect them.
    """
    sn = getattr(coord, "sn", None)
    if sn:
        return sn
    client = getattr(coord, "_cloud", None)
    mac = getattr(client, "mac_address", None) if client is not None else None
    if mac:
        return f"mac:{mac}"
    return f"entry:{coord.entry.entry_id}"


def mower_identifiers(coord: DreameA2MowerCoordinator) -> set[tuple[str, str]]:
    return {(DOMAIN, _stable_id(coord))}


def map_identifiers(
    coord: DreameA2MowerCoordinator, map_id: int
) -> set[tuple[str, str]]:
    return {(DOMAIN, f"{_stable_id(coord)}_map_{map_id}")}


def mower_unique_id(coord: DreameA2MowerCoordinator, key: str) -> str:
    return f"{_stable_id(coord)}_{key}"


def map_unique_id(
    coord: DreameA2MowerCoordinator, map_id: int, key: str
) -> str:
    return f"{_stable_id(coord)}_map_{map_id}_{key}"


def mower_device_info(coord: DreameA2MowerCoordinator) -> DeviceInfo:
    client = getattr(coord, "_cloud", None)
    model = getattr(client, "model", None) if client is not None else None
    mac = getattr(client, "mac_address", None) if client is not None else None
    sn = getattr(coord, "sn", None)
    info: dict[str, Any] = {
        "identifiers": mower_identifiers(coord),
        "manufacturer": MANUFACTURER,
        "model": model or DEFAULT_MODEL,
        "name": DEFAULT_NAME,
    }
    if sn:
        info["serial_number"] = sn
    if mac:
        info["connections"] = {(CONNECTION_NETWORK_MAC, mac)}
    return DeviceInfo(**info)


class _MowerScopedEntity:
    """Mixin for parent-device ("class-B") entities whose ``__init__`` does the
    repeated 3-line mower-scoped wiring:

        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "<key>")
        self._attr_device_info = mower_device_info(coordinator)

    Subclasses set the class attribute ``_MOWER_KEY`` to the entity key (the
    unique_id suffix). The mixin must precede ``CoordinatorEntity`` in the base
    list so its ``__init__`` runs and forwards ``coordinator`` to the chain.

    It is a PURE wiring mixin: it sets no availability source and overrides no
    other behaviour, so concrete classes keep their own ``_availability_source``
    / ``_attr_*`` declarations (including P1.1 staleness tags) untouched.
    """

    _MOWER_KEY: str = "override-me"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, self._MOWER_KEY)
        self._attr_device_info = mower_device_info(coordinator)


def map_device_info(
    coord: DreameA2MowerCoordinator,
    map_id: int,
    name: str | None,
) -> DeviceInfo:
    # Per-map device names are PREFIXED with the parent integration's
    # display name so every per-map entity_id auto-slugifies into the
    # integration's namespace — ``<platform>.dreame_a2_mower_map_N_<key>``
    # rather than ``<platform>.map_N_<key>``. The bare "Map N" form
    # collided with other integrations' generic Map entities and made
    # the per-map / parent-device prefixes look unrelated in the UI.
    # See CLAUDE.md § "Per-map naming convention".
    suffix = name or f"Map {map_id + 1}"
    display_name = f"{DEFAULT_NAME} {suffix}"
    return DeviceInfo(
        identifiers=map_identifiers(coord, map_id),
        via_device=(DOMAIN, _stable_id(coord)),
        manufacturer=MANUFACTURER,
        name=display_name,
    )
