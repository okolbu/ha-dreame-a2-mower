"""Experimental-features opt-in gate mechanism (P4 / R-52).

ONE config-entry option (``experimental_features``, default off) governs both
experimental ENTITIES and experimental SERVICES. Descriptors carry an
``experimental`` tier string (see ``const.EXPERIMENTAL_*``); production
descriptors leave it ``None``.

Entity gate (``filter_experimental``):
  * gate OFF → an experimental descriptor's entity is NOT created at all;
  * gate ON  → it is created but forced ``entity_registry_enabled_default=False``
    so it lands disabled in the registry (still opt-in per-entity once on).

Service gate (``services.experimental_service``, defined in the services
package but reading this module's ``experimental_features_enabled``):
  * gate OFF → the handler RAISES ServiceValidationError with a clear message.

This is a shared leaf: it imports only ``const`` and is used by every platform
entry file + the camera package + the services package.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .const import (
    CONF_DEBUG_SERVICES,
    CONF_EXPERIMENTAL_FEATURES,
    DEFAULT_EXPERIMENTAL_FEATURES,
)


def experimental_features_enabled(entry: Any | None) -> bool:
    """Whether the experimental-features gate is ON for this config entry.

    Reads the ``experimental_features`` option (default False). Honours the
    LEGACY ``debug_services`` option for backward-compat: a pre-P4 entry that
    still carries ``debug_services=True`` enables the unified gate without a
    re-configure (graceful single-user cutover). An entry with no ``options``
    attribute (or ``None``) is treated as OFF, never a crash.
    """
    if entry is None:
        return DEFAULT_EXPERIMENTAL_FEATURES
    opts = getattr(entry, "options", None) or {}
    if bool(opts.get(CONF_EXPERIMENTAL_FEATURES, DEFAULT_EXPERIMENTAL_FEATURES)):
        return True
    # Legacy fallback: honour a pre-P4 debug_services=True option.
    return bool(opts.get(CONF_DEBUG_SERVICES, False))


def _entity_experimental_tier(entity: Any) -> str | None:
    """Read the experimental tier for an entity (None if it is a production surface).

    Two sources, checked in order:

    1. ``entity.entity_description.experimental`` — the descriptor field. Used by
       the descriptor-driven platforms (sensor / switch / select-settings /
       number / binary_sensor / time), whose tables carry the tier per row.
    2. ``entity._experimental_tier`` — a per-instance (class-attr) fallback for
       the descriptorLESS entity classes that set ``_attr_*`` directly and never
       build an EntityDescription: ``update.firmware`` (whole-entity NOT gated —
       only its install is, see update.py), ``camera.obstacle_photo``,
       ``button.refresh_mpos``, ``select.active_map``. Giving each an
       EntityDescription purely to carry one field would be more churn than a
       single class attr, so ``filter_experimental`` honours both.
    """
    desc = getattr(entity, "entity_description", None)
    tier = getattr(desc, "experimental", None)
    if tier is not None:
        return tier
    return getattr(entity, "_experimental_tier", None)


def filter_experimental(entry: Any | None, entities: Iterable[Any]) -> list[Any]:
    """Return the entities to actually create, honouring the experimental gate.

    - A descriptor with no ``experimental`` tier → always created (unchanged).
    - Experimental descriptor + gate OFF → SKIPPED (entity not created at all).
    - Experimental descriptor + gate ON → created, forced
      ``entity_registry_enabled_default=False`` so it lands disabled in the
      registry (opt-in per entity even once the gate is on).

    No production descriptor sets ``experimental`` yet (P4.4 populates them), so
    today this is a pass-through: every entity is created unchanged.
    """
    enabled = experimental_features_enabled(entry)
    result: list[Any] = []
    for entity in entities:
        tier = _entity_experimental_tier(entity)
        if tier is None:
            result.append(entity)
            continue
        if not enabled:
            continue  # gate off → do not create the experimental entity
        entity._attr_entity_registry_enabled_default = False
        result.append(entity)
    return result
