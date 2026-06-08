"""DreameA2MapCamera publishes wifi_overlay when the active map has a
cached heatmap body, and omits it otherwise."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock


def _make_camera(tmp_path: Path, *, with_body: bool):
    from custom_components.dreame_a2_mower.camera import DreameA2MapCamera
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.mower.state_machine import MowerStateMachine
    from custom_components.dreame_a2_mower.wifi_archive_store import WifiArchiveStore

    md = SimpleNamespace(
        name="Main Lawn", bx1=0.0, by1=0.0, bx2=20000.0, by2=21000.0,
        pixel_size_mm=50.0, width_px=400, height_px=420, nav_paths=(),
    )
    cloud_state = SimpleNamespace(
        maps_by_id={0: md}, forbidden_node_types_by_map={},
        settings=SimpleNamespace(raw=[]),
    )
    coord = object.__new__(DreameA2MowerCoordinator)
    coord._base_png = b"\x89PNGbase"
    coord._base_png_mode = SimpleNamespace(value="green")
    coord._live_point_seq = 0
    coord._latest_point = None
    coord._track_snapshot = []
    coord.cloud_state = cloud_state
    coord._active_map_id = 0
    coord.state_machine = MowerStateMachine()
    coord._cloud = MagicMock()
    coord._cloud.model = "dreame.mower.g2408"
    coord._cloud.mac_address = None
    coord.entry = MagicMock(); coord.entry.entry_id = "e"
    coord.data = MagicMock(); coord.data.hardware_serial = None

    store = WifiArchiveStore(tmp_path / "wifi")
    body = {"data": [-55, -60, -70, 1], "width": 2, "height": 2,
            "resolution": 2, "startX": 100, "startY": 300}
    store.archive("hm1", body, first_seen_unix=1000)
    store.set_map_id("hm1", 0)
    coord._wifi_archive_store = store
    coord._wifi_archive_index = store.load_index()
    coord._wifi_body_cache = {"hm1": body} if with_body else {}

    return DreameA2MapCamera(coord)


def test_wifi_overlay_present_when_cached(tmp_path):
    cam = _make_camera(tmp_path, with_body=True)
    attrs = cam.extra_state_attributes
    assert "wifi_overlay" in attrs
    o = attrs["wifi_overlay"]
    assert o["width"] == 2 and o["height"] == 2
    assert o["start_x_m"] == 1.0 and o["start_y_m"] == 3.0
    assert o["resolution_m"] == 2.0


def test_wifi_overlay_absent_when_not_cached(tmp_path):
    cam = _make_camera(tmp_path, with_body=False)
    assert "wifi_overlay" not in cam.extra_state_attributes


def test_wifi_overlay_is_unrecorded(tmp_path):
    from custom_components.dreame_a2_mower.camera import DreameA2MapCamera
    assert "wifi_overlay" in DreameA2MapCamera._unrecorded_attributes
