"""Tests for P6.1a credential validation on config-flow setup.

The stubbed ``homeassistant`` package used by the vanilla test venv (see
``tests/conftest.py``) does not implement ``async_set_unique_id`` /
``_abort_if_unique_id_configured`` / ``async_create_entry`` /
``async_show_form`` on its ``ConfigFlow`` stub, so this suite tests the
EXTRACTED ``_validate_login`` helper directly with a tiny fake ``hass``
(mirrors the pattern in ``tests/config/test_options_flow_messages_keep.py``)
rather than driving the full flow.
"""
from __future__ import annotations

import pytest

from custom_components.dreame_a2_mower import config_flow
from custom_components.dreame_a2_mower.const import (
    CONF_COUNTRY,
    CONF_PASSWORD,
    CONF_USERNAME,
)


class _FakeHass:
    """Minimal hass stub: runs the executor job inline (still awaited)."""

    async def async_add_executor_job(self, func, *args):
        return func(*args)


def _data() -> dict:
    return {
        CONF_USERNAME: "user@example.com",
        CONF_PASSWORD: "hunter2",
        CONF_COUNTRY: "eu",
    }


class _FakeClientBase:
    """Stand-in for DreameA2CloudClient — only ``login`` is exercised."""

    def __init__(self, *, username, password, country):
        self.username = username
        self.password = password
        self.country = country


async def test_validate_login_raises_cannot_connect_on_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transport-layer exception from login() maps to CannotConnect."""

    class _FakeClient(_FakeClientBase):
        def login(self) -> bool:
            raise TimeoutError("simulated transport failure")

    monkeypatch.setattr(config_flow, "DreameA2CloudClient", _FakeClient)

    with pytest.raises(config_flow.CannotConnect):
        await config_flow._validate_login(_FakeHass(), _data())


async def test_validate_login_raises_invalid_auth_on_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """login() returning False (bad creds) maps to InvalidAuth."""

    class _FakeClient(_FakeClientBase):
        def login(self) -> bool:
            return False

    monkeypatch.setattr(config_flow, "DreameA2CloudClient", _FakeClient)

    with pytest.raises(config_flow.InvalidAuth):
        await config_flow._validate_login(_FakeHass(), _data())


async def test_validate_login_succeeds_on_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """login() returning True raises nothing — the happy path."""

    class _FakeClient(_FakeClientBase):
        def login(self) -> bool:
            return True

    monkeypatch.setattr(config_flow, "DreameA2CloudClient", _FakeClient)

    # Must not raise.
    await config_flow._validate_login(_FakeHass(), _data())
