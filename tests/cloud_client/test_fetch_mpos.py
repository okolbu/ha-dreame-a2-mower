from tests.cloud_client._fetchers_double import _FetchersMixin


class _FakeClient(_FetchersMixin):
    """Minimal stub — fetch_mpos only uses self.action."""
    def __init__(self, resp=None, exc=None):
        self._resp = resp
        self._exc = exc
    def action(self, siid, aiid, parameters=None, retry_count=2):
        assert siid == 2 and aiid == 50
        assert parameters == [{"m": "g", "t": "MPOS", "d": None}]
        if self._exc:
            raise self._exc
        return self._resp


def _ok(d):
    return {"siid": 2, "aiid": 50, "code": 0, "out": [{"m": "r", "r": 0, "d": d}]}


def test_fetch_mpos_ok():
    c = _FakeClient(_ok({"x": 95, "y": -4, "yaw": 0}))
    assert c.fetch_mpos() == {"result": "ok", "x": 95, "y": -4, "yaw": 0}


def test_fetch_mpos_idle_r_negative():
    c = _FakeClient({"out": [{"m": "r", "r": -3}]})
    assert c.fetch_mpos() == {"result": "idle"}
    c2 = _FakeClient({"out": [{"m": "r", "r": -1}]})
    assert c2.fetch_mpos() == {"result": "idle"}


def test_fetch_mpos_malformed_is_error():
    assert _FakeClient({"out": [{"m": "r", "r": 0, "d": {"x": 1}}]}).fetch_mpos() == {"result": "error"}
    assert _FakeClient({"out": []}).fetch_mpos() == {"result": "error"}
    assert _FakeClient("not-a-dict").fetch_mpos() == {"result": "error"}


def test_fetch_mpos_exception_is_error():
    assert _FakeClient(exc=RuntimeError("boom")).fetch_mpos() == {"result": "error"}
