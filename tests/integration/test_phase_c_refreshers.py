import dataclasses
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest

from custom_components.dreame_a2_mower.coordinator._refreshers import _RefreshersMixin
from custom_components.dreame_a2_mower.mower.state import MowerState


def _coord(gps=None, remote=None, msg=None, dev=None, ota=None, g4=None):
    c = _RefreshersMixin()
    c._cloud = SimpleNamespace(
        fetch_gps=MagicMock(return_value=gps),
        fetch_remote=MagicMock(return_value=remote),
        fetch_4g_remain=MagicMock(return_value=g4),
        fetch_message_record=MagicMock(return_value=msg),
        fetch_device_messages=MagicMock(return_value=[]),
        fetch_share_messages=MagicMock(return_value=[]),
        fetch_dev=MagicMock(return_value=dev),
        fetch_ota_version=MagicMock(return_value=ota),
        device_id=None,
        _did=None,
    )
    c.data = MowerState()
    async def _exec(fn, *a): return fn(*a)
    c.hass = SimpleNamespace(async_add_executor_job=AsyncMock(side_effect=_exec))
    c.async_set_updated_data = lambda s: setattr(c, "data", s)
    c._update_device_registry_serial = MagicMock()
    # Cross-mixin call provided by _LidarOssMixin via MRO in the real coordinator.
    c.link_message_snapshot_photos = lambda messages: None
    # Cross-mixin call: _merge_device_messages lives on _NotificationsMixin; stub
    # it here to return fresh_dicts unchanged (no accumulation in this isolated test).
    c._merge_device_messages = lambda fresh_dicts: fresh_dicts
    return c


@pytest.mark.asyncio
async def test_refresh_gps_sets_position():
    c = _coord(gps={"lat": 3.5, "lon": 4.5, "update_time": "t", "card4g": "FAKE"})
    await c._refresh_gps()
    assert c.data.position_lat == 3.5 and c.data.position_lon == 4.5
    assert c.data.gps_update_time == "t" and c.data.gps_card4g == "FAKE"


@pytest.mark.asyncio
async def test_refresh_gps_none_keeps_last_fix():
    """T3-10: ``None`` means the fetch itself failed (HTTP error, timeout,
    exception) — a transient failure must NOT be conflated with genuine
    "no GPS data" and must NOT clear the last known fix."""
    c = _coord(gps=None)
    c.data = dataclasses.replace(
        c.data, position_lat=9.9, position_lon=9.9,
        gps_update_time="2026-01-01T00:00:00", gps_card4g="FAKE")
    await c._refresh_gps()
    assert c.data.position_lat == 9.9 and c.data.position_lon == 9.9
    assert c.data.gps_update_time == "2026-01-01T00:00:00" and c.data.gps_card4g == "FAKE"


@pytest.mark.asyncio
async def test_refresh_gps_empty_dict_clears():
    """T3-10: an empty dict is the explicit "endpoint answered, zero
    records" shape (ATA-gated / Real-Time Location off) — this genuine
    no-data response IS supposed to clear the tracker."""
    c = _coord(gps={})
    c.data = dataclasses.replace(
        c.data, position_lat=9.9, position_lon=9.9,
        gps_update_time="2026-01-01T00:00:00", gps_card4g="FAKE")
    await c._refresh_gps()
    assert c.data.position_lat is None and c.data.position_lon is None
    assert c.data.gps_update_time is None and c.data.gps_card4g is None


@pytest.mark.asyncio
async def test_refresh_remote_sets_sim():
    c = _coord(remote={"active_time": "a", "card_id": "FAKE", "expired_time": "e", "left_days": 895})
    await c._refresh_remote()
    assert c.data.sim_left_days == 895 and c.data.sim_card_id == "FAKE"


@pytest.mark.asyncio
async def test_refresh_remote_folds_4g_data():
    """The REMOTE refresh chains a biz_4g_remain fetch (keyed by the ICCID it
    just learned) and folds the quantitative SIM fields."""
    c = _coord(
        remote={"active_time": "a", "card_id": "ICCID1", "expired_time": "e", "left_days": 895},
        g4={"data_remaining_mb": 1683.05, "out_of_warranty": False,
            "expiry": "2028-11-19T16:00:00Z"},
    )
    await c._refresh_remote()
    assert c.data.sim_data_remaining_mb == 1683.05
    assert c.data.sim_out_of_warranty is False
    # expiry now comes from biz_4g_remain's ISO exp_time (not REMOTE's TZ-ambiguous string)
    assert c.data.sim_expired_time == "2028-11-19T16:00:00Z"
    # the 4G fetch is keyed by the ICCID from REMOTE's card_id
    assert c._cloud.fetch_4g_remain.call_args.args[0] == "ICCID1"


@pytest.mark.asyncio
async def test_refresh_remote_no_4g_method_does_not_crash():
    """Stub clouds lacking fetch_4g_remain must not break _refresh_remote."""
    c = _coord(remote={"active_time": "a", "card_id": "ICCID1", "expired_time": "e", "left_days": 895})
    del c._cloud.fetch_4g_remain
    await c._refresh_remote()
    assert c.data.sim_card_id == "ICCID1"
    assert c.data.sim_data_remaining_mb is None


@pytest.mark.asyncio
async def test_refresh_messages_sets_unread():
    c = _coord(msg={"service_unread": 2, "system_unread": 1, "latest": "Sale"})
    await c._refresh_messages()
    assert c.data.service_messages_unread == 2 and c.data.system_messages_unread == 1
    assert c.data.latest_service_message == "Sale"


@pytest.mark.asyncio
async def test_refresh_dev_folds_ota_version():
    c = _coord(
        dev={"sn": "G2408000TESTSN0000", "fw": "4.3.6_0550", "ota": 1},
        ota={
            "curVersion": "4.3.6_0550",
            "newVersion": "4.3.6_0625",
            "hasNewFirmware": True,
            "description": "notes",
        },
    )
    await c._refresh_dev()
    assert c.data.firmware_latest == "4.3.6_0625"
    assert c.data.firmware_update_available is True
    assert c.data.firmware_release_notes == "notes"
    # DEV updates still applied in the same pass.
    assert c.data.hardware_serial == "G2408000TESTSN0000"
    assert c.data.firmware_version == "4.3.6_0550"


@pytest.mark.asyncio
async def test_refresh_dev_no_ota_method_does_not_crash():
    """Stub clouds lacking fetch_ota_version must not break _refresh_dev."""
    c = _coord(dev={"sn": "SN1", "fw": "4.3.6_0550", "ota": 1})
    del c._cloud.fetch_ota_version
    await c._refresh_dev()
    assert c.data.hardware_serial == "SN1"
    assert c.data.firmware_latest is None
