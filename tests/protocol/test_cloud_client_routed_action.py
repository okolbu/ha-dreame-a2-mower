"""Tests for cloud_client.routed_action's honest WriteResult parsing.

Mirrors test_cloud_client_set_cfg.py: routed_action now returns a
``WriteResult`` carrying the device's ``out[0].r`` verdict instead of the raw
dict/None. The four wire shapes:

- ``out[0].r == 0``           → delivered + accepted
- ``out[0].r != 0`` (e.g. -3) → delivered + NOT accepted (device rejected)
- action returns None         → NOT delivered (transport / 80001)
- delivered but ``out`` absent → delivered + accepted (no reject signal to read;
  do NOT fabricate a rejection — this DIFFERS from set_cfg by design)

It also pins the endpoint_log labels, including the new ``device_rejected``.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from custom_components.dreame_a2_mower.cloud_client import (
    DreameA2CloudClient,
    WriteResult,
)


def _make_client(action_response, *, last_error=None):
    """Build a minimal client stub with a mocked .action()."""
    client = DreameA2CloudClient.__new__(DreameA2CloudClient)
    client.endpoint_log = {}
    client._did = "did1"
    client._last_send_error_code = last_error
    client.action = MagicMock(return_value=action_response)
    return client


_OK = {"code": 0, "out": [{"r": 0}]}
_REJECTED = {"code": 0, "out": [{"r": -3, "msg": "not supported"}]}
_NO_OUT = {"code": 0}  # delivered, but no out[] to read


# --- WriteResult dataclass semantics --------------------------------------


def test_write_result_bool_is_accepted():
    assert bool(WriteResult(delivered=True, accepted=True, code=0)) is True
    assert bool(WriteResult(delivered=True, accepted=False, code=-3)) is False
    assert bool(WriteResult(delivered=False, accepted=False, code=80001)) is False


def test_write_result_ok_property_matches_accepted():
    assert WriteResult(delivered=True, accepted=True, code=0).ok is True
    assert WriteResult(delivered=True, accepted=False, code=-3).ok is False


def test_write_result_is_frozen():
    import dataclasses
    import pytest

    r = WriteResult(delivered=True, accepted=True, code=0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.accepted = False  # type: ignore[misc]


# --- routed_action parse ladder -------------------------------------------


def test_routed_action_accepted():
    """out[0].r == 0 → delivered + accepted, code 0."""
    client = _make_client(_OK)
    result = client.routed_action(op=100)
    assert isinstance(result, WriteResult)
    assert result.delivered is True
    assert result.accepted is True
    assert result.code == 0
    assert client.endpoint_log["routed_action_op=100"] == "accepted"


def test_routed_action_device_rejected():
    """out[0].r == -3 → delivered but NOT accepted; carries code + msg."""
    client = _make_client(_REJECTED)
    result = client.routed_action(op=102)
    assert result.delivered is True
    assert result.accepted is False
    assert result.code == -3
    assert result.msg == "not supported"
    assert client.endpoint_log["routed_action_op=102"] == "device_rejected"


def test_routed_action_not_delivered_80001():
    """action None + last_send_error_code 80001 → not delivered, code 80001."""

    def _fake_action(*_a, **_kw):
        client._last_send_error_code = 80001
        return None

    client = DreameA2CloudClient.__new__(DreameA2CloudClient)
    client.endpoint_log = {}
    client._did = "did1"
    client._last_send_error_code = None
    with patch.object(client, "action", side_effect=_fake_action):
        result = client.routed_action(op=999)
    assert result.delivered is False
    assert result.accepted is False
    assert result.code == 80001
    assert client.endpoint_log["routed_action_op=999"] == "rejected_80001"


def test_routed_action_not_delivered_other_error():
    """action None + a non-80001 error code → not delivered, error label."""

    def _fake_action(*_a, **_kw):
        client._last_send_error_code = -7
        return None

    client = DreameA2CloudClient.__new__(DreameA2CloudClient)
    client.endpoint_log = {}
    client._did = "did1"
    client._last_send_error_code = None
    with patch.object(client, "action", side_effect=_fake_action):
        result = client.routed_action(op=42)
    assert result.delivered is False
    assert result.accepted is False
    assert result.code == -7
    assert client.endpoint_log["routed_action_op=42"] == "error"


def test_routed_action_delivered_without_out_is_accepted():
    """Delivered envelope with no `out` → accepted=True, code=None.

    Differs from set_cfg (which treats malformed as failure): for actions a
    normal-looking envelope with no reject signal must NOT block the user, so we
    do NOT fabricate a rejection.
    """
    client = _make_client(_NO_OUT)
    result = client.routed_action(op=100)
    assert result.delivered is True
    assert result.accepted is True
    assert result.code is None
    assert client.endpoint_log["routed_action_op=100"] == "accepted"


def test_routed_action_delivered_empty_out_is_accepted():
    """`out: []` (empty list) is also 'no reject signal' → accepted."""
    client = _make_client({"code": 0, "out": []})
    result = client.routed_action(op=100)
    assert result.delivered is True
    assert result.accepted is True
    assert result.code is None
