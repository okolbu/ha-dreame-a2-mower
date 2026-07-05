"""Tests for Task 3 (P6.1c): g2408 model gate + single-device pin/warn.

After a successful login, ``async_step_user`` must discover the account's
devices via ``client.get_devices()`` and:

- Reject accounts with no ``dreame.mower.*`` device at all
  (``async_abort(reason="no_supported_device")``).
- Pin the first exact ``dreame.mower.g2408`` match when present.
- Warn (log) when multiple g2408s are present (single-device support) —
  still pin the first.
- Warn (log) when the only match is a non-g2408 ``dreame.mower.*`` model
  (R-44 model-unverified) — still pin it best-effort.
- Store the chosen device's ``did``/``sn``/``model`` in the created
  entry's ``data``.

Same harness technique as ``tests/config_flow/test_validation.py``: the
bare ``DreameA2MowerConfigFlow()`` is instantiated directly and its HA
plumbing methods are monkeypatched (no real HA / pytest-homeassistant-
custom-component available in this vanilla venv).
"""
from __future__ import annotations

import logging

import pytest

from custom_components.dreame_a2_mower import config_flow
from custom_components.dreame_a2_mower.const import (
    CONF_COUNTRY,
    CONF_PASSWORD,
    CONF_USERNAME,
    DEFAULT_MODEL,
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


def _fake_client(records: list[dict]):
    """Build a fake DreameA2CloudClient class: login()->True, get_devices()->records."""

    class _FakeClient:
        def __init__(self, *, username, password, country):
            self.username = username
            self.password = password
            self.country = country

        def login(self) -> bool:
            return True

        def get_devices(self):
            return {"page": {"records": records}}

    return _FakeClient


def _make_flow(created: dict, aborted: dict) -> config_flow.DreameA2MowerConfigFlow:
    """Build a flow wired with fakes for the HA plumbing async_step_user uses."""
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
        return {"type": "form", "step_id": step_id, "errors": errors}

    def _abort(*, reason):
        aborted["reason"] = reason
        return {"type": "abort", "reason": reason}

    flow.async_set_unique_id = _set_unique_id  # type: ignore[assignment]
    flow._abort_if_unique_id_configured = _abort_if_configured  # type: ignore[assignment]
    flow.async_create_entry = _create_entry  # type: ignore[assignment]
    flow.async_show_form = _show_form  # type: ignore[assignment]
    flow.async_abort = _abort  # type: ignore[assignment]
    return flow


async def test_single_g2408_pins_that_device(monkeypatch: pytest.MonkeyPatch) -> None:
    """Account with exactly one g2408 -> entry data carries its did/sn/model."""
    record = {"did": "did-1", "model": DEFAULT_MODEL, "sn": "SN001", "mac": "aa:bb"}
    monkeypatch.setattr(config_flow, "DreameA2CloudClient", _fake_client([record]))

    created: dict = {}
    aborted: dict = {}
    flow = _make_flow(created, aborted)

    result = await flow.async_step_user(_data())

    assert result["type"] == "create_entry"
    assert created["data"]["did"] == "did-1"
    assert created["data"]["sn"] == "SN001"
    assert created["data"]["model"] == DEFAULT_MODEL
    assert aborted == {}


async def test_no_mower_records_aborts_no_supported_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Account with zero dreame.mower.* records -> abort no_supported_device."""
    other_record = {"did": "did-x", "model": "dreame.vacuum.p2249", "sn": "SN999"}
    monkeypatch.setattr(config_flow, "DreameA2CloudClient", _fake_client([other_record]))

    created: dict = {}
    aborted: dict = {}
    flow = _make_flow(created, aborted)

    result = await flow.async_step_user(_data())

    assert result["type"] == "abort"
    assert result["reason"] == "no_supported_device"
    assert aborted["reason"] == "no_supported_device"
    assert created == {}


def _fake_client_raw(payload):
    """Fake client whose get_devices() returns an arbitrary (untrusted) payload."""

    class _FakeClient:
        def __init__(self, *, username, password, country):
            pass

        def login(self) -> bool:
            return True

        def get_devices(self):
            return payload

    return _FakeClient


@pytest.mark.parametrize("payload", [{"page": None}, {"page": "x"}, {"page": []}])
async def test_malformed_page_does_not_crash_aborts_no_supported_device(
    monkeypatch: pytest.MonkeyPatch, payload: dict
) -> None:
    """A malformed cloud response where ``page`` is present but not a dict
    (``{"page": null}`` / ``{"page": "x"}``) must NOT raise AttributeError out of
    async_step_user (it runs OUTSIDE _validate_login's try/except) — it is
    treated as no devices → no_supported_device abort."""
    monkeypatch.setattr(config_flow, "DreameA2CloudClient", _fake_client_raw(payload))

    created: dict = {}
    aborted: dict = {}
    flow = _make_flow(created, aborted)

    result = await flow.async_step_user(_data())

    assert result["type"] == "abort"
    assert result["reason"] == "no_supported_device"
    assert created == {}


async def test_multiple_g2408_pins_first_and_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Two g2408 records -> first is pinned; a warning is logged."""
    rec_a = {"did": "did-a", "model": DEFAULT_MODEL, "sn": "SN-A"}
    rec_b = {"did": "did-b", "model": DEFAULT_MODEL, "sn": "SN-B"}
    monkeypatch.setattr(config_flow, "DreameA2CloudClient", _fake_client([rec_a, rec_b]))

    created: dict = {}
    aborted: dict = {}
    flow = _make_flow(created, aborted)

    with caplog.at_level(logging.WARNING, logger=config_flow._LOGGER.name):
        result = await flow.async_step_user(_data())

    assert result["type"] == "create_entry"
    assert created["data"]["did"] == "did-a"
    assert any(
        "multiple" in r.message.lower() or "single-device" in r.message.lower()
        for r in caplog.records
    )


async def test_non_g2408_mower_model_pins_and_warns_unverified(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A dreame.mower.* record that isn't the verified g2408 is pinned best-effort with a warning."""
    record = {"did": "did-z", "model": "dreame.mower.zzzz", "sn": "SN-Z"}
    monkeypatch.setattr(config_flow, "DreameA2CloudClient", _fake_client([record]))

    created: dict = {}
    aborted: dict = {}
    flow = _make_flow(created, aborted)

    with caplog.at_level(logging.WARNING, logger=config_flow._LOGGER.name):
        result = await flow.async_step_user(_data())

    assert result["type"] == "create_entry"
    assert created["data"]["did"] == "did-z"
    assert created["data"]["model"] == "dreame.mower.zzzz"
    assert any(
        "unverified" in r.message.lower() or "model" in r.message.lower()
        for r in caplog.records
    )
