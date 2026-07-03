from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest

from custom_components.dreame_a2_mower.cloud_client import _fetchers


def _client_with_session(json_body):
    c = _fetchers._FetchersMixin()
    resp = SimpleNamespace(status_code=200, json=lambda: json_body, text="")
    c._session = SimpleNamespace(get=MagicMock(return_value=resp), post=MagicMock(return_value=resp))
    c.get_api_url = lambda: "https://eu.iot.dreame.tech"
    c._ensure_strings = lambda: None
    c.strings = ["" for _ in range(60)]
    c._did = 123
    return c


def test_fetch_gps_sends_real_did():
    """Regression: fetch_gps must read self._did, not self.did (AttributeError
    at runtime -> GPS device_tracker never updated)."""
    c = _client_with_session({"success": True, "locationRecords": {"records": []}})
    c.fetch_gps()
    assert c._session.post.call_args.kwargs["json"]["did"] == "123"


def test_fetch_gps_takes_newest_record():
    body = {"success": True, "locationRecords": {"records": [
        {"gpsLat": "1.0", "gpsLong": "2.0", "updateTime": "2026-06-09 08:00:00", "card4G": "FAKEICCID"},
        {"gpsLat": "3.5", "gpsLong": "4.5", "updateTime": "2026-06-09 16:00:00", "card4G": "FAKEICCID"},
    ]}}
    out = _client_with_session(body).fetch_gps()
    assert out == {"lat": 3.5, "lon": 4.5, "update_time": "2026-06-09 16:00:00", "card4g": "FAKEICCID"}


def test_fetch_gps_empty_records_returns_empty_dict():
    """T3-10: an empty ``records`` list means the endpoint answered with
    genuine "no data" (ATA-gated / Real-Time Location off) — distinct from
    a transport failure, which returns ``None``. The coordinator relies on
    this distinction to avoid clearing the tracker on a transient blip."""
    out = _client_with_session({"success": True, "locationRecords": {"records": []}}).fetch_gps()
    assert out == {}


def test_fetch_gps_http_error_returns_none():
    c = _client_with_session({})
    c._session.post = MagicMock(return_value=SimpleNamespace(status_code=502, json=lambda: {}, text="bad gateway"))
    assert c.fetch_gps() is None


def test_fetch_gps_exception_returns_none():
    c = _client_with_session({})
    c._session.post = MagicMock(side_effect=RuntimeError("boom"))
    assert c.fetch_gps() is None


def test_fetch_message_record_unread():
    body = {"code": 0, "success": True, "data": {
        "serviceMsg": {"unread": 2, "msgRecord": [{"multiLangDisplay": "{\"en\":{\"name\":\"Sale\",\"link\":\"http://x\"}}"}]},
        "systemMsg": {"unread": 1, "msgRecord": []},
    }}
    out = _client_with_session(body).fetch_message_record()
    assert out["service_unread"] == 2 and out["system_unread"] == 1
    assert "Sale" in (out["latest"] or "")


def test_fetch_remote_parses_sim():
    c = _fetchers._FetchersMixin()
    c.action = MagicMock(return_value={"out": [{"m": "g", "t": "REMOTE",
        "d": {"activeTime": "2025-11-20 15:45:29", "cardId": "FAKEICCID",
              "expiredTime": "2028-11-20 15:45:29", "leftDays": 895}}]})
    out = c.fetch_remote()
    assert out == {"active_time": "2025-11-20 15:45:29", "card_id": "FAKEICCID",
                   "expired_time": "2028-11-20 15:45:29", "left_days": 895}


def _4g_client(body):
    """Isolated client for fetch_4g_remain (tsingting host, no get_api_url)."""
    c = _fetchers._FetchersMixin()
    resp = SimpleNamespace(status_code=200, json=lambda: body, text="")
    c._session = SimpleNamespace(get=MagicMock(return_value=resp))
    c._did = 123
    c._sn = "G2408SN"
    c._country = "no"
    return c


# wire-verified shape [api-calls.jsonl @ 2026-06-08 (mitm_session_20260616)]
_4G_BODY = {"code": 200, "msg": "ok", "data": {
    "rem_time": 894, "rem_flow": "1683.05", "act_time": "2025-11-19T16:00:00Z",
    "exp_time": "2028-11-19T16:00:00Z", "pred_del_time": "2029-05-19T16:00:00Z",
    "iccid": "89000000000000000000", "type": 3, "out_of_warranty": False}}


def test_fetch_4g_remain_parses_data_and_warranty():
    out = _4g_client(_4G_BODY).fetch_4g_remain(iccid="89000000000000000000")
    assert out == {
        "data_remaining_mb": 1683.05,
        "out_of_warranty": False,
        "expiry": "2028-11-19T16:00:00Z",
    }


def test_fetch_4g_remain_targets_tsingting_host_with_query():
    c = _4g_client(_4G_BODY)
    c.fetch_4g_remain(iccid="89000000000000000000")
    call = c._session.get.call_args
    url = call.args[0] if call.args else call.kwargs["url"]
    assert url == "https://api-4g.tsingting.tech/api/v1/biz_4g_remain/123"
    params = call.kwargs["params"]
    assert params["sn"] == "G2408SN"
    assert params["iccid"] == "89000000000000000000"
    assert params["region"] == "no"
    assert params["isProd"] == "true"
    # Unauthenticated endpoint — no Dreame-Auth key header is sent.
    assert "headers" not in call.kwargs or not call.kwargs["headers"]


def test_fetch_4g_remain_non_200_returns_none():
    c = _4g_client(_4G_BODY)
    c._session.get = MagicMock(return_value=SimpleNamespace(status_code=500, json=lambda: {}, text=""))
    assert c.fetch_4g_remain(iccid="X") is None


def test_fetch_4g_remain_missing_iccid_returns_none():
    """No ICCID known yet (REMOTE not polled) → skip the call entirely."""
    c = _4g_client(_4G_BODY)
    assert c.fetch_4g_remain(iccid=None) is None
    c._session.get.assert_not_called()
