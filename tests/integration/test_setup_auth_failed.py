"""Task 2 (P6.1b): ConfigEntryAuthFailed propagates cleanly out of boot.

The task brief's premise ("a rc=5 give-up path already surfaces
ConfigEntryAuthFailed") was wrong — neither ``cloud_client/_auth.py``'s
``login()`` nor ``domain/mqtt_lifecycle.py`` raised a distinguishable auth
error before this change. This suite closes the loop the brief asked us to
verify: once ``coordinator/_core.py:_init_cloud`` raises
``ConfigEntryAuthFailed`` on a genuine credential rejection, does it survive
un-caught all the way through:

    _init_cloud (executor job)
      -> domain/boot.py:_restore_and_init_transports
      -> domain/boot.py:async_first_refresh
      -> coordinator/_core.py:_CoreMixin._async_update_data (thin delegator)
      -> coordinator.async_config_entry_first_refresh (the stubbed
         DataUpdateCoordinator surface tests/conftest.py provides)

Neither ``domain/boot.py`` nor the stub's ``async_config_entry_first_refresh``
wrap exceptions from the update method (confirmed by reading both — no
try/except surrounds the relevant calls), so this is exercised for real
rather than asserted from a source read alone.

Also pins the no-partial-transport-leak property: because the auth check in
``_init_cloud`` runs BEFORE ``select_first_g2408``/``get_device_info``/MQTT
connect, an auth failure leaves neither ``_cloud`` nor ``_mqtt`` set on the
coordinator — nothing to disconnect, unlike the ConfigEntryNotReady path in
``__init__.py`` (which CAN be reached after a transport is already up, and
therefore needs its explicit teardown).
"""
from __future__ import annotations

import asyncio

import pytest

from homeassistant.exceptions import ConfigEntryAuthFailed

from custom_components.dreame_a2_mower.coordinator import _core as _core_mod

from tests.factories import make_coordinator


class _FakeAuthFailedClient:
    """Stand-in for DreameA2CloudClient — login() rejects credentials."""

    last_login_failure = "auth"

    def __init__(self, *, username, password, country, did=None) -> None:
        pass

    def login(self) -> bool:
        return False

    def select_first_g2408(self):  # pragma: no cover - must not be reached
        raise AssertionError("must not run after an auth failure")

    def get_device_info(self):  # pragma: no cover - must not be reached
        raise AssertionError("must not run after an auth failure")


def test_ceaf_propagates_through_async_first_refresh_and_update_data(monkeypatch):
    """The full boot chain (_init_cloud -> domain.boot.async_first_refresh ->
    _async_update_data) must raise ConfigEntryAuthFailed uncaught, and must
    leave neither _cloud nor _mqtt set (nothing to tear down)."""
    monkeypatch.setattr(_core_mod, "DreameA2CloudClient", _FakeAuthFailedClient)
    coord = make_coordinator()
    assert not hasattr(coord, "_cloud")

    with pytest.raises(ConfigEntryAuthFailed):
        asyncio.run(coord._async_update_data())

    assert not hasattr(coord, "_cloud")
    assert not hasattr(coord, "_mqtt")


def test_ceaf_propagates_through_stubbed_first_refresh(monkeypatch):
    """Drives the same failure through the (stubbed) DataUpdateCoordinator
    surface, ``async_config_entry_first_refresh`` — the method
    ``__init__.py:async_setup_entry`` actually awaits — to confirm HA's
    entry-setup machinery would see ConfigEntryAuthFailed, not something
    swallowed or rewrapped as ConfigEntryNotReady."""
    monkeypatch.setattr(_core_mod, "DreameA2CloudClient", _FakeAuthFailedClient)
    coord = make_coordinator()

    with pytest.raises(ConfigEntryAuthFailed):
        asyncio.run(coord.async_config_entry_first_refresh())
