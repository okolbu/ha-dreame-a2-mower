"""Tests for coordinator.refresh_wifi_archive end-to-end."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

import pytest

from custom_components.dreame_a2_mower.wifi_archive_store import WifiArchiveStore


@pytest.fixture
def store_root(tmp_path: Path) -> Path:
    return tmp_path / "wifi_archive"


async def _run_refresh(coord_klass, store_root: Path, cloud_objects: list[dict]):
    """Build a minimal coordinator-like object, run refresh_wifi_archive."""
    coord = object.__new__(coord_klass)
    coord._wifi_archive_store = WifiArchiveStore(store_root)
    coord._wifi_archive_index = []
    coord._cloud = MagicMock()
    coord._cloud.list_wifi_candidates = MagicMock(
        return_value=cloud_objects
    )
    coord._cloud.get_interim_file_url = MagicMock(
        side_effect=lambda name: f"https://oss/{name}"
    )
    coord._cloud.get_file = MagicMock(
        side_effect=lambda url: json.dumps(
            {"data": [-50] * 16, "width": 4, "height": 4, "resolution": 2,
             "startX": 0, "startY": 0}
        ).encode()
    )
    coord.hass = MagicMock()
    coord.hass.async_add_executor_job = AsyncMock(
        side_effect=lambda fn, *args: fn(*args)
    )
    coord.async_update_listeners = MagicMock()
    # _build_map_extents is called for extents; stub to empty (no per-map info needed).
    coord._build_map_extents = MagicMock(return_value={})
    summary = await coord.refresh_wifi_archive()
    return coord, summary


@pytest.mark.asyncio
async def test_refresh_archives_new_objects(store_root: Path):
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    cloud_objects = [
        {"object_name": "wifimap_1700000001.json", "unix_ts": 1700000001,
         "map_id": None, "startX": 0, "startY": 0,
         "width": 4, "height": 4, "resolution": 2},
        {"object_name": "wifimap_1700000002.json", "unix_ts": 1700000002,
         "map_id": None, "startX": 0, "startY": 0,
         "width": 4, "height": 4, "resolution": 2},
    ]
    coord, summary = await _run_refresh(
        DreameA2MowerCoordinator, store_root, cloud_objects
    )
    assert summary["fetched"] == 2
    assert summary["new"] == 2
    assert summary["archive_total"] == 2
    # Files written.
    assert (store_root / "wifimap_1700000001.json").is_file()
    assert (store_root / "wifimap_1700000002.json").is_file()
    # In-memory index mirrors disk.
    assert len(coord._wifi_archive_index) == 2


@pytest.mark.asyncio
async def test_refresh_is_idempotent(store_root: Path):
    """Two refreshes with the same cloud state → no duplicates."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    cloud_objects = [
        {"object_name": "wifimap_1700000001.json", "unix_ts": 1700000001,
         "map_id": None, "startX": 0, "startY": 0,
         "width": 4, "height": 4, "resolution": 2},
    ]
    coord, _ = await _run_refresh(
        DreameA2MowerCoordinator, store_root, cloud_objects
    )
    # Re-run (manually, no re-instantiation — same coord + store).
    coord._cloud.list_wifi_candidates.return_value = cloud_objects
    summary2 = await coord.refresh_wifi_archive()
    assert summary2["fetched"] == 1
    assert summary2["new"] == 0
    assert summary2["archive_total"] == 1


def test_coordinator_init_sets_real_store(tmp_path: Path, monkeypatch):
    """After __init__, _wifi_archive_store must be a real WifiArchiveStore,
    not None. Regression for ef4cf4a clobber bug."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    import inspect
    import re

    src = inspect.getsource(DreameA2MowerCoordinator.__init__)
    assert "self._wifi_archive_store" in src, (
        "__init__ should initialise _wifi_archive_store"
    )
    # Must NOT contain a `= None` assignment for that attribute.
    # Use MULTILINE so ^ anchors per-line; check each line individually.
    clobber_pattern = re.compile(
        r"self\._wifi_archive_store\s*(?::\s*\S+\s*)?\=\s*None"
    )
    for line in src.splitlines():
        assert clobber_pattern.search(line) is None, (
            f"Regression: __init__ has a `_wifi_archive_store = None` clobber: {line!r}"
        )


@pytest.mark.asyncio
async def test_refresh_keeps_cloud_garbage_collected_entries(store_root: Path):
    """If cloud drops an object that's already archived, archive keeps it."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    cloud_first = [
        {"object_name": "wifimap_1700000001.json", "unix_ts": 1700000001,
         "map_id": None, "startX": 0, "startY": 0,
         "width": 4, "height": 4, "resolution": 2},
        {"object_name": "wifimap_1700000002.json", "unix_ts": 1700000002,
         "map_id": None, "startX": 0, "startY": 0,
         "width": 4, "height": 4, "resolution": 2},
    ]
    coord, _ = await _run_refresh(
        DreameA2MowerCoordinator, store_root, cloud_first
    )
    coord._cloud.list_wifi_candidates.return_value = cloud_first[:1]
    await coord.refresh_wifi_archive()
    assert len(coord._wifi_archive_index) == 2


