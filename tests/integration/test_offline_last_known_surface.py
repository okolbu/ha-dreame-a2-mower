"""Task 12b — OFFLINE entity availability + staleness + connectivity consistency.

The 12a persistence layer seeds ``coord.data`` read-only fields from a LastKnown
Store before the first cloud fetch. This is the ENTITY-SURFACE half: when the
freshness gate says NOT fresh (cloud/mqtt link down) an entity that still HOLDS a
seeded last-known value stays ``available`` (marked ``stale``) instead of going
unavailable — while an entity with genuinely no value still goes unavailable, and
the connectivity-STATUS entities keep showing the real (disconnected) state.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.dreame_a2_mower.state import MowerState
from custom_components.dreame_a2_mower.state.machine import MowerStateMachine


def _coord(*, mqtt: bool = True, cloud: bool = True, saved_unix=1000.0, data=None):
    coord = MagicMock()
    coord.mqtt_is_fresh = mqtt
    coord.cloud_is_fresh = cloud
    coord.last_known_saved_unix = saved_unix
    coord.entry.entry_id = "fake"
    coord.data = data if data is not None else MowerState()
    return coord


# ---------------------------------------------------------------------------
# 1. offline (cloud not fresh) + seeded last-known value → available + stale
# ---------------------------------------------------------------------------

def test_sensor_stays_available_and_marks_stale_when_cloud_offline():
    from custom_components.dreame_a2_mower.entities.sensor.device import (
        SENSORS,
        DreameA2Sensor,
    )

    desc = next(d for d in SENSORS if d.key == "blades_life_pct")
    assert desc.availability_source == "cloud"

    coord = _coord(cloud=False, data=MowerState(blades_life_pct=88.0))
    ent = DreameA2Sensor(coord, desc)

    # The seeded last-known value is present…
    assert ent.native_value == 88.0
    # …so the entity stays visible instead of going unavailable,
    assert ent.available is True
    # …marked stale, carrying the blob-level save timestamp.
    attrs = ent.extra_state_attributes
    assert attrs["stale"] is True
    assert attrs["last_updated"] == 1000.0


def test_diagnostic_sensor_stays_available_stale_when_cloud_offline():
    from custom_components.dreame_a2_mower.entities.sensor.device import (
        DIAGNOSTIC_SENSORS,
        DreameA2DiagnosticSensor,
    )

    desc = next(d for d in DIAGNOSTIC_SENSORS if d.key == "cfg_version")
    assert desc.availability_source == "cloud"

    coord = _coord(cloud=False, data=MowerState(cfg_version=42))
    ent = DreameA2DiagnosticSensor(coord, desc)
    assert ent.native_value == 42
    assert ent.available is True
    assert ent.extra_state_attributes["stale"] is True


# ---------------------------------------------------------------------------
# 2. config switch: display stays available but the WRITE still RAISES offline
# ---------------------------------------------------------------------------

def test_config_switch_sticky_available_but_write_still_raises_offline():
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.dreame_a2_mower.cloud_client._helpers import WriteResult
    from custom_components.dreame_a2_mower.entities.switch.global_ import SWITCHES
    from custom_components.dreame_a2_mower.entities.switch.base import DreameA2Switch

    desc = next(d for d in SWITCHES if d.key == "child_lock")
    assert DreameA2Switch._availability_source == "cloud"

    coord = _coord(cloud=False, data=MowerState(child_lock_enabled=True))
    # The device rejects the write (delivered, not accepted).
    coord.write_setting = AsyncMock(
        return_value=WriteResult(delivered=True, accepted=False, code=1, msg="no")
    )
    ent = DreameA2Switch(coord, desc)

    # Sticky display: last-known value keeps it visible + stale.
    assert ent.is_on is True
    assert ent.available is True
    assert ent.extra_state_attributes["stale"] is True

    # But the write path is UNCHANGED — a rejected write raises (T3-3).
    with pytest.raises(HomeAssistantError):
        import asyncio

        asyncio.run(ent.async_turn_on())


# ---------------------------------------------------------------------------
# 3. offline + NO value (None) → unavailable
# ---------------------------------------------------------------------------

def test_sensor_unavailable_when_offline_and_no_value():
    from custom_components.dreame_a2_mower.entities.sensor.device import (
        SENSORS,
        DreameA2Sensor,
    )

    desc = next(d for d in SENSORS if d.key == "blades_life_pct")
    coord = _coord(cloud=False, data=MowerState())  # blades_life_pct is None
    ent = DreameA2Sensor(coord, desc)
    assert ent.native_value is None
    assert ent.available is False
    # No value → no stale marker either.
    assert not (ent.extra_state_attributes or {})


# ---------------------------------------------------------------------------
# 4. fresh again → stale absent
# ---------------------------------------------------------------------------

def test_sensor_not_stale_when_fresh():
    from custom_components.dreame_a2_mower.entities.sensor.device import (
        SENSORS,
        DreameA2Sensor,
    )

    desc = next(d for d in SENSORS if d.key == "blades_life_pct")
    coord = _coord(cloud=True, data=MowerState(blades_life_pct=88.0))
    ent = DreameA2Sensor(coord, desc)
    assert ent.available is True
    assert "stale" not in (ent.extra_state_attributes or {})


# ---------------------------------------------------------------------------
# 5. connectivity-STATUS entities show the real disconnected state offline —
#    NOT a stale "connected". They are ungated (source None) + live value_fn.
# ---------------------------------------------------------------------------

def test_cloud_connected_binary_sensor_is_live_not_last_known_sticky():
    from custom_components.dreame_a2_mower.binary_sensor import (
        BINARY_SENSORS,
        DreameA2BinarySensor,
    )

    desc = next(d for d in BINARY_SENSORS if d.key == "cloud_connected")
    # Ungated: never freshness-sticky, so it can honestly report disconnected.
    assert desc.availability_source is None

    coord = _coord(mqtt=False, cloud=False)
    coord.state_machine = MowerStateMachine()  # no heartbeat yet
    ent = DreameA2BinarySensor(coord, desc)
    # Live value_fn reads the snapshot (None until first heartbeat) — it is NOT
    # seeded from LastKnown, so it can never show a stale "connected".
    assert ent.is_on is None
    # Ungated availability: the reporter itself stays visible…
    assert ent.available is True
    # …and carries no stale marker (source None is never sticky/stale).
    assert not (ent.extra_state_attributes or {})


def test_mqtt_connectivity_sensor_is_ungated_and_live():
    from custom_components.dreame_a2_mower.entities.sensor.device import (
        DreameA2MqttConnectivitySensor,
    )

    coord = _coord(mqtt=False, cloud=False)
    coord.state_machine = MowerStateMachine()
    ent = DreameA2MqttConnectivitySensor(coord)
    assert ent._availability_source is None
    assert ent.available is True
    # Its own age_s attrs stand; no stale marker injected (ungated).
    assert "stale" not in ent.extra_state_attributes


# ---------------------------------------------------------------------------
# 6. connectivity consistency (d): wifi_ssid/wifi_ip are cloud-sourced
# ---------------------------------------------------------------------------

def test_wifi_ssid_and_ip_descriptors_are_cloud_sourced():
    from custom_components.dreame_a2_mower.entities.sensor.device import SENSORS

    ssid = next(d for d in SENSORS if d.key == "wifi_ssid")
    ip = next(d for d in SENSORS if d.key == "wifi_ip")
    assert ssid.availability_source == "cloud"
    assert ip.availability_source == "cloud"


def test_wifi_sensors_sticky_stale_when_cloud_offline():
    from custom_components.dreame_a2_mower.entities.sensor.device import (
        SENSORS,
        DreameA2Sensor,
    )

    desc = next(d for d in SENSORS if d.key == "wifi_ssid")
    coord = _coord(cloud=False, data=MowerState(wifi_ssid="MyLawnNet"))
    ent = DreameA2Sensor(coord, desc)
    assert ent.native_value == "MyLawnNet"
    assert ent.available is True
    assert ent.extra_state_attributes["stale"] is True


# ---------------------------------------------------------------------------
# 7. refresh_net persists last-known promptly (closes the 12a Minor)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_net_persists_last_known_on_success():
    from custom_components.dreame_a2_mower.domain import device_info

    c = SimpleNamespace()
    c._cloud = SimpleNamespace(
        fetch_net=lambda: {
            "current": "MyLawnNet",
            "list": [{"ssid": "MyLawnNet", "ip": "192.168.1.5", "rssi": -55}],
        }
    )
    c.data = MowerState()

    async def _exec(fn, *a):
        return fn(*a)

    c.hass = SimpleNamespace(async_add_executor_job=_exec)
    c.async_set_updated_data = lambda s: setattr(c, "data", s)
    c.saves = 0
    c._save_last_known = lambda: setattr(c, "saves", c.saves + 1)

    await device_info.refresh_net(c)
    assert c.data.wifi_ssid == "MyLawnNet"
    assert c.data.wifi_ip == "192.168.1.5"
    assert c.saves == 1


@pytest.mark.asyncio
async def test_refresh_net_failure_does_not_persist():
    from custom_components.dreame_a2_mower.domain import device_info

    c = SimpleNamespace()
    c._cloud = SimpleNamespace(fetch_net=lambda: None)  # transient failure
    c.data = MowerState()

    async def _exec(fn, *a):
        return fn(*a)

    c.hass = SimpleNamespace(async_add_executor_job=_exec)
    c.async_set_updated_data = lambda s: setattr(c, "data", s)
    c.saves = 0
    c._save_last_known = lambda: setattr(c, "saves", c.saves + 1)

    await device_info.refresh_net(c)
    assert c.saves == 0
