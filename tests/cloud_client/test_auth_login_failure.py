"""Task 2 (P6.1b): login() must distinguish auth-rejected vs transport failure.

``login()`` keeps its historic ``bool`` return (many callers rely on that),
but now also records *why* a ``False`` happened on a new, purely additive
``last_login_failure`` attribute/property:

- ``None``      — last login succeeded (or none attempted yet).
- ``"auth"``    — the cloud responded but rejected the credentials (a 200
  response with no access-token key, or a non-200 "Login failed" response
  that isn't the refresh-token-expired retry case).
- ``"transport"`` — a ``requests`` Timeout / RequestException / malformed
  response (ValueError) prevented reaching a clear auth verdict.

This is the "distinguishable auth error" the reauth design (Task 2) needs:
``coordinator/_core.py:_init_cloud`` raises ``ConfigEntryAuthFailed`` only
for ``"auth"``, and ``domain/mqtt_lifecycle.py`` only starts reauth for
``"auth"`` — a transient network blip must not trigger either.

Note: ``login()`` replaces ``self._session`` with a fresh
``requests.session()`` on every call (close-then-recreate), so a test can't
just monkeypatch ``client._session.post`` beforehand — it gets thrown away.
Instead we monkeypatch the shared ``requests.session`` constructor (via the
``_auth`` module's ``requests`` reference) to hand back a fake session
object whose ``.post`` we control.
"""
from __future__ import annotations

import json

import pytest
import requests

from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient
from custom_components.dreame_a2_mower.cloud_client import _auth as _auth_mod


class _FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


class _FakeSession:
    """Stand-in for ``requests.session()`` — only ``post``/``close`` used by login()."""

    def __init__(self, post_impl) -> None:
        self._post_impl = post_impl

    def post(self, *args, **kwargs):
        return self._post_impl(*args, **kwargs)

    def close(self) -> None:
        pass


def _client_with_post(monkeypatch: pytest.MonkeyPatch, post_impl) -> DreameA2CloudClient:
    client = DreameA2CloudClient(username="user@example.com", password="hunter2", country="eu")
    monkeypatch.setattr(_auth_mod.requests, "session", lambda: _FakeSession(post_impl))
    return client


def test_last_login_failure_is_none_before_any_login() -> None:
    client = DreameA2CloudClient(username="u", password="p", country="eu")
    assert client.last_login_failure is None


def test_login_success_sets_last_login_failure_none(monkeypatch: pytest.MonkeyPatch) -> None:
    ok_body = json.dumps(
        {
            "access_token": "tok",
            "refresh_token": "rtok",
            "expires_in": 3600,
            "uid": "1234",
            "region": "eu",
            "tenant_id": "000000",
        }
    )
    client = _client_with_post(monkeypatch, lambda *a, **kw: _FakeResponse(200, ok_body))

    assert client.login() is True
    assert client.last_login_failure is None


def test_login_200_without_token_sets_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cloud responds 200 but the body carries no access_token — rejected creds."""
    client = _client_with_post(monkeypatch, lambda *a, **kw: _FakeResponse(200, json.dumps({})))

    assert client.login() is False
    assert client.last_login_failure == "auth"


def test_login_401_sets_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 401 'Login failed' response (not the refresh-token-expired retry)
    is a genuine credentials-rejected outcome."""
    client = _client_with_post(monkeypatch, lambda *a, **kw: _FakeResponse(401, "not json {"))

    assert client.login() is False
    assert client.last_login_failure == "auth"


def test_login_403_sets_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 403 is likewise a credentials/authorization rejection."""
    client = _client_with_post(monkeypatch, lambda *a, **kw: _FakeResponse(403, "forbidden"))

    assert client.login() is False
    assert client.last_login_failure == "auth"


def test_login_500_sets_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 5xx is a transient server-side outage/maintenance window, NOT a
    credentials problem — it must classify as 'transport' so setup retries
    via ConfigEntryNotReady/backoff and the rc=5 path does NOT force a
    spurious reauth prompt (review finding, P6.1b)."""
    client = _client_with_post(monkeypatch, lambda *a, **kw: _FakeResponse(500, "internal server error"))

    assert client.login() is False
    assert client.last_login_failure == "transport"


def test_login_503_sets_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 503 (service unavailable / maintenance) is transient → 'transport'."""
    client = _client_with_post(monkeypatch, lambda *a, **kw: _FakeResponse(503, "service unavailable"))

    assert client.login() is False
    assert client.last_login_failure == "transport"


def test_login_timeout_sets_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a, **kw):
        raise requests.exceptions.Timeout("simulated timeout")

    client = _client_with_post(monkeypatch, _raise)

    assert client.login() is False
    assert client.last_login_failure == "transport"


def test_login_request_exception_sets_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a, **kw):
        raise requests.exceptions.ConnectionError("simulated connection error")

    client = _client_with_post(monkeypatch, _raise)

    assert client.login() is False
    assert client.last_login_failure == "transport"


def test_login_malformed_json_sets_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 200 response whose body isn't valid JSON raises ValueError inside
    ``json.loads`` — caught alongside RequestException, so it's 'transport'
    (garbled cloud response), not 'auth'."""
    client = _client_with_post(monkeypatch, lambda *a, **kw: _FakeResponse(200, "{not valid json"))

    assert client.login() is False
    assert client.last_login_failure == "transport"
