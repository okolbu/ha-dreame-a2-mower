"""New diagnostic sensors: cloud device-id, API endpoint, integration version."""
from __future__ import annotations
from unittest.mock import MagicMock


def _coord():
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    cloud = MagicMock()
    cloud.device_id = "BM169439"
    cloud.host = "eu.iot.dreame.tech"
    coord._cloud = cloud
    coord.cloud = cloud
    return coord


def _cloud_device_id_descriptor():
    from custom_components.dreame_a2_mower.sensor import DIAGNOSTIC_SENSORS
    return next(d for d in DIAGNOSTIC_SENSORS if d.key == "cloud_device_id")


def test_cloud_device_id_sensor():
    d = _cloud_device_id_descriptor()
    assert d.value_fn(_coord()) == "BM169439"
    assert d.entity_category == "diagnostic"


def test_cloud_device_id_sensor_none_when_missing():
    """When the cloud client isn't ready, returns None. The entity is
    `entity_registry_enabled_default=False`, so HA's auto-disable on
    None doesn't bite — the user explicitly enables it if they want it."""
    coord = MagicMock()
    coord._cloud = None
    coord.cloud = None
    assert _cloud_device_id_descriptor().value_fn(coord) is None


def test_api_endpoint_sensor():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2ApiEndpointSensor,
    )
    s = DreameA2ApiEndpointSensor(_coord())
    assert s.native_value == "eu.iot.dreame.tech:19973"


def test_integration_version_sensor():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2IntegrationVersionSensor,
    )
    s = DreameA2IntegrationVersionSensor(_coord())
    val = s.native_value
    assert isinstance(val, str)
    assert val


def test_ota_state_and_progress_sensors_present():
    from custom_components.dreame_a2_mower.entities.sensor.device import DIAGNOSTIC_SENSORS
    keys = {d.key for d in DIAGNOSTIC_SENSORS}
    assert "ota_state" in keys
    assert "ota_progress" in keys


def test_ota_state_value_fn_reads_mower_state():
    from types import SimpleNamespace
    from custom_components.dreame_a2_mower.entities.sensor.device import DIAGNOSTIC_SENSORS
    desc = next(d for d in DIAGNOSTIC_SENSORS if d.key == "ota_state")
    coord = SimpleNamespace(data=SimpleNamespace(ota_state=2))
    # s1p2 maps through the OTAState enum; inventory.yaml § s1p2 ota_state.
    assert desc.value_fn(coord) == "upgrading"


def test_ota_state_value_fn_none_stays_none():
    from types import SimpleNamespace
    from custom_components.dreame_a2_mower.entities.sensor.device import DIAGNOSTIC_SENSORS
    desc = next(d for d in DIAGNOSTIC_SENSORS if d.key == "ota_state")
    coord = SimpleNamespace(data=SimpleNamespace(ota_state=None))
    assert desc.value_fn(coord) is None