@pytest.mark.asyncio
async def test_refresh_enforces_retention_after_tagging(store_root: Path):
    """refresh_wifi_archive prunes the archive to the per-map retention cap
    once new heatmaps are downloaded (and after the tagging pass)."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    cloud_objects = [
        {"object_name": f"wifimap_17000000{i:02d}.json",
         "unix_ts": 1700000000 + i, "map_id": None, "startX": 0, "startY": 0,
         "width": 4, "height": 4, "resolution": 2}
        for i in (1, 2, 3)
    ]
    coord = object.__new__(DreameA2MowerCoordinator)
    coord._wifi_archive_store = WifiArchiveStore(store_root)
    coord._wifi_archive_store.set_retention(2)  # keep newest 2 per map
    coord._wifi_archive_index = []
    coord._cloud = MagicMock()
    coord._cloud.list_wifi_candidates = MagicMock(return_value=cloud_objects)
    coord._cloud.get_interim_file_url = MagicMock(
        side_effect=lambda name: f"https://oss/{name}"
    )
    coord._cloud.get_file = MagicMock(
        side_effect=lambda url: json.dumps(
            {"data": [-50] * 16, "width": 4, "height": 4, "resolution": 2,
             "startX": 0, "startY": 0}
        ).encode()
    )
    coord.hass = MagicMock()
    coord.hass.async_add_executor_job = AsyncMock(
        side_effect=lambda fn, *args: fn(*args)
    )
    coord.async_update_listeners = MagicMock()
    coord._build_map_extents = MagicMock(return_value={})

    summary = await coord.refresh_wifi_archive()

    # All three were fetched, but the archive is pruned to the cap of 2.
    assert summary["fetched"] == 3
    assert len(coord._wifi_archive_store.load_index()) == 2
    names = {e.object_name for e in coord._wifi_archive_store.load_index()}
    assert "wifimap_1700000001.json" not in names  # oldest pruned
    assert names == {"wifimap_1700000002.json", "wifimap_1700000003.json"}


@pytest.mark.asyncio
async def test_periodic_archive_refresh_rearms_lidar_and_refreshes_wifi():
    """The periodic archive timer re-runs the WiFi re-list AND re-arms the
    one-shot LiDAR 3dmap backfill, so a long-running integration picks up new
    maps without waiting for a restart."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    coord = object.__new__(DreameA2MowerCoordinator)
    # The boot backfill already ran this session.
    coord._lidar_backfill_done = True
    coord.refresh_wifi_archive = AsyncMock()

    flag_at_backfill = {}

    async def _fake_backfill(now_unix):
        # Capture the flag state as the backfill is entered — it must have
        # been reset to False so the re-list is allowed to run.
        flag_at_backfill["value"] = coord._lidar_backfill_done

    coord._backfill_lidar_from_3dmap = AsyncMock(side_effect=_fake_backfill)

    await coord._periodic_archive_refresh()

    coord._backfill_lidar_from_3dmap.assert_awaited_once()
    coord.refresh_wifi_archive.assert_awaited_once()
    assert flag_at_backfill["value"] is False  # re-armed before re-list


def test_init_configures_wifi_retention():
    """__init__ wires the WiFi archive retention cap (from options/defaults)
    onto the store, so accumulation is bounded — regression guard."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    import inspect
    src = inspect.getsource(DreameA2MowerCoordinator.__init__)
    assert "_wifi_archive_store.set_retention" in src


def test_periodic_archive_timer_is_registered():
    """The setup path registers the periodic archive re-list timer — guards
    against the freshness wiring silently disappearing."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    import inspect
    src = inspect.getsource(DreameA2MowerCoordinator._async_update_data)
    assert "_periodic_archive_refresh" in src
