"""Coordinator package — assembled DreameA2MowerCoordinator + helpers.

Decomposed from a single-file 4997-LOC ``coordinator.py`` 2026-05-15.
See spec ``docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md``
and plan ``docs/superpowers/plans/2026-05-15-coordinator-decomposition.md``.

External callers continue to use ``from .coordinator import …``; the
package re-exports the same public surface as the old module.

Post-P3.9 (refactor-v2) the coordinator is a thin **composition root + attr
hub + poll orchestrator**: the business LOGIC lives in the layer-4 ``domain/``
services, and every mixin below is a thin delegator preserving the public/test
surface. See CLAUDE.md § Coordinator structure + the target architecture doc
``docs/superpowers/specs/2026-07-02-refactor-v2-target-architecture.md`` §1.

Per-mixin file map (see CLAUDE.md § Coordinator structure for the full table):

- ``_core.py``           — composition root + ``__init__`` attr hub + transport
                           bootstrap (``_init_cloud`` / ``_init_mqtt``);
                           ``_async_update_data`` delegates to ``domain/boot.py``
- ``_property_apply.py`` — re-export shim → ``state/apply.py``
- ``_refreshers.py``     — thin delegators → domain/{gps,device_info,obstacles,
                           notifications} + the residual ``_refresh_mapl``
- ``_cloud_state.py``    — cloud_state apply + map fetch/persist
- ``_mqtt_handlers.py``  — thin delegators → domain/{ingress,session}
- ``_writes.py``         — thin delegators → domain/writes/
- ``_session.py``        — thin delegators → domain/session/
- ``_rendering.py``      — thin delegators → domain/render.py
- ``_lidar_oss.py``      — thin delegators → domain/{lidar,media,wifi}
- ``_device_sync.py``    — thin delegators → domain/{device_sync,faults}
- ``_wifi_archive.py``   — thin delegators → domain/wifi/service.py
- ``_notifications.py``  — thin delegators → domain/notifications.py
"""
from __future__ import annotations

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from ..mower.state import MowerState
from ._cloud_state import _CloudStateMixin
from ._core import _CoreMixin
from ._device_sync import _DeviceSyncMixin
from ._lidar_oss import _LidarOssMixin
from ._mqtt_handlers import _MqttHandlersMixin
from ._notifications import _NotificationsMixin
from ._property_apply import (
    _BLOB_SLOTS,
    _SUPPRESSED_SLOTS,
    S2P2_EVENT_TYPES,
    _project_north_east,
    apply_property_to_state,
)
from ._refreshers import _RefreshersMixin
from ._rendering import _RenderingMixin
from ._session import _SessionMixin
from ._wifi_archive import _WifiArchiveMixin
from ._writes import _WritesMixin


class DreameA2MowerCoordinator(
    _CoreMixin,
    _RefreshersMixin,
    _CloudStateMixin,
    _MqttHandlersMixin,
    _NotificationsMixin,
    _WritesMixin,
    _SessionMixin,
    _RenderingMixin,
    _LidarOssMixin,
    _DeviceSyncMixin,
    _WifiArchiveMixin,
    DataUpdateCoordinator[MowerState],
):
    """Coordinates MQTT + cloud clients and the typed MowerState.

    Per spec §3 layer 3. The class body is assembled from per-concern
    mixins (see module map above). Only ``_CoreMixin`` owns ``__init__``;
    every other mixin is a pure method container.
    """


__all__ = [
    "DreameA2MowerCoordinator",
    "apply_property_to_state",
    "_BLOB_SLOTS",
    "_SUPPRESSED_SLOTS",
    "S2P2_EVENT_TYPES",
    "_project_north_east",
]
