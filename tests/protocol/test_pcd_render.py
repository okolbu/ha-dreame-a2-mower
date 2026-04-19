"""Tests for the PCD → top-down PNG renderer."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
import numpy as np

from protocol.pcd import parse_pcd
from protocol.pcd_render import render_top_down


def _tiny_cloud(points: list[tuple[float, float, float, int, int, int]]):
    """Build a PointCloud from an explicit point list (x, y, z, r, g, b)."""
    from protocol.pcd import PointCloud, PCDHeader

    xyz = np.array([(p[0], p[1], p[2]) for p in points], dtype=np.float32)
    rgb = np.array([(p[3], p[4], p[5]) for p in points], dtype=np.uint8)
    hdr = PCDHeader(
        version="0.7",
        fields=["x", "y", "z", "rgb"],
        sizes=[4, 4, 4, 4],
        types=["F", "F", "F", "U"],
        counts=[1, 1, 1, 1],
        width=len(points),
        height=1,
        points=len(points),
        data="binary",
    )
    return PointCloud(xyz=xyz, rgb=rgb, header=hdr, bytes_per_point=16)


def test_render_returns_png_bytes():
    cloud = _tiny_cloud([(0.0, 0.0, 0.0, 0, 255, 0)])
    png = render_top_down(cloud, width=32, height=32)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_render_dimensions_match_request():
    cloud = _tiny_cloud([(0.0, 0.0, 0.0, 0, 255, 0)])
    png = render_top_down(cloud, width=64, height=48)
    img = Image.open(io.BytesIO(png))
    assert img.size == (64, 48)


def test_single_point_is_visible_in_output():
    """A cloud with one green point at origin must produce at least one
    green pixel in the PNG (not all black)."""
    cloud = _tiny_cloud([(0.0, 0.0, 0.0, 0, 255, 0)])
    png = render_top_down(cloud, width=32, height=32)
    arr = np.array(Image.open(io.BytesIO(png)).convert("RGB"))
    # some pixel must have G > 200
    assert (arr[:, :, 1] > 200).any()


def test_higher_z_point_occludes_lower_z_at_same_pixel():
    """Two points projecting to the same pixel should show the taller
    point's color (roof over grass), not blend them."""
    # both map to image center; first is grass (green, z=0), second is
    # roof (red, z=5). The roof should win.
    cloud = _tiny_cloud([
        (0.0, 0.0, 0.0, 0, 255, 0),   # green grass
        (0.0, 0.0, 5.0, 255, 0, 0),   # red roof, taller
    ])
    png = render_top_down(cloud, width=64, height=64, margin_px=0)
    arr = np.array(Image.open(io.BytesIO(png)).convert("RGB"))
    nonblack = (arr.sum(axis=2) > 0)
    assert nonblack.any(), "expected at least one rendered pixel"
    r = arr[:, :, 0][nonblack].max()
    g = arr[:, :, 1][nonblack].max()
    assert r > g, f"expected red roof on top; got max R={r}, max G={g}"


def test_aspect_ratio_preserved(tmp_path: Path):
    """A cloud spanning 20m×10m (2:1) rendered into a 200×200 image should
    still keep the 2:1 aspect — i.e., only use ~half the height."""
    cloud = _tiny_cloud([
        (0.0, 0.0, 0.0, 0, 255, 0),
        (20.0, 10.0, 0.0, 0, 255, 0),
        (0.0, 10.0, 0.0, 0, 255, 0),
        (20.0, 0.0, 0.0, 0, 255, 0),
    ])
    png = render_top_down(cloud, width=200, height=200, background=(0, 0, 0))
    arr = np.array(Image.open(io.BytesIO(png)).convert("RGB"))
    # Find the bounding box of non-black pixels
    nonblack = arr.sum(axis=2) > 0
    ys, xs = np.where(nonblack)
    if len(xs) == 0:
        raise AssertionError("no rendered pixels")
    w = xs.max() - xs.min()
    h = ys.max() - ys.min()
    # 2:1 aspect → w ≈ 2*h (with small margin tolerance)
    assert w > h, f"expected w > h for a 2:1 cloud; got w={w} h={h}"
    # roughly 2:1 (allow ±30% slack for margins and pixel discretisation)
    ratio = w / max(h, 1)
    assert 1.5 < ratio < 2.8, f"aspect ratio {ratio:.2f} not ≈ 2.0"


def test_full_fixture_renders_without_error(fixtures_dir: Path):
    """Smoke test on the real 145k-point capture."""
    data = (fixtures_dir / "lidar_sample.pcd").read_bytes()
    cloud = parse_pcd(data)
    png = render_top_down(cloud, width=256, height=256)
    img = Image.open(io.BytesIO(png)).convert("RGB")
    arr = np.array(img)
    # Expect a substantial fraction of pixels to be painted (ground plane visible)
    painted = (arr.sum(axis=2) > 0).sum()
    assert painted > 256 * 256 * 0.05, f"only {painted} pixels painted"
