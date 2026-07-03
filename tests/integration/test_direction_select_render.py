"""P2 Task 6 (T3-4): the per-map mowing-direction select must re-render the
stripe preview after a successful write.

Recurring bug pattern (same family as test_action_mode_select.py): a select
write that changes a field the STRIPES-mode renderer consumes
(settings_mowing_direction) used to only broadcast the new state — no render,
no camera access_token rotation — so the map card kept showing the old stripe
angle until an unrelated render trigger fired (e.g. the next mow start).

These tests pin the contract: an ACCEPTED write must await
coordinator._render_base() and then broadcast again via
coordinator.async_update_listeners() (the established
broadcast->render->broadcast token-rotation dance, see
feedback_camera_image_refresh_pattern); a REJECTED write must NOT render
(nothing new to paint — the value was already reverted).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.dreame_a2_mower.entities.select.map_settings import (
    DreameA2PerMapMowingDirectionSelect,
)
from custom_components.dreame_a2_mower.mower.state import MowerState

_MAP_ID = 0
_PATCH_TARGET = (
    "custom_components.dreame_a2_mower.entities.select.map_settings."
    "pre_settings_optimistic_write"
)


def _make_coord():
    coord = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.data = MowerState()
    cs = MagicMock()
    cs.maps_by_id = {_MAP_ID: MagicMock(name="Front")}
    cs.settings.by_map_id_canonical = {_MAP_ID: {"mowingDirection": 0}}
    coord.cloud_state = cs
    return coord


def _make_entity(coord):
    ent = DreameA2PerMapMowingDirectionSelect(coord, map_id=_MAP_ID)
    ent.async_write_ha_state = MagicMock()
    return ent


@pytest.mark.asyncio
async def test_accepted_write_triggers_render_base():
    coord = _make_coord()
    coord._render_base = AsyncMock()
    coord.render_base = coord._render_base
    ent = _make_entity(coord)

    with patch(_PATCH_TARGET, new_callable=AsyncMock):
        await ent.async_select_option("90°")

    coord._render_base.assert_awaited_once()


@pytest.mark.asyncio
async def test_accepted_write_broadcasts_after_render():
    """Broadcast -> render -> broadcast, in that order (camera token
    rotation needs the render to complete before the second broadcast)."""
    coord = _make_coord()
    call_order: list[str] = []

    async def _fake_render():
        call_order.append("render")

    async def _fake_write(*a, **k):
        call_order.append("write")

    coord._render_base = _fake_render
    coord.render_base = coord._render_base
    coord.async_update_listeners = MagicMock(
        side_effect=lambda: call_order.append("broadcast")
    )
    ent = _make_entity(coord)

    with patch(_PATCH_TARGET, new=_fake_write):
        await ent.async_select_option("90°")

    assert call_order == ["write", "render", "broadcast"]


@pytest.mark.asyncio
async def test_rejected_write_does_not_render():
    """A rejected write raises inside pre_settings_optimistic_write (after
    reverting the optimistic value) — the render call must never be reached,
    since nothing changed relative to the pre-write PNG."""
    coord = _make_coord()
    coord._render_base = AsyncMock()
    coord.render_base = coord._render_base
    ent = _make_entity(coord)

    async def _fake_write_raises(*a, **k):
        raise HomeAssistantError("rejected")

    with patch(_PATCH_TARGET, new=_fake_write_raises):
        with pytest.raises(HomeAssistantError):
            await ent.async_select_option("90°")

    coord._render_base.assert_not_awaited()
    coord.async_update_listeners.assert_not_called()
