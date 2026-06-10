from custom_components.dreame_a2_mower.protocol import cfg_action


def test_get_pre_scoped_args_and_returns_array():
    arr = [0, 1, 0, 0, 60, 1, 8, 1, 0, 1, 1, 2, 1, 20, 10, 7, 1, 2, 0]
    captured = {}
    def fake_send(siid, aiid, params):
        captured["params"] = params
        return {"result": {"out": [{"m": "g", "t": "PRE", "d": arr}]}}
    out = cfg_action.get_pre(fake_send, idx=1, region=0)
    p = captured["params"][0]
    assert p == {"m": "g", "t": "PRE", "d": {"idx": 1, "region": 0}}
    assert out == arr
