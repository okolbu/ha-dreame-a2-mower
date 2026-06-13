"""Per-source entity availability (Phase 1.1).

The coordinator is push-based (``update_interval=None``), so HA's
``CoordinatorEntity.available`` — which reflects
``coordinator.last_update_success`` — is only ever ``True``. On source loss
(MQTT drop / cloud-account outage) entities therefore *froze* at their last
value instead of going ``unavailable``.

This mixin restores honest availability by consulting the coordinator's two
per-source freshness signals (``mqtt_is_fresh`` / ``cloud_is_fresh``). Each
entity declares which source feeds it via ``_availability_source``:

- ``"mqtt"``  — value comes from the device MQTT push (position, activity,
  ``lawn_mower``, heartbeat-derived). Unavailable when the link goes stale
  (``HB_STALENESS_S`` = 90s with no heartbeat).
- ``"cloud"`` — value comes from the 2-min full-state cloud poll
  (CFG / SETTINGS / MIHIS / MAPL). Unavailable after the poll fails
  ``_CLOUD_UNAVAIL_THRESHOLD`` consecutive cycles.
- ``None`` (default) — not gated on link freshness: local-archive, static /
  config-derived, and rendered entities keep their own ``value-is-None``
  availability semantics.

Place the mixin BEFORE ``CoordinatorEntity`` in the MRO so ``super().available``
still resolves to the base check (value-None / last_update_success) first — a
``False`` there always wins.

NO ``homeassistant.*`` imports — pure mixin; works under the stubbed-HA test
harness.
"""
from __future__ import annotations


class _FreshnessAvailableMixin:
    """Adds per-source staleness to an entity's ``available`` property."""

    #: "mqtt" | "cloud" | None — overridden per entity class or, for
    #: descriptor-driven entities, via a property reading the description.
    _availability_source: str | None = None

    @property
    def available(self) -> bool:
        # Base check first (value presence / coordinator.last_update_success).
        if not super().available:  # type: ignore[misc]
            return False
        source = self._availability_source
        if source == "mqtt":
            return bool(self.coordinator.mqtt_is_fresh)  # type: ignore[attr-defined]
        if source == "cloud":
            return bool(self.coordinator.cloud_is_fresh)  # type: ignore[attr-defined]
        return True
