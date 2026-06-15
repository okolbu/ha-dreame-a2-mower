from unittest.mock import MagicMock
from custom_components.dreame_a2_mower.cloud_client._fetchers import _FetchersMixin


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload
        self.text = "x"

    def json(self):
        return self._p


def _client(resp):
    c = _FetchersMixin.__new__(_FetchersMixin)
    c._ensure_strings = lambda: None
    c._key_expire = None
    c._strings = [""] * 60
    c.strings = [""] * 60
    c._session = MagicMock()
    c._session.get.return_value = resp
    c.get_api_url = lambda: "https://api"
    c.login = lambda: None
    return c


def test_fetch_message_record_returns_service_records():
    payload = {"data": {"serviceMsg": {"unread": 2, "msgRecord": [{"id": "1"}]},
                        "systemMsg": {"unread": 0}}}
    c = _client(_Resp(200, payload))
    out = c.fetch_message_record()
    assert out["service_unread"] == 2
    assert out["service_records"] == [{"id": "1"}]


def test_fetch_share_messages_returns_list():
    payload = {"code": 0, "data": {"content": [{"id": "s1"}]}}
    c = _client(_Resp(200, payload))
    out = c.fetch_share_messages(limit=50)
    assert out == [{"id": "s1"}]


def test_fetch_share_messages_none_on_http_error():
    c = _client(_Resp(500, {}))
    assert c.fetch_share_messages(limit=50) is None


def test_fetch_share_messages_none_on_error_code():
    # HTTP 200 but a non-zero API code → None (and a debug log), mirroring
    # fetch_device_messages.
    c = _client(_Resp(200, {"code": -1, "msg": "bad", "data": None}))
    assert c.fetch_share_messages(limit=50) is None
