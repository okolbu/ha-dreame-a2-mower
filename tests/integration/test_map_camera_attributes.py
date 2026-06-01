"""DreameA2MapCamera.extra_state_attributes — live-map rehaul surface.

The map camera now serves the BASE png (lawn + background only) and publishes
the live position stream + map projection so the bundled card draws the trail +
mower icon client-side. The old `calibration_points` block (consumed by the
retired LiDAR-texture approach) is gone.
"""
from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock


def _make_camera(*, base_png=b"\x89PNGbase", position=None, heading=None):
    from custom_components.dreame_a2_mower.camera import DreameA2MapCamera
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.mower.state_machine import MowerStateMachine

    md = SimpleNamespace(
        name="Main Lawn",
        bx1=0.0, by1=0.0, bx2=20000.0, by2=21000.0,
        pixel_size_mm=50.0, width_px=400, height_px=420,
        nav_paths=(),
    )
    cloud_state = SimpleNamespace(
        maps_by_id={0: md},
        forbidden_node_types_by_map={},
        settings=SimpleNamespace(raw=[]),
    )
    coord = object.__new__(DreameA2MowerCoordinator)
    coord._base_png = base_png
    coord._base_png_mode = SimpleNamespace(value="green")
    coord._live_point_seq = 7
    coord._latest_point = [1.0, 2.0, 90.0, 1234.0]
    coord._track_snapshot = [[0.0, 0.0, None, 1230.0], [1.0, 2.0, 90.0, 1234.0]]
    coord.cloud_state = cloud_state
    coord._active_map_id = 0
    sm = MowerStateMachine()
    if position is not None:
        sm.handle_position(
            x_m=position[0], y_m=position[1],
            north_m=None, east_m=None, heading_deg=heading, now_unix=1000,
        )
    coord.state_machine = sm
    coord._cloud = MagicMock()
    coord._cloud.model = "dreame.mower.g2408"
    coord._cloud.mac_address = None
    coord.entry = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.data = MagicMock()
    coord.data.hardware_serial = None

    return DreameA2MapCamera(coord)


def test_async_camera_image_returns_base_png():
    cam = _make_camera(base_png=b"\x89PNGbasebytes")
    result = asyncio.run(cam.async_camera_image())
    assert result == b"\x89PNGbasebytes"


def test_extra_state_attributes_exposes_map_projection():
    attrs = _make_camera().extra_state_attributes
    proj = attrs["map_projection"]
    assert proj["bx2_mm"] == 20000.0
    assert proj["by2_mm"] == 21000.0
    assert proj["pixel_size_mm"] == 50.0
    assert proj["width_px"] == 400
    assert proj["height_px"] == 420


def test_extra_state_attributes_exposes_live_stream():
    attrs = _make_camera().extra_state_attributes
    assert attrs["point_seq"] == 7
    assert attrs["latest_point"] == [1.0, 2.0, 90.0, 1234.0]
    assert attrs["track_snapshot"] == [
        [0.0, 0.0, None, 1230.0],
        [1.0, 2.0, 90.0, 1234.0],
    ]


def test_extra_state_attributes_exposes_background_mode():
    attrs = _make_camera().extra_state_attributes
    assert attrs["background_mode"] == "green"


def test_extra_state_attributes_image_version_is_base_png_hash():
    cam = _make_camera(base_png=b"\x89PNGspecific")
    attrs = cam.extra_state_attributes
    assert attrs["image_version"] == hashlib.sha1(b"\x89PNGspecific").hexdigest()[:12]


def test_extra_state_attributes_has_no_calibration_points():
    attrs = _make_camera().extra_state_attributes
    assert "calibration_points" not in attrs


def test_last_known_point_none_when_no_position():
    # Fresh state machine: no telemetry position yet → no idle marker.
    attrs = _make_camera().extra_state_attributes
    assert attrs["last_known_point"] is None


def test_last_known_point_from_persisted_position():
    # Position with no heading → published with None heading.
    attrs = _make_camera(position=(1.5, -2.0)).extra_state_attributes
    assert attrs["last_known_point"] == [1.5, -2.0, None]


def test_last_known_point_includes_heading():
    # Persisted s1p4 heading is published so the idle icon faces last-travel.
    attrs = _make_camera(position=(1.5, -2.0), heading=0.0).extra_state_attributes
    assert attrs["last_known_point"] == [1.5, -2.0, 0.0]


def test_last_known_point_is_unrecorded():
    # Excluded from the recorder like the other volatile stream attrs.
    from custom_components.dreame_a2_mower.camera import DreameA2MapCamera
    assert "last_known_point" in DreameA2MapCamera._unrecorded_attributes
