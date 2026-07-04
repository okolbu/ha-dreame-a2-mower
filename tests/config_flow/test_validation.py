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
    """login() returning False (bad creds) maps to InvalidAuth.

    ``_FakeClient`` here carries no ``last_login_failure`` attribute at all
    (it's not the real ``DreameA2CloudClient``) — the refined
    ``_validate_login`` must default an absent/non-"transport" value to
    InvalidAuth (Task 2 / P6.1b), not blow up on the missing attribute.
    """

    class _FakeClient(_FakeClientBase):
        def login(self) -> bool:
            return False

    monkeypatch.setattr(config_flow, "DreameA2CloudClient", _FakeClient)

    with pytest.raises(config_flow.InvalidAuth):
        await config_flow._validate_login(_FakeHass(), _data())


async def test_validate_login_false_with_transport_marker_raises_cannot_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task 2 (P6.1b): login() -> False AND last_login_failure == 'transport'
    now maps to CannotConnect, not InvalidAuth — closing the Task 1 nuance
    where a network blip was indistinguishable from bad credentials."""

    class _FakeClient(_FakeClientBase):
        last_login_failure = "transport"

        def login(self) -> bool:
            return False

    monkeypatch.setattr(config_flow, "DreameA2CloudClient", _FakeClient)

    with pytest.raises(config_flow.CannotConnect):
        await config_flow._validate_login(_FakeHass(), _data())


async def test_validate_login_false_with_auth_marker_raises_invalid_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """login() -> False AND last_login_failure == 'auth' maps to InvalidAuth."""

    class _FakeClient(_FakeClientBase):
        last_login_failure = "auth"

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


# ---------------------------------------------------------------------------
# Form-level tests: drive async_step_user end-to-end and assert the
# errors["base"] mapping / entry creation.
#
# The reviewer confirmed DreameA2MowerConfigFlow() is a bare Python object
# (no __slots__), so it can be instantiated directly and have its
# instance attributes/methods monkeypatched WITHOUT touching conftest.
# ---------------------------------------------------------------------------
def _make_flow(login_impl, created: dict) -> config_flow.DreameA2MowerConfigFlow:
    """Build a flow wired with fakes for the HA plumbing async_step_user uses.

    ``login_impl`` is bound as ``DreameA2CloudClient.login`` for the case;
    ``created`` captures the ``async_create_entry`` kwargs on success.
    """
    flow = config_flow.DreameA2MowerConfigFlow()
    flow.hass = _FakeHass()  # type: ignore[attr-defined]

    async def _set_unique_id(unique_id):  # async no-op
        return None

    def _abort_if_configured():  # no-op
        return None

    def _create_entry(*, title, data):
        created["title"] = title
        created["data"] = data
        return {"type": "create_entry", "title": title, "data": data}

    def _show_form(*, step_id, data_schema, errors):
        # Mirror HA: re-shows the form carrying the errors dict.
        return {"type": "form", "step_id": step_id, "errors": errors}

    flow.async_set_unique_id = _set_unique_id  # type: ignore[assignment]
    flow._abort_if_unique_id_configured = _abort_if_configured  # type: ignore[assignment]
    flow.async_create_entry = _create_entry  # type: ignore[assignment]
    flow.async_show_form = _show_form  # type: ignore[assignment]
    return flow


async def test_step_user_invalid_auth_surfaces_form_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """login()->False re-shows the form with errors[base]==invalid_auth; no entry."""

    class _FakeClient(_FakeClientBase):
        def login(self) -> bool:
            return False

    monkeypatch.setattr(config_flow, "DreameA2CloudClient", _FakeClient)

    created: dict = {}
    flow = _make_flow(None, created)

    result = await flow.async_step_user(_data())

    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_auth"
    assert created == {}  # no entry created on failure


async def test_step_user_cannot_connect_surfaces_form_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """login() raising a transport error re-shows form with errors[base]==cannot_connect."""

    class _FakeClient(_FakeClientBase):
        def login(self) -> bool:
            raise TimeoutError("simulated transport failure")

    monkeypatch.setattr(config_flow, "DreameA2CloudClient", _FakeClient)

    created: dict = {}
    flow = _make_flow(None, created)

    result = await flow.async_step_user(_data())

    assert result["type"] == "form"
    assert result["errors"]["base"] == "cannot_connect"
    assert created == {}


async def test_step_user_success_creates_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """login()->True creates the config entry with the submitted title/data."""
    from custom_components.dreame_a2_mower.const import DEFAULT_NAME

    class _FakeClient(_FakeClientBase):
        def login(self) -> bool:
            return True

    monkeypatch.setattr(config_flow, "DreameA2CloudClient", _FakeClient)

    created: dict = {}
    flow = _make_flow(None, created)

    data = _data()
    result = await flow.async_step_user(data)

    assert result["type"] == "create_entry"
    assert created["title"] == DEFAULT_NAME
    assert created["data"] == data
