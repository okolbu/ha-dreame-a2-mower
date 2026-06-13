"""start_point_patrol + start_edge_patrol: ensure-active-map then dispatch."""
from unittest.mock import AsyncMock

from custom_components.dreame_a2_mower.cloud_client import WriteResult
from custom_components.dreame_a2_mower.coordinator._writes import _WritesMixin
from custom_components.dreame_a2_mower.mower.actions import MowerAction


class _Stub(_WritesMixin):
    def __init__(self):
        # Explicit accepted results — start_* now propagates the WriteResult to
        # its caller, so the mocks return a real one rather than a bare MagicMock.
        self._ensure_active_map = AsyncMock(return_value=WriteResult.local_ok())
        self.dispatch_action = AsyncMock(return_value=WriteResult.local_ok())


async def test_start_point_patrol_routes():
    c = _Stub()
    result = await c.start_point_patrol(map_id=0, point_ids=[3, 4])
    c._ensure_active_map.assert_awaited_once_with(0)
    c.dispatch_action.assert_awaited_once_with(
        MowerAction.START_POINT_PATROL, {"point_ids": [3, 4]}
    )
    assert result.accepted


async def test_start_edge_patrol_routes():
    c = _Stub()
    result = await c.start_edge_patrol(map_id=0, contour_ids=[[1, 0]])
    c._ensure_active_map.assert_awaited_once_with(0)
    c.dispatch_action.assert_awaited_once_with(
        MowerAction.START_EDGE_PATROL, {"contour_ids": [[1, 0]]}
    )
    assert result.accepted
