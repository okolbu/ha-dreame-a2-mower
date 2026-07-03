"""Tests for cloud_client.set_cfg dict-vs-primitive payload routing.

The set_cfg method accepts both shapes:
- primitive (int/bool/list/str) → wrapped as ``{"value": <prim>}``
- dict → sent verbatim as the action's ``d`` payload (named-key format
  for complex CFG keys like WRP/DND/LOW/LIT)
"""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient


def _make_client(action_response):
    """Build a minimal DreameA2CloudClient stub with a mocked .action()."""
    client = object.__new__(DreameA2CloudClient)
    client.action = MagicMock(return_value=action_response)
    return client


_OK = {"code": 0, "out": [{"r": 0}]}
_REJECTED = {"code": 0, "out": [{"r": -3, "msg": "not supported"}]}


def test_set_cfg_primitive_wraps_as_value():
    """Primitive int → action gets {m:'s', t:KEY, d:{value: <int>}}."""
    client = _make_client(_OK)
    ok = client.set_cfg("VOL", 60)
    assert ok.accepted is True and ok.delivered is True and ok.code == 0
    client.action.assert_called_once()
    kwargs = client.action.call_args.kwargs
    params = kwargs.get("parameters") or client.action.call_args.args[0]
    payload = params[0]
    assert payload == {"m": "s", "t": "VOL", "d": {"value": 60}}


def test_set_cfg_bool_wraps_as_value():
    """Boolean True → wrapped as {value: True}."""
    client = _make_client(_OK)
    ok = client.set_cfg("CLS", True)
    assert ok.accepted is True
    payload = client.action.call_args.kwargs["parameters"][0]
    assert payload == {"m": "s", "t": "CLS", "d": {"value": True}}


def test_set_cfg_list_wraps_as_value():
    """A list payload (legacy callers) is also wrapped — back-compat."""
    client = _make_client(_OK)
    ok = client.set_cfg("ATA", [1, 0, 1])
    assert ok.accepted is True
    payload = client.action.call_args.kwargs["parameters"][0]
    assert payload == {"m": "s", "t": "ATA", "d": {"value": [1, 0, 1]}}


def test_set_cfg_dict_passes_through_verbatim():
    """A dict payload is sent as ``d`` directly (named-key format)."""
    client = _make_client(_OK)
    d_payload = {"value": 1, "time": 4}
    ok = client.set_cfg("WRP", d_payload)
    assert ok.accepted is True
    payload = client.action.call_args.kwargs["parameters"][0]
    assert payload == {"m": "s", "t": "WRP", "d": d_payload}


def test_set_cfg_dict_dnd_named_key_shape():
    """DND named-key wire format passes through."""
    client = _make_client(_OK)
    d_payload = {"value": 1, "time": [1200, 480]}
    ok = client.set_cfg("DND", d_payload)
    assert ok.accepted is True
    payload = client.action.call_args.kwargs["parameters"][0]
    assert payload["d"] == d_payload


def test_set_cfg_dict_lit_full_named_keys():
    """LIT 4-light + fill named-key wire format passes through."""
    client = _make_client(_OK)
    d_payload = {
        "value": 1,
        "time": [480, 1200],
        "light": [1, 1, 1, 1],
        "fill": 0,
    }
    ok = client.set_cfg("LIT", d_payload)
    assert ok.accepted is True
    payload = client.action.call_args.kwargs["parameters"][0]
    assert payload["d"] == d_payload


def test_set_cfg_rejection_carries_device_code():
    """out[0].r=-3 → delivered-but-rejected WriteResult carrying r + msg.

    r=-3 = "no setter for THIS key at THIS address" — see inventory.yaml
    § READ/WRITE SURFACES note 1 (routed-action write surface).
    """
    client = _make_client(_REJECTED)
    result = client.set_cfg("WRP", {"value": 1})
    assert bool(result) is False
    assert result.delivered is True
    assert result.accepted is False
    assert result.code == -3
    assert result.msg == "not supported"


def test_set_cfg_none_response_is_not_delivered():
    client = _make_client(None)
    result = client.set_cfg("VOL", 50)
    assert bool(result) is False
    assert result.delivered is False
    assert result.accepted is False
