"""mqtt_handlers mixin — extracted from coordinator.py 2026-05-15.

See spec docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md.

P3.7 (refactor-v2 ingress funnel): the MQTT routing, the ``_on_state_update``
lifecycle-edge detectors, and the session-type signal capture were moved
VERBATIM into the domain layer:

  - ``domain/ingress.py``                — MQTT routing + property-push dispatch
                                           (paho purity P2.9 preserved exactly).
  - ``domain/session/lifecycle_events.py`` — ``_on_state_update`` edge detectors.
  - ``domain/session/signals.py``        — session-type signal capture.

This mixin now holds only thin DELEGATORS that preserve the coordinator's public
and test surface (``coord._on_mqtt_message``, ``coord.handle_property_push``,
``coord._on_state_update``, the unbound ``_MqttHandlersMixin._on_state_update``,
``_mqtt_handlers.capture_session_type_signals`` as a module attribute, …), plus
the CFG write-key table. The FULL coordinator de-godding continues in P3.8/P3.9.
"""
from __future__ import annotations

from typing import Any

from ..state import MowerState
from ..domain import ingress as _ingress
from ..domain.session import lifecycle_events as _lifecycle_events
from ..domain.session import signals as _signals

# Session-type signal capture moved to the domain layer (P3.7). Re-exported
# here so the module attribute `_mqtt_handlers.capture_session_type_signals`
# (imported by tests as `MH.capture_session_type_signals`) still resolves.
from ..domain.session.signals import capture_session_type_signals

__all__ = ["_MqttHandlersMixin", "capture_session_type_signals"]


class _MqttHandlersMixin:
    """Thin delegators to the domain ingress/lifecycle/signals modules (P3.7)."""

    def _apply_mapl(self, mapl: Any) -> None:
        """Delegates to ``domain.ingress.apply_mapl`` (P3.7)."""
        _ingress.apply_mapl(self, mapl)

    def _on_mqtt_message(self, topic: str, payload: dict[str, Any]) -> None:
        """Delegates to ``domain.ingress.on_mqtt_message`` (P3.7)."""
        _ingress.on_mqtt_message(self, topic, payload)

    def handle_property_push(self, siid: int, piid: int, value: Any) -> None:
        """Delegates to ``domain.ingress.handle_property_push`` (P3.7).

        The paho-thread purity (P2.9) + the loop-side ``_deferred`` dispatch are
        preserved VERBATIM in the domain module.
        """
        _ingress.handle_property_push(self, siid, piid, value)

    async def _handle_event_occured(self, arguments: list[dict[str, Any]]) -> None:
        """Delegates to ``domain.ingress.handle_event_occured`` (P3.7)."""
        await _ingress.handle_event_occured(self, arguments)

    # -- session-type signals (domain/session/signals.py) -------------------

    def _latch_task_op(self, op: int) -> None:
        """Delegates to ``domain.session.signals.latch_task_op`` (P3.7)."""
        _signals.latch_task_op(self, op)

    def _handle_task_op_echo(self, value: Any) -> None:
        """Delegates to ``domain.session.signals.handle_task_op_echo`` (P3.7)."""
        _signals.handle_task_op_echo(self, value)

    def _seed_session_type_from_pending(self) -> None:
        """Delegates to ``domain.session.signals.seed_session_type_from_pending`` (P3.7)."""
        _signals.seed_session_type_from_pending(self)

    # -- lifecycle-edge detectors (domain/session/lifecycle_events.py) ------

    def _maybe_fire_charging_events(
        self, charging_status, now_unix: int, battery: int | None
    ) -> None:
        """Delegates to ``domain.session.lifecycle_events.maybe_fire_charging_events`` (P3.7)."""
        _lifecycle_events.maybe_fire_charging_events(
            self, charging_status, now_unix, battery
        )

    def _fire_rain_delay_started_if_edge(
        self, *, old: int | None, new: int | None, now_unix: int
    ) -> None:
        """Delegates to ``domain.session.lifecycle_events.fire_rain_delay_started_if_edge`` (P3.7)."""
        _lifecycle_events.fire_rain_delay_started_if_edge(
            self, old=old, new=new, now_unix=now_unix
        )

    def _fire_self_shutdown_if_edge(
        self, *, old: int | None, new: int | None, now_unix: int
    ) -> None:
        """Delegates to ``domain.session.lifecycle_events.fire_self_shutdown_if_edge`` (P3.7)."""
        _lifecycle_events.fire_self_shutdown_if_edge(
            self, old=old, new=new, now_unix=now_unix
        )

    def _capture_telemetry_sample(
        self, key: tuple[int, int], value: Any, now_unix: int
    ) -> None:
        """Delegates to ``domain.session.lifecycle_events.capture_telemetry_sample`` (P3.7)."""
        _lifecycle_events.capture_telemetry_sample(self, key, value, now_unix)

    def _on_state_update(self, new_state: MowerState, now_unix: int) -> MowerState:
        """Delegates to ``domain.session.lifecycle_events.on_state_update`` (P3.7).

        The 375-LOC edge-detector body was decomposed VERBATIM into named seam
        functions + an orchestrator in that module; this thin method preserves
        the public/test surface (``coord._on_state_update`` and the unbound
        ``_MqttHandlersMixin._on_state_update``).
        """
        return _lifecycle_events.on_state_update(self, new_state, now_unix)

    # -----------------------------------------------------------------------
    # Settings write surface (F4.5.1)
    # -----------------------------------------------------------------------

    #: CFG keys whose wire value is passed directly to set_cfg().
    #: All multi-field CFG keys (DND, LIT, BAT, WRP, LOW, ATA, REC) are
    #: also in this set — the entity layer builds the full array/dict value
    #: and passes it here; the coordinator relays verbatim.
    _CFG_SINGLE_KEYS: frozenset[str] = frozenset(
        {
            "CLS", "VOL", "LANG", "DND", "WRP", "LOW", "BAT", "LIT", "ATA", "REC",
            # AMBIGUOUS_TOGGLE single-int keys (a62 — toggle-confirmed 2026-04-30):
            "FDP", "STUN", "AOP", "PROT",
            # AMBIGUOUS_4LIST 4-bool keys (a62 — slot-confirmed 2026-04-30):
            "MSG_ALERT", "VOICE",
        }
    )
