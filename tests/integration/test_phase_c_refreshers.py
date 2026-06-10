import dataclasses
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest

from custom_components.dreame_a2_mower.coordinator._refreshers import _RefreshersMixin
from custom_components.dreame_a2_mower.mower.state import MowerState


def _coord(gps=None, remote=None, msg=None):
    c = _RefreshersMixin()
    c._cloud = SimpleNamespace(
        fetch_gps=MagicMock(return_value=gps),
        fetch_remote=MagicMock(return_value=remote),
        fetch_message_record=MagicMock(return_value=msg),
    )
    c.data = MowerState()
    async def _exec(fn, *a): return fn(*a)
    c.hass = SimpleNamespace(async_add_executor_job=AsyncMock(side_effect=_exec))
    c.async_set_updated_data = lambda s: setattr(c, "data", s)
    return c


@pytest.mark.asyncio
async def test_refresh_gps_sets_position():
    c = _coord(gps={"lat": 3.5, "lon": 4.5, "update_time": "t", "card4g": "FAKE"})
    await c._refresh_gps()
    assert c.data.position_lat == 3.5 and c.data.position_lon == 4.5
    assert c.data.gps_update_time == "t" and c.data.gps_card4g == "FAKE"


@pytest.mark.asyncio
async def test_refresh_gps_none_clears():
    c = _coord(gps=None)
    c.data = dataclasses.replace(c.data, position_lat=9.9, position_lon=9.9)
    await c._refresh_gps()
    assert c.data.position_lat is None and c.data.position_lon is None


@pytest.mark.asyncio
async def test_refresh_remote_sets_sim():
    c = _coord(remote={"active_time": "a", "card_id": "FAKE", "expired_time": "e", "left_days": 895})
    await c._refresh_remote()
    assert c.data.sim_left_days == 895 and c.data.sim_card_id == "FAKE"


@pytest.mark.asyncio
async def test_refresh_messages_sets_unread():
    c = _coord(msg={"service_unread": 2, "system_unread": 1, "latest": "Sale"})
    await c._refresh_messages()
    assert c.data.service_messages_unread == 2 and c.data.system_messages_unread == 1
    assert c.data.latest_service_message == "Sale"
