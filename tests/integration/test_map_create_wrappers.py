from unittest.mock import AsyncMock
import pytest
from custom_components.dreame_a2_mower.coordinator._writes import _WritesMixin


def _coord():
    c = _WritesMixin()
    c.edit_map = AsyncMock(return_value=True)
    return c


@pytest.mark.asyncio
async def test_create_no_go_polygon_circle_line():
    c = _coord()
    await c.create_no_go(0, "polygon", [[9.65, -0.13], [4.12, -0.13], [4.12, 5.01]])
    await c.create_no_go(0, "circle", [[-5.08, -4.97]], radius=1.5)
    await c.create_no_go(1, "line", [[6.48, 3.23], [-7.56, -5.81]])
    muts = [call.args[1][0] for call in c.edit_map.await_args_list]
    assert muts[0] == (215, {"id": -1, "type": 2, "points": [[9.65, -0.13], [4.12, -0.13], [4.12, 5.01]], "radius": 0.0})
    assert muts[1] == (215, {"id": -1, "type": 3, "points": [[-5.08, -4.97]], "radius": 1.5})
    assert muts[2] == (215, {"id": -1, "type": 1, "points": [[6.48, 3.23], [-7.56, -5.81]], "radius": 0.0})


@pytest.mark.asyncio
async def test_create_ignore_obstacle_has_no_radius():
    c = _coord()
    await c.create_ignore_obstacle(0, [[-2.49, -5.97], [-8.71, -5.97], [-8.71, -0.18]])
    op, payload = c.edit_map.await_args.args[1][0]
    assert op == 234 and payload["type"] == 0 and "radius" not in payload


@pytest.mark.asyncio
async def test_create_mow_shape():
    c = _coord()
    await c.create_mow_shape(0, "heart", [[0.57, -8.39], [-7.97, 0.15]])
    assert c.edit_map.await_args.args[1][0] == (215, {"id": -1, "type": 13, "points": [[0.57, -8.39], [-7.97, 0.15]], "radius": 0})


@pytest.mark.asyncio
async def test_split_and_merge():
    c = _coord()
    await c.split_zone(0, 1, [-0.19, -11.41], [-5.21, -6.22])
    await c.merge_zones(0, [2, 1])
    muts = [call.args[1][0] for call in c.edit_map.await_args_list]
    assert muts[0] == (220, {"id": 1, "line_start": [-0.19, -11.41], "line_end": [-5.21, -6.22]})
    assert muts[1] == (221, {"ids": [2, 1]})


@pytest.mark.asyncio
async def test_validation_rejects_before_wire():
    c = _coord()
    with pytest.raises(ValueError):
        await c.create_no_go(0, "line", [[0, 0]])           # need 2 points
    with pytest.raises(ValueError):
        await c.create_mow_shape(0, "square", [[0, 0], [1, 1]])  # need 4
    c.edit_map.assert_not_awaited()
