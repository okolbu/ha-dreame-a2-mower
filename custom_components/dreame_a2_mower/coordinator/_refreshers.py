"""refreshers mixin — thin delegators + the residual MAPL poll (refactor-v2 P3.9e).

The per-domain cloud-poll SLICES moved VERBATIM to the ``domain/`` layer, each
taking the coordinator (``coord``) as its first argument; this mixin keeps thin
delegating methods so the public/test surface (``coord._refresh_dock`` /
``._refresh_net`` / ``._refresh_remote`` / ``._refresh_dev`` / ``._refresh_mpos``
/ ``._refresh_gps`` / ``._refresh_messages`` / ``._refresh_aiobs`` /
``._fetch_pending_obstacle_photos`` / ``._refresh_mapl``, the unbound
``_RefreshersMixin._X`` methods bound by ``test_phase_c_refreshers`` /
``test_aiobs_*`` / ``test_messages_refresh``, and the
``coordinator._refreshers.apply_mpos_result`` re-export) is unchanged. The poll
ORCHESTRATION (cadence → slice) lives in ``domain/boot.py`` (the composition
root's poll orchestrator, P3.9e).

Domain homes (P3.9d + P3.9e):
- ``domain/gps.py``          — ``refresh_gps`` (9d)
- ``domain/device_info.py``  — ``refresh_dock`` / ``refresh_net`` / ``refresh_remote``
                               / ``refresh_dev`` / ``refresh_mpos`` + ``apply_mpos_result``
- ``domain/obstacles.py``    — ``refresh_aiobs`` + ``fetch_pending_obstacle_photos``
- ``domain/notifications.py``— ``refresh_messages``

``_refresh_mapl`` stays a REAL impl here (DEFERRED): it is map-poll glue whose
only body is a ``coord._apply_mapl`` call (the apply lives in ``domain/ingress``),
with no single owning domain service; moving it would need a map/apply service
that 9e does not carve. See the P3.9e report.

See docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md and
the refactor-v2 P3 plan.
"""
from __future__ import annotations

from ..const import LOGGER
from ..domain import device_info as _device_info
from ..domain import gps as _gps
from ..domain import notifications as _notif
from ..domain import obstacles as _obstacles

# Back-compat re-export — tests import this pure helper from its old
# ``coordinator._refreshers`` home (test_apply_mpos_result).
apply_mpos_result = _device_info.apply_mpos_result


class _RefreshersMixin:
    """Thin delegators to the per-domain refresh services (P3.9e) + the
    residual MAPL poll — see module docstring."""

    async def _refresh_mapl(self) -> None:
        """Re-poll MAPL only (no full CFG refresh).

        Residual poll glue kept here (P3.9e): its sole action is applying the
        MAPL response via ``self._apply_mapl`` (``domain/ingress``); no single
        domain service owns it, so it stays on the coordinator poll surface.
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            return
        try:
            mapl_resp = await self.hass.async_add_executor_job(
                self._cloud.fetch_mapl
            )
        except Exception as ex:
            LOGGER.debug("[map] _refresh_mapl raised: %s", ex)
            return
        if isinstance(mapl_resp, dict):
            inner = (mapl_resp.get("ok") or {}).get("d") or mapl_resp.get("ok") or mapl_resp
            self._apply_mapl(inner if isinstance(inner, list) else None)
        elif isinstance(mapl_resp, list):
            # fetch_mapl can return a bare list per Task 7 implementation.
            self._apply_mapl(mapl_resp)

    async def _refresh_dock(self) -> None:
        """Delegates to ``domain.device_info.refresh_dock`` (P3.9e)."""
        await _device_info.refresh_dock(self)

    async def _refresh_net(self) -> None:
        """Delegates to ``domain.device_info.refresh_net`` (P3.9e)."""
        await _device_info.refresh_net(self)

    async def _refresh_gps(self) -> None:
        """Delegates to ``domain.gps.refresh_gps`` (P3.9d)."""
        await _gps.refresh_gps(self)

    async def _refresh_remote(self) -> None:
        """Delegates to ``domain.device_info.refresh_remote`` (P3.9e)."""
        await _device_info.refresh_remote(self)

    async def _refresh_mpos(self) -> None:
        """Delegates to ``domain.device_info.refresh_mpos`` (P3.9e)."""
        await _device_info.refresh_mpos(self)

    async def _refresh_messages(self) -> None:
        """Delegates to ``domain.notifications.refresh_messages`` (P3.9e)."""
        await _notif.refresh_messages(self)

    async def _refresh_dev(self) -> None:
        """Delegates to ``domain.device_info.refresh_dev`` (P3.9e)."""
        await _device_info.refresh_dev(self)

    async def _refresh_aiobs(self) -> None:
        """Delegates to ``domain.obstacles.refresh_aiobs`` (P3.9e)."""
        await _obstacles.refresh_aiobs(self)

    async def _fetch_pending_obstacle_photos(self) -> None:
        """Delegates to ``domain.obstacles.fetch_pending_obstacle_photos`` (P3.9e)."""
        await _obstacles.fetch_pending_obstacle_photos(self)

    # _poll_slow_properties REMOVED 2026-05-26.
    # It only fetched s6.3 ([cloud_connected, rssi_dbm]) and s1.5 (serial) via
    # the relay get_properties path, which 80001s when the device is asleep
    # (113 hourly :01 failures in production). Both targets are now redundant:
    #   • wifi_rssi_dbm comes from heartbeat byte[17] (~20 s cadence) directly.
    #   • cloud_connected is implied by MQTT being up (see coordinator
    #     `last_mqtt_unix` + binary_sensor.cloud_connected).
    #   • serial is provided by DEV (CFG.DEV.sn), which the integration's own
    #     comments flagged as authoritative.
    # See docs/research/app-api-surface-2026-05-25.md § 80001 for the full
    # write-up; nothing else called this method.
