from types import SimpleNamespace
from unittest.mock import MagicMock
from tests.cloud_client import _fetchers_double as _fetchers


def _client(json_body):
    c = _fetchers._FetchersMixin()
    resp = SimpleNamespace(status_code=200, json=lambda: json_body, text="")
    c._session = SimpleNamespace(post=MagicMock(return_value=resp), get=MagicMock(return_value=resp))
    c.get_api_url = lambda: "https://eu.iot.dreame.tech"
    c._ensure_strings = lambda: None
    c.strings = ["" for _ in range(60)]
    c._did = 123
    return c


def test_list_oss_media_sends_real_did():
    """Regression: list_oss_media must read self._did (the real client attr),
    NOT self.did — DreameA2CloudClient has no `did` attribute, so self.did
    raised AttributeError at runtime (caught -> None -> silent no-op sync)."""
    c = _client({"data": {"records": []}})
    c.list_oss_media("jpg")
    assert c._session.post.call_args.kwargs["json"]["did"] == "123"


def test_fetch_oss_quota_sends_real_did():
    c = _client({"data": {}})
    c.fetch_oss_quota()
    assert c._session.post.call_args.kwargs["json"]["did"] == "123"


def test_list_oss_media_jpg_records():
    body = {"code": 0, "success": True, "data": {"records": [
        {"id": "1", "type": "jpg", "filepath": "https://fake/oss/a.jpg", "uploadTime": "2026-06-08 21:07:08", "videoPath": "", "ext": "0", "fileSize": 100, "key": "0"},
    ]}}
    recs = _client(body).list_oss_media("jpg")
    assert recs and recs[0]["id"] == "1" and recs[0]["filepath"] == "https://fake/oss/a.jpg"


def test_list_oss_media_thumb_records():
    body = {"code": 0, "success": True, "data": {"records": [
        {"id": "9", "type": "thumb", "filepath": "https://fake/oss/t.jpg", "videoPath": "https://fake/oss/v.mp4", "ext": "{\"duration\":18}", "uploadTime": "2026-06-09 18:42:13", "fileSize": 100, "key": "k"},
    ]}}
    recs = _client(body).list_oss_media("thumb")
    assert recs[0]["videoPath"] == "https://fake/oss/v.mp4"


def test_list_oss_media_tolerates_top_level_records():
    body = {"records": [{"id": "1", "type": "jpg", "filepath": "https://fake/a.jpg", "videoPath": "", "uploadTime": "x"}]}
    assert _client(body).list_oss_media("jpg")[0]["id"] == "1"


def test_fetch_oss_quota():
    q = _client({"code": 0, "success": True, "data": {"total": "209715200", "used": "45898604"}}).fetch_oss_quota()
    assert q == {"total": 209715200, "used": 45898604}


def test_fetch_oss_quota_none_on_bad():
    assert _client({"code": 0, "data": {}}).fetch_oss_quota() is None
