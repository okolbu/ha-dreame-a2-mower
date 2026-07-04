"""Coordinator cloud-state refresh + map-render tests (domain/render + cloud_state).

Split out of the test_coordinator.py monolith (P3.11); tests moved verbatim.
"""
from __future__ import annotations


from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from tests.integration._coordinator_helpers import (
    _empty_cloud_state_parts,
    _make_coordinator_for_render_tests,
)


def test_refresh_cloud_state_syncs_map_subdevices():
    """_refresh_cloud_state must call _sync_map_subdevices.

    After _refresh_map is deleted, _refresh_cloud_state is the only
    startup/periodic path that creates per-map devices (the MQTT MAPL
    path is push-only). Guard against silently dropping that sync.
    """
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    coord = object.__new__(DreameA2MowerCoordinator)
    coord._cloud = MagicMock()
    coord.hass = MagicMock()

    async def _exec(fn, *a):
        return fn(*a)

    coord.hass.async_add_executor_job.side_effect = _exec
    coord._cloud.fetch_full_cloud_state = MagicMock(return_value=_empty_cloud_state_parts())
    coord.async_update_listeners = MagicMock()

    with patch.object(coord, "_render_maps_from_cloud_state", new=AsyncMock()), \
         patch.object(coord, "_backfill_lidar_from_3dmap", new=AsyncMock()), \
         patch.object(coord, "_apply_cloud_state_to_mower_state"), \
         patch.object(coord, "_sync_map_subdevices") as m_sync:
        asyncio.run(coord._refresh_cloud_state())

    m_sync.assert_called_once()


def test_refresh_cloud_state_applies_mapl():
    """_refresh_cloud_state must drive active-map detection from cs.mapl
    (replaces the former _refresh_cfg trailing MAPL poll)."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    coord = object.__new__(DreameA2MowerCoordinator)
    coord._cloud = MagicMock()
    coord.hass = MagicMock()

    async def _exec(fn, *a):
        return fn(*a)

    coord.hass.async_add_executor_job.side_effect = _exec
    parts = _empty_cloud_state_parts()
    parts["mapl"] = [[0, 1]]  # active map row so _apply_mapl gets a real value
    coord._cloud.fetch_full_cloud_state = MagicMock(return_value=parts)
    coord.async_update_listeners = MagicMock()

    with patch.object(coord, "_render_maps_from_cloud_state", new=AsyncMock()), \
         patch.object(coord, "_backfill_lidar_from_3dmap", new=AsyncMock()), \
         patch.object(coord, "_apply_cloud_state_to_mower_state"), \
         patch.object(coord, "_sync_map_subdevices"), \
         patch.object(coord, "_apply_mapl") as m_mapl:
        asyncio.run(coord._refresh_cloud_state())

    m_mapl.assert_called_once_with([[0, 1]])


def test_render_maps_from_cloud_state_renders_base_png():
    """Each map with a changed md5 gets a base PNG rendered into the cache."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    coord, _md = _make_coordinator_for_render_tests()
    with patch(
        "custom_components.dreame_a2_mower.map_render.render_base_map",
        return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 10,
    ) as mock_base, \
         patch.object(coord, "_render_base", new=AsyncMock()), \
         patch.object(coord, "_render_active_map_base", new=AsyncMock()):
        asyncio.run(coord._render_maps_from_cloud_state())
        mock_base.assert_called_once()

    assert coord._static_map_pngs_by_id.get(0) is not None


def test_render_maps_from_cloud_state_skips_if_md5_unchanged():
    """A map whose md5 matches the last render is not re-rendered."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    coord, md = _make_coordinator_for_render_tests()
    coord._last_map_md5_by_id[0] = md.md5
    coord._static_map_pngs_by_id[0] = b"already-rendered"
    with patch(
        "custom_components.dreame_a2_mower.map_render.render_base_map",
        return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 10,
    ) as mock_base, \
         patch.object(coord, "_render_base", new=AsyncMock()), \
         patch.object(coord, "_render_active_map_base", new=AsyncMock()):
        asyncio.run(coord._render_maps_from_cloud_state())
        mock_base.assert_not_called()

    assert coord._static_map_pngs_by_id[0] == b"already-rendered"


def test_render_maps_from_cloud_state_no_ops_when_no_cloud_state():
    """No cloud_state yet -> method returns early without rendering."""
    import asyncio
    from unittest.mock import patch

    coord = object.__new__(DreameA2MowerCoordinator)
    coord.cloud_state = None
    coord._static_map_pngs_by_id = {}
    coord._last_map_md5_by_id = {}

    with patch(
        "custom_components.dreame_a2_mower.map_render.render_base_map",
    ) as mock_base:
        asyncio.run(coord._render_maps_from_cloud_state())
        mock_base.assert_not_called()

    assert coord._static_map_pngs_by_id == {}
