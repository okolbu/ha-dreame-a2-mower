"""Tests for cloud_client.set_pre response parsing.

set_pre delegates to protocol.cfg_action.set_pre (which builds the
``{m:'s', t:'PRE', d:<bare array>}`` routed-action envelope) and then
inspects ``out[0].r`` — returning a WriteResult accepted only when the
device accepted the write (r=0), mirroring set_cfg (P2 Task 5). The HTTP-layer ``code`` is always 0 on a
reachable cloud even when the device rejects, so a shallow non-None check
would report false success.

Prior r=-3 results were a wrong-envelope artifact: the old code wrapped the
array as ``d:{"value": pre_array}`` which the device rejected with r=-3.
The app sends the bare array ``d:[...]`` and the device accepts it
(app MITM capture 2026-06-09).
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


def test_set_pre_accepted_on_r0():
    client = _make_client(_OK)
    result = client.set_pre(_PRE)
    assert result.accepted is True and result.delivered is True and result.code == 0
    # cfg_action.set_pre calls action(siid, aiid, [payload]) positionally.
    args = client.action.call_args.args
    payload = args[2][0]
    # d must be the bare array — NOT {"value": _PRE} (wrong-envelope, 2026-06-09 fix).
    assert payload == {"m": "s", "t": "PRE", "d": _PRE}


def test_set_pre_rejection_carries_device_code():
    """out[0].r=-3 → delivered-but-rejected WriteResult with code=-3."""
    client = _make_client(_REJECTED)
    result = client.set_pre(_PRE)
    assert bool(result) is False
    assert result.delivered is True and result.accepted is False
    assert result.code == -3 and result.msg == "not supported"


def test_set_pre_none_response_is_not_delivered():
    """80001 / send-timeout surfaces as action() == None → not delivered."""
    client = _make_client(None)
    result = client.set_pre(_PRE)
    assert bool(result) is False and result.delivered is False


def test_set_pre_malformed_out_is_falsy_not_delivered():
    result = _make_client({"code": 0, "out": []}).set_pre(_PRE)
    assert bool(result) is False and result.delivered is False


def test_set_pre_http_error_code_is_falsy():
    result = _make_client({"code": 5, "out": [{"r": 0}]}).set_pre(_PRE)
    assert bool(result) is False and result.code == 5
