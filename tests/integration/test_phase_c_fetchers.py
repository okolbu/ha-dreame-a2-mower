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
    c.did = 123
    return c


def test_fetch_gps_takes_newest_record():
    body = {"success": True, "locationRecords": {"records": [
        {"gpsLat": "1.0", "gpsLong": "2.0", "updateTime": "2026-06-09 08:00:00", "card4G": "FAKEICCID"},
        {"gpsLat": "3.5", "gpsLong": "4.5", "updateTime": "2026-06-09 16:00:00", "card4G": "FAKEICCID"},
    ]}}
    out = _client_with_session(body).fetch_gps()
    assert out == {"lat": 3.5, "lon": 4.5, "update_time": "2026-06-09 16:00:00", "card4g": "FAKEICCID"}


def test_fetch_gps_empty_records_returns_none():
    assert _client_with_session({"success": True, "locationRecords": {"records": []}}).fetch_gps() is None


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
