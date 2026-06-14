"""Python↔JS frame-parity gate for the live-map projection.

The bundled cards project cloud-frame metres to base-PNG pixels with
``projectPoint`` in ``www/_dreame-map-core.js``.  The server renders the base
PNG with ``map_render._geometry._cloud_to_px`` plus the final
``FLIP_TOP_BOTTOM`` (``py = height_px - py_pre``).  ``extract_projection``
documents exactly this consumption contract.  If the two ever diverge, the
card's trail/icon land off the rendered lawn — a silent, browser-only break.

This test feeds the SAME projection inputs to BOTH paths (real node runs the
real JS) and asserts the pixel outputs match within a tight epsilon, including
the bbox corners.  It is the regression gate for the deferred transform-move
(see docs/TODO.md).
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

from custom_components.dreame_a2_mower.map_render._geometry import _cloud_to_px

NODE = shutil.which("node")
HARNESS = pathlib.Path(__file__).parent / "projection_parity_harness.mjs"

# Pixel epsilon: pure float arithmetic on both sides; tolerance only guards
# IEEE-754 last-bit noise across the two languages.
EPS = 1e-6


def _py_project(x_m: float, y_m: float, proj: dict) -> tuple[float, float]:
    """Project (x_m, y_m) metres -> base-PNG pixels via the SERVER path.

    Mirrors what ``extract_projection`` tells the card it does:
      cloud_x = x_m * 1000;  cloud_y = y_m * 1000
      (px, py_pre) = _cloud_to_px(cloud_x, cloud_y, bx2, by2, grid)
      py = height_px - py_pre          # FLIP_TOP_BOTTOM applied to base PNG
    """
    px, py_pre = _cloud_to_px(
        x_m * 1000.0,
        y_m * 1000.0,
        proj["bx2_mm"],
        proj["by2_mm"],
        proj["pixel_size_mm"],
    )
    py = proj["height_px"] - py_pre
    return px, py


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_js_python_projection_parity():
    r = subprocess.run(
        [NODE, str(HARNESS)], capture_output=True, text=True, timeout=30
    )
    assert r.returncode == 0, f"node harness failed:\n{r.stdout}\n{r.stderr}"
    data = json.loads(r.stdout)
    proj = data["proj"]
    points_m = data["points_m"]
    js_pixels = data["pixels"]

    assert len(points_m) >= 8, "harness must exercise bbox corners + interior"

    for (x_m, y_m), (jx, jy) in zip(points_m, js_pixels):
        px, py = _py_project(x_m, y_m, proj)
        assert abs(px - jx) < EPS and abs(py - jy) < EPS, (
            f"frame mismatch at ({x_m}, {y_m}): "
            f"python=({px}, {py}) js=({jx}, {jy})"
        )

    # Spot-check the bbox-far corner (bx2,by2) lands at x=0 and (after the flip)
    # y=height_px — proving the flip orientation, not just internal agreement.
    px0, py0 = _py_project(
        proj["bx2_mm"] / 1000.0, proj["by2_mm"] / 1000.0, proj
    )
    assert abs(px0 - 0.0) < EPS
    assert abs(py0 - proj["height_px"]) < EPS
