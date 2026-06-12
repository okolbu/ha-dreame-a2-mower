from unittest.mock import AsyncMock
import pytest
from custom_components.dreame_a2_mower.coordinator._writes import _WritesMixin


def _coord():
    c = _WritesMixin()
    c.edit_map = AsyncMock(return_value=True)
    return c


@pytest.mark.asyncio
async def test_create_defaults_to_minus_one():
    c = _coord()
    await c.create_no_go(0, "polygon", [[1, 2], [3, 4], [5, 6]])
    assert c.edit_map.await_args.args[1][0][1]["id"] == -1


@pytest.mark.asyncio
async def test_edit_in_place_uses_real_id():
    c = _coord()
    await c.create_no_go(0, "polygon", [[1, 2], [3, 4], [5, 6]], object_id=101)
    op, payload = c.edit_map.await_args.args[1][0]
    assert op == 215 and payload["id"] == 101
    await c.create_ignore_obstacle(0, [[1, 2], [3, 4], [5, 6]], object_id=205)
    assert c.edit_map.await_args.args[1][0][1]["id"] == 205
    await c.create_mow_shape(0, "heart", [[0, 0], [1, 1]], object_id=302)
    assert c.edit_map.await_args.args[1][0][1]["id"] == 302
