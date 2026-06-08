"""Coordinator-side active-map WiFi overlay accessor.

The live-map card reads camera.dreame_a2_mower_map.attributes.wifi_overlay;
that attribute is built by DreameA2MowerCoordinator.active_map_wifi_overlay,
which resolves the newest archived heatmap tagged with the ACTIVE map_id and
emits its cell grid in metre units (cm->m converted here)."""
from __future__ import annotations

from pathlib import Path

from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.wifi_archive_store import WifiArchiveStore


def _build_coord(tmp_path: Path):
    coord = object.__new__(DreameA2MowerCoordinator)
    coord._wifi_archive_store = WifiArchiveStore(tmp_path / "wifi_archive")
    coord._wifi_archive_index = []
    coord._wifi_body_cache = {}
    coord._active_map_id = None
    return coord


def _archive_heatmap(coord, *, object_name, map_id, width, height, res_m,
                     start_x_m, start_y_m, fill_dbm=-55, unix_ts=1000):
    body = {
        "data": [fill_dbm] * (width * height),
        "width": width, "height": height, "resolution": res_m,
        "startX": int(start_x_m * 100), "startY": int(start_y_m * 100),
    }
    store = coord._wifi_archive_store
    store.archive(object_name, body, first_seen_unix=unix_ts)
    # Tag with map_id + refresh the in-memory index the accessor reads.
    store.set_map_id(object_name, map_id)
    coord._wifi_archive_index = store.load_index()
    return body


def test_overlay_none_when_no_active_map(tmp_path):
    coord = _build_coord(tmp_path)
    assert coord.active_map_wifi_overlay is None


def test_overlay_none_when_body_not_cached(tmp_path):
    coord = _build_coord(tmp_path)
    _archive_heatmap(coord, object_name="hm1", map_id=0, width=2, height=2,
                     res_m=2, start_x_m=1.0, start_y_m=3.0)
    coord._active_map_id = 0
    # Entry resolves, but body has not been loaded into the cache yet.
    assert coord.active_map_wifi_overlay is None


def test_overlay_payload_shape_when_cached(tmp_path):
    coord = _build_coord(tmp_path)
    body = _archive_heatmap(coord, object_name="hm1", map_id=0, width=2,
                            height=3, res_m=2, start_x_m=1.0, start_y_m=3.0)
    coord._active_map_id = 0
    coord._wifi_body_cache["hm1"] = body  # simulate a completed load
    overlay = coord.active_map_wifi_overlay
    assert overlay is not None
    assert overlay["width"] == 2 and overlay["height"] == 3
    assert overlay["data"] == body["data"]
    assert overlay["resolution_m"] == 2.0
    assert overlay["start_x_m"] == 1.0   # cm -> m
    assert overlay["start_y_m"] == 3.0


def test_overlay_ignores_other_map(tmp_path):
    coord = _build_coord(tmp_path)
    body = _archive_heatmap(coord, object_name="hm9", map_id=9, width=2,
                            height=2, res_m=2, start_x_m=0.0, start_y_m=0.0)
    coord._wifi_body_cache["hm9"] = body
    coord._active_map_id = 0  # different map -> no entry
    assert coord.active_map_wifi_overlay is None
