"""device_sync mixin — thin delegators (refactor-v2 P3.9d).

The map sub-device registry sync + lifecycle-event emission LOGIC moved
VERBATIM to the ``domain/`` layer:

- ``domain/device_sync.py`` — target-area computation, device-registry serial
  sync, map sub-device sync, debounced cloud-refresh tripwire, event-entity
  wiring + the ``_fire_*`` lifecycle emitters (mowing_ended / notification /
  lifecycle / local-novel-s2p2).
- ``domain/faults.py`` — the fault EMISSION glue: fault-delta lifecycle events
  + error-tier persistent notices + the emergency-stop PIN banner.

Each domain function takes the coordinator (``coord``) as its first argument;
this mixin keeps thin delegating methods so the public/test surface
(``coord.register_event_entities``, ``coord._fire_mowing_ended``, all the
unbound ``_DeviceSyncMixin._X`` methods that ``test_fault_events`` binds via
``types.MethodType(_DeviceSyncMixin._fire_fault_delta, coord)``, and the
``_EMERGENCY_STOP_CODE`` class attr) is unchanged.

See spec docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md
(original decomposition) + the refactor-v2 P3 plan.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..domain import device_sync as _sync
from ..domain import faults as _faults
from ..state import MowerState

if TYPE_CHECKING:
    pass  # cross-mixin type imports added as needed


class _DeviceSyncMixin:
    """Thin delegators to ``domain.{device_sync,faults}`` (P3.9d) — see module docstring."""

    # ------------------------------------------------------------------
    # device_sync service (P3.9d) — domain/device_sync.py
    # ------------------------------------------------------------------

    def _compute_target_area_m2(self, state: MowerState) -> float | None:
        """Delegates to ``domain.device_sync.compute_target_area_m2`` (P3.9d)."""
        return _sync.compute_target_area_m2(self, state)

    def _update_device_registry_serial(self, serial: str) -> None:
        """Delegates to ``domain.device_sync.update_device_registry_serial`` (P3.9d)."""
        _sync.update_device_registry_serial(self, serial)

    def _get_device_registry(self) -> object | None:
        """Delegates to ``domain.device_sync.get_device_registry`` (P3.9d)."""
        return _sync.get_device_registry(self)

    def _sync_map_subdevices(self) -> None:
        """Delegates to ``domain.device_sync.sync_map_subdevices`` (P3.9d)."""
        _sync.sync_map_subdevices(self)

    def _schedule_cloud_refresh(
        self, *, delay_sec: float = 5.0, reason: str = "tripwire",
    ) -> None:
        """Delegates to ``domain.device_sync.schedule_cloud_refresh`` (P3.9d)."""
        _sync.schedule_cloud_refresh(self, delay_sec=delay_sec, reason=reason)

    def register_event_entities(self, *, lifecycle: Any, notification: Any) -> None:
        """Delegates to ``domain.device_sync.register_event_entities`` (P3.9d)."""
        _sync.register_event_entities(self, lifecycle=lifecycle, notification=notification)

    def _fire_lifecycle(
        self, event_type: str, event_data: dict[str, Any] | None = None
    ) -> None:
        """Delegates to ``domain.device_sync.fire_lifecycle`` (P3.9d)."""
        _sync.fire_lifecycle(self, event_type, event_data)

    def _fire_local_novel_s2p2(self, *, code: int, now_unix: int) -> None:
        """Delegates to ``domain.device_sync.fire_local_novel_s2p2`` (P3.9d)."""
        _sync.fire_local_novel_s2p2(self, code=code, now_unix=now_unix)

    def _fire_mowing_ended(
        self,
        now_unix: int,
        area_mowed_m2: float | None,
        duration_min: int | None,
        completed: bool,
    ) -> None:
        """Delegates to ``domain.device_sync.fire_mowing_ended`` (P3.9d)."""
        _sync.fire_mowing_ended(self, now_unix, area_mowed_m2, duration_min, completed)

    def _fire_notification(
        self,
        *,
        event_type: str,
        text: str,
        code: int,
        siid: int = 2,
        piid: int = 2,
        send_time: str | None = None,
        message_id: str | None = None,
        now_unix: int = 0,
    ) -> None:
        """Delegates to ``domain.device_sync.fire_notification`` (P3.9d)."""
        _sync.fire_notification(
            self, event_type=event_type, text=text, code=code, siid=siid,
            piid=piid, send_time=send_time, message_id=message_id, now_unix=now_unix,
        )

    # ------------------------------------------------------------------
    # faults service (P3.9d) — domain/faults.py
    # ------------------------------------------------------------------

    # Codes the generic fault-notice path must NOT touch: emergency-stop (23)
    # has its own PIN-entry persistent notice. Kept as a class attr here (single
    # source in domain/faults.py) so the established `coord._EMERGENCY_STOP_CODE`
    # surface resolves.
    _EMERGENCY_STOP_CODE = _faults._EMERGENCY_STOP_CODE

    def _handle_emergency_stop_transition(
        self, prev: bool | None, new: bool | None,
    ) -> None:
        """Delegates to ``domain.faults.handle_emergency_stop_transition`` (P3.9d)."""
        _faults.handle_emergency_stop_transition(self, prev, new)

    def _fault_notification_id(self, code: int) -> str:
        """Delegates to ``domain.faults.fault_notification_id`` (P3.9d)."""
        return _faults.fault_notification_id(self, code)

    def _post_fault_notice(self, code: int, lang: str) -> None:
        """Delegates to ``domain.faults.post_fault_notice`` (P3.9d)."""
        _faults.post_fault_notice(self, code, lang)

    def _dismiss_fault_notice(self, code: int) -> None:
        """Delegates to ``domain.faults.dismiss_fault_notice`` (P3.9d)."""
        _faults.dismiss_fault_notice(self, code)

    def _repost_active_fault_notices(self) -> None:
        """Delegates to ``domain.faults.repost_active_fault_notices`` (P3.9d)."""
        _faults.repost_active_fault_notices(self)

    def _fire_fault_delta(
        self, prev_errors, new_errors, *, now_unix: int
    ) -> None:
        """Delegates to ``domain.faults.fire_fault_delta`` (P3.9d)."""
        _faults.fire_fault_delta(self, prev_errors, new_errors, now_unix=now_unix)
