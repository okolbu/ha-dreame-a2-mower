"""Tests for the OTA cloud endpoints (B2).

fetch_ota_version  -> iotuserbind/checkDeviceVersion
trigger_firmware_update -> iotuserbind/manualFirmwareUpdate

Auth: Dreame-Auth bearer (token), NO sign (B1 spike: sign opaque/
unreproducible). Body carries a millisecond `timestamp`. Source:
app-mitm 2026-06-16.
"""
from custom_components.dreame_a2_mower.cloud_client._fetchers import _FetchersMixin


class _FakeClient(_FetchersMixin):
    """Minimal stub — the OTA fetchers only use get_api_url + request."""

    def __init__(self, resp=None, exc=None):
        self._resp = resp
        self._exc = exc
        self._did = "9999999"
        self._uid = "BM169439"
        self.last_url = None
        self.last_body = None

    def get_api_url(self):
        return "https://eu.example:13267"

    def request(self, url, data, retry_count=2, content_type="application/x-www-form-urlencoded"):
        self.last_url = url
        self.last_body = data
        # OTA endpoints must send JSON, not form-urlencoded.
        self.last_content_type = content_type
        if self._exc:
            raise self._exc
        return self._resp


def _parse_body(raw):
    import json
    if isinstance(raw, (bytes, str)):
        return json.loads(raw)
    return raw


# --------------------------------------------------------------------------
# fetch_ota_version
# --------------------------------------------------------------------------

def test_fetch_ota_version_parses_four_fields():
    c = _FakeClient(
        {
            "data": {
                "curVersion": "4.3.6_0550",
                "newVersion": "4.3.6_0600",
                "hasNewFirmware": True,
                "description": "Bug fixes",
                "ignored": "extra",
            }
        }
    )
    out = c.fetch_ota_version()
    assert out == {
        "curVersion": "4.3.6_0550",
        "newVersion": "4.3.6_0600",
        "hasNewFirmware": True,
        "description": "Bug fixes",
    }
    # URL hits the checkDeviceVersion endpoint, sent as JSON.
    assert "checkDeviceVersion" in c.last_url
    assert c.last_content_type == "application/json"
    # Body has a timestamp and NO sign.
    body = _parse_body(c.last_body)
    assert "sign" not in body
    assert "timestamp" in body
    assert isinstance(body["timestamp"], int)
    # 13-digit millisecond epoch.
    assert body["timestamp"] > 1_000_000_000_000
    assert body["did"] == "9999999"


def test_fetch_ota_version_undwrapped_dict():
    # Some firmware revs may return the fields at top level (no `data` wrap).
    c = _FakeClient(
        {
            "curVersion": "a",
            "newVersion": "b",
            "hasNewFirmware": False,
            "description": "d",
        }
    )
    out = c.fetch_ota_version()
    assert out == {
        "curVersion": "a",
        "newVersion": "b",
        "hasNewFirmware": False,
        "description": "d",
    }


def test_fetch_ota_version_none_on_garbage():
    assert _FakeClient(None).fetch_ota_version() is None
    assert _FakeClient("not-a-dict").fetch_ota_version() is None
    assert _FakeClient({"data": "nope"}).fetch_ota_version() is None


def test_fetch_ota_version_none_on_exception():
    assert _FakeClient(exc=RuntimeError("boom")).fetch_ota_version() is None


# --------------------------------------------------------------------------
# trigger_firmware_update
# --------------------------------------------------------------------------

def test_trigger_returns_inner_success_true():
    # P3.5: trigger_firmware_update now returns a WriteResult; `.accepted`
    # mirrors the device's INNER data.success (bool(result) == accepted too).
    c = _FakeClient({"success": True, "data": {"success": True}})
    res = c.trigger_firmware_update()
    assert res.accepted is True
    assert res.delivered is True
    assert "manualFirmwareUpdate" in c.last_url
    body = _parse_body(c.last_body)
    assert "sign" not in body
    assert "timestamp" in body and isinstance(body["timestamp"], int)
    assert body["did"] == "9999999"
    assert body["uid"] == "BM169439"


def test_trigger_false_when_inner_false_even_if_outer_true():
    # Outer success only means the API received the call; the device's verdict
    # is the INNER data.success. Device refused (weak WiFi / not charging):
    # delivered but not accepted.
    c = _FakeClient({"success": True, "data": {"success": False}})
    res = c.trigger_firmware_update()
    assert res.accepted is False
    assert res.delivered is True


def test_trigger_false_on_none_and_garbage():
    # None / non-dict / missing-field → NOT delivered (the mower never heard it).
    assert _FakeClient(None).trigger_firmware_update().accepted is False
    assert _FakeClient("not-a-dict").trigger_firmware_update().accepted is False
    assert _FakeClient({"data": {}}).trigger_firmware_update().accepted is False
    assert _FakeClient({"no_data": 1}).trigger_firmware_update().accepted is False
    assert _FakeClient({"no_data": 1}).trigger_firmware_update().delivered is False


def test_trigger_false_on_exception():
    assert _FakeClient(exc=RuntimeError("boom")).trigger_firmware_update().accepted is False
