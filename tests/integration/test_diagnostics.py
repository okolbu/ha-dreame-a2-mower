"""Tests for the download_diagnostics handler.

R-3 rewrite: the dump moved from a denylist (``REDACTION_KEYS``) to an
explicit ALLOWLIST (default-deny). These tests pin two things:

1. A comprehensive set of sensitive sentinel values (GPS, wifi, SIM,
   serial, cloud did/uid/uuid/host, MQTT topics, config-entry
   credentials) must appear NOWHERE in the serialized diagnostics blob.
2. The safe debugging surface (state-machine phase/battery, versions,
   entity/archive counts, redaction markers) is still present.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.diagnostics import (
    async_get_config_entry_diagnostics,
)


def _build_diagnostics_output():
    """Build a coordinator/hass/entry rig with sensitive fields populated
    with sentinel values, then run the diagnostics handler. Returns
    (out, blob, sentinels) for the leak-absence + presence assertions."""
    from custom_components.dreame_a2_mower.const import DOMAIN
    from custom_components.dreame_a2_mower.observability import (
        FreshnessTracker,
        NovelLogBuffer,
        NovelObservationRegistry,
    )
    from custom_components.dreame_a2_mower.state import MowerState

    coordinator = MagicMock()
    coordinator.data = MowerState(
        battery_level=42,
        position_lat=59.9,
        position_lon=10.7,
        gps_card4g="GPS-CARD-SENTINEL",
        wifi_ssid="MyNet",
        wifi_ip="192.168.1.50",
        hardware_serial="SN-SECRET-123",
        sim_card_id="8947000000000000000",
    )
    coordinator.freshness = FreshnessTracker()
    coordinator.novel_registry = NovelObservationRegistry()
    coordinator.novel_log = NovelLogBuffer(
        maxlen=10, prefixes=("[NOVEL/property]",)
    )
    cloud = MagicMock()
    cloud.endpoint_log = {"routed_action_op=100": "accepted"}
    cloud._did = "DID-SENTINEL"
    cloud._uid = "UID-SENTINEL"
    cloud._uuid = "UUID-SENTINEL"
    cloud._host = "HOST-SENTINEL.example.com"
    cloud._logged_in = True
    cloud._connected = True
    cloud._model = "a2.mower.g2408"
    cloud._country = "no"
    cloud._last_send_error_code = None
    coordinator._cloud = cloud
    coordinator.cloud = cloud

    mqtt = MagicMock()
    mqtt._connected = True
    mqtt._connecting = False
    mqtt._subscribe_topic = "TOPIC-SENTINEL/SN-SECRET-123/property"
    mqtt._first_topics = ["TOPIC-SENTINEL/SN-SECRET-123/property"]
    mqtt._callback = object()
    mqtt._client = object()
    mqtt._username = "mqttuser"
    mqtt._suback_results = [0]
    coordinator.mqtt = mqtt

    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "abc123"
    entry.data = {
        "username": "alice",
        "password": "secret",
        "token": "TOKEN-VALUE-SENTINEL",
        "did": "did1",
        "mac": "aa:bb",
        "host": "1.2.3.4",
        "sn": "SN-SECRET-123",
        "country": "no",
        "model": "a2.mower.g2408",
    }
    hass.data = {DOMAIN: {"abc123": coordinator}}

    out = asyncio.run(async_get_config_entry_diagnostics(hass, entry))
    blob = json.dumps(out, default=str)
    sentinels = [
        "59.9",
        "10.7",
        "GPS-CARD-SENTINEL",
        "MyNet",
        "192.168.1.50",
        "SN-SECRET-123",
        "8947000000000000000",
        "DID-SENTINEL",
        "UID-SENTINEL",
        "UUID-SENTINEL",
        "HOST-SENTINEL.example.com",
        "TOPIC-SENTINEL/SN-SECRET-123/property",
        "alice",
        "secret",
        "TOKEN-VALUE-SENTINEL",
        "did1",
        "aa:bb",
        "1.2.3.4",
    ]
    return out, blob, sentinels


def test_diagnostics_leaks_no_sensitive_sentinels():
    """The single load-bearing leak-absence test (R-3): none of the
    sensitive sentinel values may appear anywhere in the serialized
    diagnostics blob."""
    _out, blob, sentinels = _build_diagnostics_output()
    for sentinel in sentinels:
        assert sentinel not in blob, f"sentinel leaked into diagnostics blob: {sentinel!r}"


def test_diagnostics_dump_safe_surface_present():
    """The safe debugging surface survives the allowlist rewrite."""
    out, _blob, _sentinels = _build_diagnostics_output()

    assert "config_entry" in out
    assert out["config_entry"]["password"] == "**REDACTED**"
    assert out["config_entry"]["username"] == "**REDACTED**"
    assert out["config_entry"]["token"] == "**REDACTED**"
    assert out["config_entry"]["did"] == "**REDACTED**"
    assert out["config_entry"]["mac"] == "**REDACTED**"
    assert out["config_entry"]["host"] == "**REDACTED**"
    assert out["config_entry"]["sn"] == "**REDACTED**"
    assert out["config_entry"]["country"] == "no"
    assert out["config_entry"]["model"] == "a2.mower.g2408"

    assert "state" in out
    assert out["state"]["battery_level"] == 42
    for leaky_field in (
        "position_lat", "position_lon", "gps_card4g", "wifi_ssid",
        "wifi_ip", "sim_card_id", "hardware_serial",
    ):
        assert leaky_field not in out["state"], f"{leaky_field} must be absent from state"

    assert "versions" in out
    assert out["versions"]["integration"]
    assert "firmware" in out["versions"]

    assert "entity_counts" in out
    assert "archive_counts" in out

    assert "cloud_state" in out
    for key in ("did", "uid", "uuid", "host"):
        assert key not in out["cloud_state"]
    assert out["cloud_state"]["logged_in"] is True
    assert out["cloud_state"]["country"] == "no"

    assert "mqtt_state" in out
    for key in ("subscribe_topic", "first_topics"):
        assert key not in out["mqtt_state"]
    assert out["mqtt_state"]["connected"] is True

    assert "capabilities" in out
    assert out["capabilities"]["lidar_navigation"] is True

    assert out["novel_observations"] == []
    assert out["freshness"] == {}
    assert out["endpoint_log"] == {"routed_action_op=100": "accepted"}
    assert out["recent_novel_log_lines"] == []
