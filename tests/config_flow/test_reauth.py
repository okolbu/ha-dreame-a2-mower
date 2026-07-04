"""Task 2 (P6.1b): reauth flow — the UI surface for a distinguishable auth failure.

Standard HA reauth pattern:

- ``async_step_reauth(entry_data)`` stashes the entry being reauthenticated
  (looked up via ``self.context["entry_id"]``) and forwards straight to
  ``async_step_reauth_confirm``.
- ``async_step_reauth_confirm`` shows a password-only form, validates the
  NEW password via the same ``_validate_login`` helper Task 1 added, and on
  success calls ``self.async_update_reload_and_abort(entry, data=...)`` to
  swap in the new password and reload the config entry. Bad creds map to
  ``errors["base"]`` exactly like the initial ``async_step_user`` flow.

As with ``test_validation.py``, the stubbed ``homeassistant`` package (see
``tests/conftest.py``) doesn't implement the real ConfigFlow reauth
machinery (``context``, ``hass.config_entries.async_get_entry``,
``async_update_reload_and_abort``), so this suite instantiates the bare
``DreameA2MowerConfigFlow()`` object directly and monkeypatches the handful
of instance attributes/methods the two steps touch — the same technique
``test_validation.py``'s form-level tests already use.
"""
from __future__ import annotations

from typing import Any

import pytest

from custom_components.dreame_a2_mower import config_flow
from custom_components.dreame_a2_mower.const import (
    CONF_COUNTRY,
    CONF_PASSWORD,
    CONF_USERNAME,
)


class _FakeEntry:
    """Minimal stand-in for the ConfigEntry being reauthenticated."""

    def __init__(self, *, entry_id: str, data: dict[str, Any]) -> None:
        self.entry_id = entry_id
        self.data = data


class _FakeConfigEntries:
    def __init__(self, entry: _FakeEntry) -> None:
        self._entry = entry

    def async_get_entry(self, entry_id: str):
        assert entry_id == self._entry.entry_id
        return self._entry


class _FakeHass:
    """Runs the executor job inline; exposes config_entries.async_get_entry."""

    def __init__(self, entry: _FakeEntry) -> None:
        self.config_entries = _FakeConfigEntries(entry)

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class _FakeClientBase:
    """Stand-in for DreameA2CloudClient — only ``login`` is exercised."""

    def __init__(self, *, username, password, country):
        self.username = username
        self.password = password
        self.country = country


def _entry_data() -> dict[str, Any]:
    return {
        CONF_USERNAME: "user@example.com",
        CONF_PASSWORD: "stale-password",
        CONF_COUNTRY: "eu",
    }


def _make_flow(entry: _FakeEntry, *, reload_calls: list) -> config_flow.DreameA2MowerConfigFlow:
    """Build a bare flow wired for the reauth steps, mirroring the
    test_validation.py ``_make_flow`` technique for async_step_user."""
    flow = config_flow.DreameA2MowerConfigFlow()
    flow.hass = _FakeHass(entry)  # type: ignore[attr-defined]
    flow.context = {"entry_id": entry.entry_id}  # type: ignore[attr-defined]

    def _update_reload_and_abort(entry_arg, *, data):
        reload_calls.append({"entry": entry_arg, "data": data})
        return {"type": "abort", "reason": "reauth_successful"}

    def _show_form(*, step_id, data_schema, errors=None):
        return {"type": "form", "step_id": step_id, "errors": errors or {}}

    flow.async_update_reload_and_abort = _update_reload_and_abort  # type: ignore[assignment]
    flow.async_show_form = _show_form  # type: ignore[assignment]
    return flow


async def test_async_step_reauth_stashes_entry_and_shows_confirm_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """async_step_reauth looks up the entry via context["entry_id"] and
    forwards to async_step_reauth_confirm (no password submitted yet)."""
    entry = _FakeEntry(entry_id="test-entry", data=_entry_data())
    flow = _make_flow(entry, reload_calls=[])

    result = await flow.async_step_reauth({})

    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"
    assert flow._reauth_entry is entry


async def test_reauth_confirm_success_updates_password_and_reloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid new password re-logs in, merges into entry.data, and calls
    async_update_reload_and_abort — the standard HA reauth completion."""

    class _FakeClient(_FakeClientBase):
        def login(self) -> bool:
            return True

    monkeypatch.setattr(config_flow, "DreameA2CloudClient", _FakeClient)

    entry = _FakeEntry(entry_id="test-entry", data=_entry_data())
    reload_calls: list = []
    flow = _make_flow(entry, reload_calls=reload_calls)
    await flow.async_step_reauth({})  # stashes _reauth_entry

    result = await flow.async_step_reauth_confirm({CONF_PASSWORD: "new-password"})

    assert result["type"] == "abort"
    assert len(reload_calls) == 1
    call = reload_calls[0]
    assert call["entry"] is entry
    # New password merged in; username/country carried over unchanged.
    assert call["data"][CONF_PASSWORD] == "new-password"
    assert call["data"][CONF_USERNAME] == entry.data[CONF_USERNAME]
    assert call["data"][CONF_COUNTRY] == entry.data[CONF_COUNTRY]


async def test_reauth_confirm_invalid_auth_stays_in_reauth_with_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bad new credentials re-show the reauth_confirm form with invalid_auth,
    and must NOT call async_update_reload_and_abort."""

    class _FakeClient(_FakeClientBase):
        def login(self) -> bool:
            return False

    monkeypatch.setattr(config_flow, "DreameA2CloudClient", _FakeClient)

    entry = _FakeEntry(entry_id="test-entry", data=_entry_data())
    reload_calls: list = []
    flow = _make_flow(entry, reload_calls=reload_calls)
    await flow.async_step_reauth({})

    result = await flow.async_step_reauth_confirm({CONF_PASSWORD: "still-wrong"})

    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"]["base"] == "invalid_auth"
    assert reload_calls == []


async def test_reauth_confirm_cannot_connect_stays_in_reauth_with_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transport failure during reauth re-shows the form with
    cannot_connect and does not abort/reload."""

    class _FakeClient(_FakeClientBase):
        def login(self) -> bool:
            raise TimeoutError("simulated transport failure")

    monkeypatch.setattr(config_flow, "DreameA2CloudClient", _FakeClient)

    entry = _FakeEntry(entry_id="test-entry", data=_entry_data())
    reload_calls: list = []
    flow = _make_flow(entry, reload_calls=reload_calls)
    await flow.async_step_reauth({})

    result = await flow.async_step_reauth_confirm({CONF_PASSWORD: "whatever"})

    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"]["base"] == "cannot_connect"
    assert reload_calls == []


async def test_reauth_confirm_no_input_shows_form(monkeypatch: pytest.MonkeyPatch) -> None:
    """Calling async_step_reauth_confirm with no user_input just (re)shows
    the form — the initial-display case, mirroring async_step_user."""
    entry = _FakeEntry(entry_id="test-entry", data=_entry_data())
    flow = _make_flow(entry, reload_calls=[])
    flow._reauth_entry = entry  # normally set by async_step_reauth

    result = await flow.async_step_reauth_confirm(None)

    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {}
