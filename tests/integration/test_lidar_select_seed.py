"""Regression: the LiDAR archive select seeds the coordinator's render entry
to its displayed default, so /lidar/selected.pcd serves the default scan
instead of 404-ing until the user re-picks (P5.5 eyeball finding — the view's
None-fallback keys off _active_map_id, which is None while the mower is offline).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.entities.select.global_ import (
    DreameA2LidarArchiveSelect,
)


def _entry(filename: str, unix_ts: int) -> SimpleNamespace:
    return SimpleNamespace(filename=filename, unix_ts=unix_ts)


def _make_select(entries, render_entry):
    coord = MagicMock()
    coord._lidar_render_entry = render_entry
    coord.list_lidar_archive_entries.return_value = entries
    sel = DreameA2LidarArchiveSelect.__new__(DreameA2LidarArchiveSelect)
    sel.coordinator = coord
    return sel, coord


def test_rebuild_seeds_render_entry_from_default_when_none():
    entries = [(0, _entry("scan_newest.pcd", 200)), (0, _entry("scan_older.pcd", 100))]
    sel, coord = _make_select(entries, render_entry=None)
    sel._rebuild_options()
    # Seeded to the FIRST (displayed default) entry, so the pcd view serves it.
    assert coord._lidar_render_entry == (0, "scan_newest.pcd")
    # Displayed current option matches the seeded scan.
    assert sel._attr_current_option == sel._format_option(0, entries[0][1])


def test_rebuild_no_seed_when_no_entries():
    sel, coord = _make_select([], render_entry=None)
    sel._rebuild_options()
    # Nothing to seed → render entry stays None, placeholder shown.
    assert coord._lidar_render_entry is None
    assert sel._attr_current_option == sel._placeholder


def test_rebuild_preserves_explicit_selection():
    entries = [(1, _entry("a.pcd", 200)), (1, _entry("b.pcd", 100))]
    sel, coord = _make_select(entries, render_entry=(1, "b.pcd"))
    # The explicit-selection branch resolves the label via lidar_archives.
    coord.lidar_archives = {1: SimpleNamespace(entries=lambda: [entries[0][1], entries[1][1]])}
    sel._rebuild_options()
    # An explicit selection is not overwritten by the default-seed path.
    assert coord._lidar_render_entry == (1, "b.pcd")
    assert sel._attr_current_option == sel._format_option(1, entries[1][1])
