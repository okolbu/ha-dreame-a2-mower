"""Back-compat shim: ``_FetchersMixin`` composed from the P3.5 family split.

The single 1,278-LOC ``_FetchersMixin`` was split (P3.5 transport split,
autopsy #2) into per-family mixins:

- ``_state_fetch._StateFetchMixin``  — CFG/DEV/MIHIS/DOCK/NET/MAP/MAPL/PRE-read
  + ``fetch_full_cloud_state``
- ``_device_fetch._DeviceFetchMixin`` — GPS/REMOTE/4G/MPOS/AIOBS
- ``_messages._MessagesMixin``       — device/account/share message stores
- ``_media._MediaMixin``             — OSS media listing + quota
- ``_ota._OtaMixin``                 — OTA version check
- ``_writers._WritersMixin``         — set_cfg / set_pre / trigger_firmware_update

Production assembles the six directly in ``cloud_client/__init__.py``. This
module only re-exports a composed ``_FetchersMixin`` so the existing test
importers (``tests/cloud_client/…``, ``tests/integration/test_*fetchers*``,
``tests/integration/test_messages_refresh``) keep working unchanged. It is a
transitional shim, retired in P3.10 (import-path rewrite + contract-test
replacement) — new code imports the specific family mixin directly.
"""
from __future__ import annotations

from ._state_fetch import _StateFetchMixin
from ._device_fetch import _DeviceFetchMixin
from ._messages import _MessagesMixin
from ._media import _MediaMixin
from ._ota import _OtaMixin
from ._writers import _WritersMixin


class _FetchersMixin(
    _StateFetchMixin,
    _DeviceFetchMixin,
    _MessagesMixin,
    _MediaMixin,
    _OtaMixin,
    _WritersMixin,
):
    """Composed shim preserving the pre-split ``_FetchersMixin`` surface."""
