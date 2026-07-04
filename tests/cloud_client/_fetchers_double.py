"""Test-only composite of the six cloud-client fetch-family mixins.

Relocated here from the production ``cloud_client/_fetchers.py`` back-compat
shim, which was **retired in P3.10**. Production assembles the six family
mixins directly in ``cloud_client/__init__.py``; this composite exists ONLY so
fake-client tests can inherit / instantiate (no-arg) an object carrying every
fetch method. New tests should prefer the specific family mixin.
"""
from __future__ import annotations

from custom_components.dreame_a2_mower.cloud_client._state_fetch import _StateFetchMixin
from custom_components.dreame_a2_mower.cloud_client._device_fetch import _DeviceFetchMixin
from custom_components.dreame_a2_mower.cloud_client._messages import _MessagesMixin
from custom_components.dreame_a2_mower.cloud_client._media import _MediaMixin
from custom_components.dreame_a2_mower.cloud_client._ota import _OtaMixin
from custom_components.dreame_a2_mower.cloud_client._writers import _WritersMixin


class _FetchersMixin(
    _StateFetchMixin,
    _DeviceFetchMixin,
    _MessagesMixin,
    _MediaMixin,
    _OtaMixin,
    _WritersMixin,
):
    """Composed test double preserving the pre-split ``_FetchersMixin`` surface."""
