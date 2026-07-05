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

Offline last-known surfacing (Task 12b / P6.7)
----------------------------------------------
The 12a persistence layer seeds ``coord.data`` read-only fields from a LastKnown
Store before the first cloud fetch. This mixin is the ENTITY-SURFACE half: when
the freshness gate says NOT fresh, an entity that STILL HOLDS a value (its
resolved state / native value is not ``None`` — e.g. a seeded last-known value)
stays ``available`` and is marked ``stale`` via ``extra_state_attributes``,
instead of going unavailable. An entity that genuinely has no value still goes
unavailable. The ``None``-source (ungated) branch is unchanged — so the
connectivity-STATUS entities (``binary_sensor.cloud_connected`` /
``sensor.mqtt_connectivity``), which are ungated AND compute their state from a
LIVE ``value_fn`` (never seeded from LastKnown), keep showing the real
disconnected state offline and never a stale "connected".

NO ``homeassistant.*`` imports — pure mixin; works under the stubbed-HA test
harness.
"""
from __future__ import annotations

from typing import Any


class _FreshnessAvailableMixin:
    """Adds per-source staleness to an entity's ``available`` property."""

    #: "mqtt" | "cloud" | None — overridden per entity class or, for
    #: descriptor-driven entities, via a property reading the description.
    _availability_source: str | None = None

    #: State-value attributes probed, in order, to answer "does this entity
    #: currently hold a value?" generically for the last-known-sticky check.
    #: Covers every value-bearing platform that uses this mixin: sensor/number
    #: (``native_value``), switch/binary_sensor (``is_on``), select
    #: (``current_option``). Control entities without one of these (e.g. the
    #: lawn_mower, whose value is ``activity``) resolve to "no value" and keep
    #: the pre-12b unavailable-when-stale behaviour — deliberately conservative.
    _FRESHNESS_VALUE_ATTRS: tuple[str, ...] = ("native_value", "is_on", "current_option")

    def _freshness_is_fresh(self) -> bool | None:
        """Per-source freshness verdict, or ``None`` when the entity is ungated.

        ``None`` (source not "mqtt"/"cloud") means "not link-gated" — callers
        treat it as always-available and never-stale.
        """
        source = self._availability_source
        if source == "mqtt":
            return bool(self.coordinator.mqtt_is_fresh)  # type: ignore[attr-defined]
        if source == "cloud":
            return bool(self.coordinator.cloud_is_fresh)  # type: ignore[attr-defined]
        return None

    def _freshness_value(self) -> Any:
        """Best-effort resolve this entity's current state value; ``None`` = none held."""
        sentinel = object()
        for attr in self._FRESHNESS_VALUE_ATTRS:
            val = getattr(self, attr, sentinel)
            if val is not sentinel:
                return val
        return None

    def _is_freshness_stale(self) -> bool:
        """True when the source is stale but a last-known value keeps it visible."""
        fresh = self._freshness_is_fresh()
        if fresh is None or fresh:
            return False
        return self._freshness_value() is not None

    def _freshness_stale_attrs(self) -> dict[str, Any]:
        """``extra_state_attributes`` staleness marker.

        Empty dict when fresh, ungated, or holding no value — so entity classes
        can cheaply merge ``**self._freshness_stale_attrs()`` without perturbing
        their attrs on the happy path. ``last_updated`` is the coarse blob-level
        ``saved_unix`` of the last LastKnown persist (Task 12a), omitted if the
        coordinator does not expose it.
        """
        if not self._is_freshness_stale():
            return {}
        out: dict[str, Any] = {"stale": True}
        saved = getattr(self.coordinator, "last_known_saved_unix", None)  # type: ignore[attr-defined]
        if saved is not None:
            out["last_updated"] = saved
        return out

    @property
    def available(self) -> bool:
        # Base check first (value presence / coordinator.last_update_success).
        if not super().available:  # type: ignore[misc]
            return False
        fresh = self._freshness_is_fresh()
        if fresh is None:
            # Ungated source (None): keep the entity's own semantics.
            return True
        if fresh:
            return True
        # Source is stale: stay available ONLY while a last-known value is held,
        # so a seeded value shows (marked stale) instead of going unavailable.
        return self._freshness_value() is not None
