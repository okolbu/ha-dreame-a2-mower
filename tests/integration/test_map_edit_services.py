"""Map-edit services: rename_zone + delete_map_object."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.dreame_a2_mower import services

from custom_components.dreame_a2_mower.cloud_client import WriteResult as _WR

# P2 Task 5: the coordinator write families return WriteResult, not bool.
_WR_ACCEPTED = _WR(delivered=True, accepted=True, code=0)
_WR_REJECTED = _WR(delivered=True, accepted=False, code=-3, msg="not supported")



@pytest.mark.asyncio
async def test_rename_zone_service(monkeypatch):
    coord = SimpleNamespace(rename_zone=AsyncMock(return_value=_WR_ACCEPTED))
    monkeypatch.setattr(services, "_coordinator_from_call", lambda hass, call: coord)
    call = SimpleNamespace(
        hass=SimpleNamespace(), data={"map_id": 1, "zone": 3, "name": "Lawn"}
    )
    await services._handle_rename_zone(call)
    coord.rename_zone.assert_awaited_once_with(1, 3, "Lawn")


@pytest.mark.asyncio
async def test_delete_map_object_service(monkeypatch):
    coord = SimpleNamespace(delete_map_object=AsyncMock(return_value=_WR_ACCEPTED))
    monkeypatch.setattr(services, "_coordinator_from_call", lambda hass, call: coord)
    call = SimpleNamespace(
        hass=SimpleNamespace(), data={"map_id": 0, "object_id": 102, "category": 4}
    )
    await services._handle_delete_map_object(call)
    coord.delete_map_object.assert_awaited_once_with(0, 102, 4)
