"""Tests for the stateful TrailLayer overlay compositor."""

from __future__ import annotations

import io

from PIL import Image
import numpy as np

from protocol.trail_overlay import TrailLayer, _affine_from_calibration


CALIBRATION = [
    {"mower": {"x": 0, "y": 0}, "map": {"x": 100, "y": 100}},
    {"mower": {"x": 1000, "y": 0}, "map": {"x": 200, "y": 100}},
    {"mower": {"x": 0, "y": 1000}, "map": {"x": 100, "y": 200}},
]


def _blank_png(w: int = 256, h: int = 256, color=(0, 0, 0)) -> bytes:
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _red_pixels(png_bytes: bytes) -> int:
    arr = np.array(Image.open(io.BytesIO(png_bytes)).convert("RGB"))
    return int(((arr[:, :, 0] > 150) & (arr[:, :, 1] < 100) & (arr[:, :, 2] < 100)).sum())


# ---------- affine ----------

def test_affine_forward_maps_calibration_anchors():
    a, b, c, d, tx, ty = _affine_from_calibration(CALIBRATION)
    assert abs(tx - 100.0) < 1e-6 and abs(ty - 100.0) < 1e-6
    assert abs(a * 1000 + tx - 200.0) < 1e-6
    assert abs(d * 1000 + ty - 200.0) < 1e-6


def test_affine_rejects_colinear():
    with pytest.raises(ValueError):
        _affine_from_calibration([
            {"mower": {"x": 0, "y": 0}, "map": {"x": 0, "y": 0}},
            {"mower": {"x": 1, "y": 0}, "map": {"x": 1, "y": 0}},
            {"mower": {"x": 2, "y": 0}, "map": {"x": 2, "y": 0}},
        ])


# ---------- live path ----------

def test_first_live_point_does_not_draw():
    """Nothing to connect to on the first point; layer should remain empty."""
    layer = TrailLayer(base_size=(256, 256), calibration=CALIBRATION)
    layer.extend_live([0.0, 0.0])
    png = layer.compose(_blank_png())
    assert _red_pixels(png) == 0


def test_second_live_point_draws_segment():
    layer = TrailLayer(base_size=(256, 256), calibration=CALIBRATION)
    layer.extend_live([0.0, 0.0])
    layer.extend_live([1.0, 0.0])
    png = layer.compose(_blank_png())
    assert _red_pixels(png) > 0


def test_version_bumps_on_each_new_segment():
    layer = TrailLayer(base_size=(256, 256), calibration=CALIBRATION)
    v0 = layer.version
    layer.extend_live([0.0, 0.0])
    # First point — no drawing, no bump.
    assert layer.version == v0
    layer.extend_live([1.0, 0.0])
    v1 = layer.version
    assert v1 > v0
    layer.extend_live([1.0, 1.0])
    assert layer.version > v1


def test_compose_is_idempotent_without_changes():
    layer = TrailLayer(base_size=(256, 256), calibration=CALIBRATION)
    layer.extend_live([0.0, 0.0])
    layer.extend_live([1.0, 0.0])
    png1 = layer.compose(_blank_png())
    png2 = layer.compose(_blank_png())
    assert png1 == png2


# ---------- replay / reset ----------

def test_reset_clears_trail():
    layer = TrailLayer(base_size=(256, 256), calibration=CALIBRATION)
    layer.extend_live([0.0, 0.0])
    layer.extend_live([1.0, 0.0])
    layer.reset()
    png = layer.compose(_blank_png())
    assert _red_pixels(png) == 0


def test_reset_to_session_paints_completed_track():
    layer = TrailLayer(base_size=(256, 256), calibration=CALIBRATION)
    layer.reset_to_session(
        completed_track=[
            [[0.0, 0.0], [0.5, 0.0], [1.0, 0.0]],
            [[0.0, 0.5], [0.5, 0.5]],
        ],
    )
    png = layer.compose(_blank_png())
    assert _red_pixels(png) > 0


def test_reset_to_session_accepts_flat_path_too():
    layer = TrailLayer(base_size=(256, 256), calibration=CALIBRATION)
    layer.reset_to_session(path=[[0.0, 0.0], [1.0, 0.0]])
    png = layer.compose(_blank_png())
    assert _red_pixels(png) > 0


def test_dock_marker_renders_green():
    layer = TrailLayer(base_size=(256, 256), calibration=CALIBRATION)
    layer.set_dock([0.0, 0.0])
    png = layer.compose(_blank_png())
    arr = np.array(Image.open(io.BytesIO(png)).convert("RGB"))
    green = ((arr[:, :, 1] > 130) & (arr[:, :, 0] < 100) & (arr[:, :, 2] < 100)).sum()
    assert green > 0


def test_obstacle_polygon_blends_over_base():
    layer = TrailLayer(base_size=(256, 256), calibration=CALIBRATION)
    poly = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    layer.set_obstacles([poly])
    png = layer.compose(_blank_png(color=(0, 255, 0)))
    arr = np.array(Image.open(io.BytesIO(png)).convert("RGB"))
    orange = ((arr[:, :, 0] > 100) & (arr[:, :, 1] > 50) & (arr[:, :, 1] < 200) & (arr[:, :, 2] < 100)).sum()
    assert orange > 0


# ---------- compose ----------

def test_compose_output_dimensions_match_base():
    layer = TrailLayer(base_size=(321, 123), calibration=CALIBRATION)
    layer.extend_live([0.0, 0.0])
    layer.extend_live([0.5, 0.0])
    png = layer.compose(_blank_png(w=321, h=123))
    assert Image.open(io.BytesIO(png)).size == (321, 123)


def test_compose_handles_base_size_mismatch():
    """If the base PNG changes size the trail is resized to match —
    compose still succeeds rather than throwing."""
    layer = TrailLayer(base_size=(256, 256), calibration=CALIBRATION)
    layer.extend_live([0.0, 0.0])
    layer.extend_live([1.0, 0.0])
    # Hand it a differently-sized base.
    png = layer.compose(_blank_png(w=300, h=200))
    assert Image.open(io.BytesIO(png)).size == (300, 200)


# pytest import needs to be present for `pytest.raises`
import pytest  # noqa: E402
