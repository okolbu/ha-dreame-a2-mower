from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from custom_components.dreame_a2_mower import services


def _patch_coord(monkeypatch, **methods):
    coord = SimpleNamespace(**methods)
    monkeypatch.setattr(services, "_coordinator_from_call", lambda hass, call: coord)
    return coord


@pytest.mark.asyncio
async def test_create_no_go_zone_service(monkeypatch):
    coord = _patch_coord(monkeypatch, create_no_go=AsyncMock(return_value=True))
    call = SimpleNamespace(hass=SimpleNamespace(), data={
        "map_id": 0, "shape": "polygon", "points": [[1, 2], [3, 4], [5, 6]], "radius": 0,
    })
    await services._handle_create_no_go_zone(call)
    coord.create_no_go.assert_awaited_once_with(0, "polygon", [[1, 2], [3, 4], [5, 6]], 0.0, object_id=-1)


@pytest.mark.asyncio
async def test_create_ignore_obstacle_service(monkeypatch):
    coord = _patch_coord(monkeypatch, create_ignore_obstacle=AsyncMock(return_value=True))
    call = SimpleNamespace(hass=SimpleNamespace(), data={"map_id": 0, "points": [[1, 2], [3, 4], [5, 6]]})
    await services._handle_create_ignore_obstacle(call)
    coord.create_ignore_obstacle.assert_awaited_once_with(0, [[1, 2], [3, 4], [5, 6]], object_id=-1)


@pytest.mark.asyncio
async def test_create_mow_shape_service(monkeypatch):
    coord = _patch_coord(monkeypatch, create_mow_shape=AsyncMock(return_value=True))
    call = SimpleNamespace(hass=SimpleNamespace(), data={"map_id": 0, "shape": "heart", "points": [[0, 0], [1, 1]]})
    await services._handle_create_mow_shape(call)
    coord.create_mow_shape.assert_awaited_once_with(0, "heart", [[0, 0], [1, 1]], object_id=-1)


@pytest.mark.asyncio
async def test_split_and_merge_services(monkeypatch):
    coord = _patch_coord(
        monkeypatch,
        split_zone=AsyncMock(return_value=True),
        merge_zones=AsyncMock(return_value=True),
    )
    await services._handle_split_zone(SimpleNamespace(hass=SimpleNamespace(), data={
        "map_id": 0, "zone": 1, "line_start": [0, 0], "line_end": [1, 1]}))
    await services._handle_merge_zones(SimpleNamespace(hass=SimpleNamespace(), data={
        "map_id": 0, "zones": [2, 1]}))
    coord.split_zone.assert_awaited_once_with(0, 1, [0, 0], [1, 1])
    coord.merge_zones.assert_awaited_once_with(0, [2, 1])


@pytest.mark.asyncio
async def test_handler_swallows_value_error(monkeypatch):
    coord = _patch_coord(monkeypatch, create_no_go=AsyncMock(side_effect=ValueError("bad")))
    # should not raise out of the handler
    await services._handle_create_no_go_zone(SimpleNamespace(hass=SimpleNamespace(), data={
        "map_id": 0, "shape": "line", "points": [[0, 0]], "radius": 0}))
