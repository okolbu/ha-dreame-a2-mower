from custom_components.dreame_a2_mower.protocol.cfg_action import call_action_op


def test_call_action_op_default_p_zero_and_d_nesting():
    calls = []
    def send(siid, aiid, params):
        calls.append((siid, aiid, params))
        return {"result": {"out": [{"m": "a", "r": 0}]}}
    call_action_op(send, 219, {"region": 1, "name": "X"})
    assert calls[0][0] == 2 and calls[0][1] == 50
    assert calls[0][2] == [{"m": "a", "p": 0, "o": 219, "d": {"region": 1, "name": "X"}}]


def test_call_action_op_p_one_commit_no_extra():
    calls = []
    def send(siid, aiid, params):
        calls.append(params)
        return {"result": {"out": [{"m": "a", "r": 0}]}}
    call_action_op(send, 201, p=1)
    assert calls[0] == [{"m": "a", "p": 1, "o": 201}]
