from custom_components.dreame_a2_mower.protocol import cfg_action


def test_set_pre_emits_bare_array():
    captured = {}
    def fake_send(siid, aiid, params):
        captured["siid"] = siid; captured["aiid"] = aiid; captured["params"] = params
        return {"result": {"out": [{"m": "r", "r": 0}]}}
    arr = [0, 1, 0, 0, 60, 1, 8, 1, 0, 1, 1, 2, 1, 20, 10, 7, 1, 2, 0]
    cfg_action.set_pre(fake_send, arr)
    payload = captured["params"][0]
    assert payload["m"] == "s" and payload["t"] == "PRE"
    assert payload["d"] == arr            # BARE array
    assert not isinstance(payload["d"], dict)
