"""Tests for cloud_client.set_pre response parsing.

set_pre delegates to protocol.cfg_action.set_pre (which builds the
``{m:'s', t:'PRE', d:{value: <array>}}`` routed-action envelope) and then
inspects ``out[0].r`` — returning True only when the device accepted the
write (r=0), mirroring set_cfg. The HTTP-layer ``code`` is always 0 on a
reachable cloud even when the device rejects, so a shallow non-None check
would report false success.

Known g2408 reality (fw 4.3.6_0550): ``t='PRE'`` has no routed-action setter,
so every PRE write returns ``out[0].r=-3`` — see
docs/research/wire-captures/pre-write-r3-2026-06-03.md. The reject test below
pins that this surfaces as False rather than a false success.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient


def _make_client(action_response):
    """Minimal client stub with a mocked .action() (set_pre calls self.action)."""
    client = object.__new__(DreameA2CloudClient)
    client.action = MagicMock(return_value=action_response)
    return client


# cfg_action.set_pre requires >= 10 elements; pad the g2408 [zone_id, mode]
# with the integration's defaults so we exercise the wire layer.
_PRE = [0, 1, 60, 0, 0, 0, 0, 0, 0, 0]

_OK = {"code": 0, "out": [{"r": 0}]}
_REJECTED = {"code": 0, "out": [{"r": -3, "msg": "not supported"}]}


def test_set_pre_returns_true_on_r0():
    client = _make_client(_OK)
    assert client.set_pre(_PRE) is True
    # cfg_action.set_pre calls action(siid, aiid, [payload]) positionally.
    args = client.action.call_args.args
    payload = args[2][0]
    assert payload == {"m": "s", "t": "PRE", "d": {"value": _PRE}}


def test_set_pre_returns_false_when_device_rejects():
    """out[0].r=-3 (the live g2408 verdict) → set_pre returns False."""
    client = _make_client(_REJECTED)
    assert client.set_pre(_PRE) is False


def test_set_pre_returns_false_when_action_returns_none():
    """80001 / send-timeout surfaces as action() == None → False."""
    client = _make_client(None)
    assert client.set_pre(_PRE) is False


def test_set_pre_returns_false_on_malformed_out():
    client = _make_client({"code": 0, "out": []})
    assert client.set_pre(_PRE) is False


def test_set_pre_returns_false_on_http_error_code():
    client = _make_client({"code": 5, "out": [{"r": 0}]})
    assert client.set_pre(_PRE) is False
