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


# ---------------------------------------------------------------------------
# _RefreshersMixin._refresh_messages — normalize + trim integration test
# ---------------------------------------------------------------------------

import dataclasses
import pytest
from custom_components.dreame_a2_mower.coordinator._refreshers import _RefreshersMixin
from custom_components.dreame_a2_mower.state import MowerState


@pytest.mark.asyncio
async def test_refresh_messages_normalizes_and_trims():
    coord = _RefreshersMixin.__new__(_RefreshersMixin)
    coord.data = MowerState()
    # self.entry is the real config-entry attribute (assigned in _core.py line 116)
    coord.entry = type("E", (), {"options": {"messages_keep": 2}})()
    # 5 service records — should be trimmed to cap=2, newest first
    svc = [
        {
            "id": str(i),
            "createTime": i,
            "multiLangDisplay": '{"en":{"name":"m%d"}}' % i,
        }
        for i in range(5)
    ]
    cloud = type("C", (), {})()
    cloud.fetch_message_record = lambda: {
        "service_unread": 1,
        "system_unread": 0,
        "latest": "x",
        "service_records": svc,
    }
    # did is derived from cloud attrs: getattr(cloud, "device_id", None) or getattr(cloud, "_did", None)
    cloud.device_id = "did123"
    cloud.fetch_device_messages = lambda did, n: []
    cloud.fetch_share_messages = lambda limit, offset=0: []
    coord._cloud = cloud
    captured = {}
    coord.async_set_updated_data = lambda new: captured.update(new=new)
    # Cross-mixin calls (provided by _LidarOssMixin / _NotificationsMixin via MRO
    # in the real coordinator); isolated mixin under test needs stubs.
    # No-op photo linker = no snapshot photos linked (correct for trim test).
    # Pass-through _merge_device_messages = fresh list unchanged (no accumulation).
    coord.link_message_snapshot_photos = lambda messages: None
    coord._merge_device_messages = lambda fresh_dicts: fresh_dicts

    async def _exec(fn, *a):
        return fn(*a)

    coord.hass = type("H", (), {})()
    coord.hass.async_add_executor_job = _exec
    await _RefreshersMixin._refresh_messages(coord)
    new = captured["new"]
    assert len(new.service_messages) == 2          # trimmed to cap
    assert new.service_messages[0]["title"] == "m4"  # newest first
