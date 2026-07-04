"""Task 2 (P6.1b): setup-time cloud login failure surfaces ConfigEntryAuthFailed.

``_init_cloud`` (coordinator/_core.py) is the synchronous body run inside an
executor job by ``domain/boot.py:_restore_and_init_transports`` during the
first refresh. Before this change it called ``client.login()`` and ignored
the return value entirely — a genuinely-rejected credential set would fall
straight through to ``select_first_g2408``/``get_device_info`` and blow up
with an unrelated, confusing error (or silently proceed with no device
data). Now:

- ``last_login_failure == "auth"`` (cloud rejected the creds) → raise
  ``ConfigEntryAuthFailed`` so HA starts the reauth flow.
- ``last_login_failure == "transport"`` (network blip) → do NOT raise here;
  the existing downstream path still raises ``ConfigEntryNotReady`` once
  ``get_device_info``/``mqtt_host_port`` finds no host data.
"""
from __future__ import annotations

import pytest

from homeassistant.exceptions import ConfigEntryAuthFailed

from custom_components.dreame_a2_mower.coordinator import _core as _core_mod

from tests.factories import make_coordinator


class _FakeCloudClientBase:
    """Stand-in for DreameA2CloudClient — _init_cloud only touches these."""

    def __init__(self, *, username, password, country, did=None) -> None:
        self.username = username
        self.password = password
        self.country = country
        self._host = "mower.example.com:8883"

    def select_first_g2408(self) -> None:
        pass

    def get_device_info(self) -> None:
        pass

    def mqtt_host_port(self):
        return ("mower.example.com", 8883)

    @property
    def device_id(self):
        return "did-1"

    @property
    def model(self):
        return "dreame.mower.g2408"


def test_init_cloud_raises_config_entry_auth_failed_on_auth_rejection(monkeypatch):
    """login() -> False with last_login_failure == 'auth' must raise CEAF
    before select_first_g2408/get_device_info even run."""

    class _FakeClient(_FakeCloudClientBase):
        last_login_failure = "auth"

        def login(self) -> bool:
            return False

        def select_first_g2408(self):  # pragma: no cover - must not be reached
            raise AssertionError("select_first_g2408 must not run after an auth failure")

    monkeypatch.setattr(_core_mod, "DreameA2CloudClient", _FakeClient)
    coord = make_coordinator()

    with pytest.raises(ConfigEntryAuthFailed):
        coord._init_cloud()


def test_init_cloud_does_not_raise_ceaf_on_transport_failure(monkeypatch):
    """login() -> False with last_login_failure == 'transport' must NOT raise
    ConfigEntryAuthFailed — the existing downstream ConfigEntryNotReady path
    (via mqtt_host_port/get_device_info) is the correct surface for that."""

    calls: list[str] = []

    class _FakeClient(_FakeCloudClientBase):
        last_login_failure = "transport"

        def login(self) -> bool:
            return False

        def select_first_g2408(self):
            calls.append("select_first_g2408")

        def get_device_info(self):
            calls.append("get_device_info")

    monkeypatch.setattr(_core_mod, "DreameA2CloudClient", _FakeClient)
    coord = make_coordinator()

    coord._init_cloud()  # must not raise

    assert calls == ["select_first_g2408", "get_device_info"]


def test_init_cloud_does_not_raise_on_successful_login(monkeypatch):
    class _FakeClient(_FakeCloudClientBase):
        last_login_failure = None

        def login(self) -> bool:
            return True

    monkeypatch.setattr(_core_mod, "DreameA2CloudClient", _FakeClient)
    coord = make_coordinator()

    client = coord._init_cloud()  # must not raise
    assert isinstance(client, _FakeClient)
