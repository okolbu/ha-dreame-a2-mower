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

Offline last-known surfacing (Task 12b / P6.7) — CLOUD-ONLY (final-fix)
----------------------------------------------------------------------
The 12a persistence layer seeds ``coord.data`` read-only fields from a LastKnown
Store before the first cloud fetch — and every field it persists/seeds is a
``_availability_source == "cloud"`` field (consumables / SIM / dock / firmware /
settings switches / wifi / schedule-count / ota). This mixin is the
ENTITY-SURFACE half, and the last-known stickiness is deliberately restricted to
the **cloud** source:

- ``"cloud"`` — when the cloud gate goes stale, an entity that STILL HOLDS a
  value (its resolved state / native value is not ``None`` — a seeded last-known
  value) stays ``available`` and is marked ``stale`` via
  ``extra_state_attributes`` instead of going unavailable. An entity that
  genuinely has no value still goes unavailable.
- ``"mqtt"`` — NO stickiness. When the MQTT gate goes stale the entity goes
  ``unavailable`` (the pre-12b behaviour). This is a SAFETY-HONESTY requirement:
  the MQTT-source binary_sensors carry live safety flags (emergency_stop,
  safety_alert_active, drop_tilt, lift, bumper, wheel_bind_active, …) that hold
  NO persisted last-known. Keeping them ``available`` on a stale link would show
  a frozen "all clear" (e.g. ``emergency_stop=off``) when we genuinely can't
  hear the mower — a dangerous regression. Honest ``unavailable`` is the only
  safe surface. (Task 12b originally made stickiness apply to any gated source;
  this was too broad and is corrected here.)
- ``None`` (ungated) — unchanged. The connectivity-STATUS entities
  (``binary_sensor.cloud_connected`` / ``sensor.mqtt_connectivity``) are ungated
  AND compute their state from a LIVE ``value_fn`` (never seeded from
  LastKnown), so they keep showing the real disconnected state offline and never
  a stale "connected".

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
        """True when a CLOUD source is stale but a last-known value keeps it visible.

        Stickiness (and therefore the ``stale`` marker) is CLOUD-ONLY: mqtt-source
        entities go unavailable when stale (no last-known to surface — see the
        module docstring's safety-honesty note), so they are never "stale".
        """
        if self._availability_source != "cloud":
            return False
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
    def extra_state_attributes(self) -> Any:
        """Merge the cloud-source staleness marker with the entity's own attrs.

        Placed on the mixin so every freshness-gated platform (number / select /
        time / per-map sensor / …) picks up the ``stale`` marker uniformly, via
        the MRO ``super()`` chain, without each class re-implementing the merge.
        ``_freshness_stale_attrs()`` is CLOUD-gated and returns ``{}`` unless a
        cloud source is stale-but-holding-a-value, so mqtt/ungated entities are
        byte-identical to before. Returns the parent's value untouched (possibly
        ``None``) on the happy path — never fabricates an empty dict.
        """
        parent = getattr(super(), "extra_state_attributes", None)
        stale = self._freshness_stale_attrs()
        if not stale:
            return parent
        return {**(parent or {}), **stale}

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
        # Source is STALE. Stickiness is CLOUD-ONLY: a stale cloud entity stays
        # available while it holds a (seeded) last-known value, shown marked
        # ``stale``. An mqtt-source entity has no last-known and may carry a live
        # SAFETY flag, so it goes honestly UNAVAILABLE — never a frozen
        # "all clear" while the link is down (safety-honesty; final-fix).
        if self._availability_source == "cloud":
            return self._freshness_value() is not None
        return False
