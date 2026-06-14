"""Golden-image safety net for the map render pipeline (P3a transform-move).

This is the regression gate for the upcoming output-preserving render
refactor (`refactor/p3a-transform-move`). The refactor will move the
rotation + midline-reflection transform out of decode-time
(`parse_cloud_map`) and into a `map_render` presentation step. The
END-TO-END output — cloud-map JSON → ``parse_cloud_map`` → ``render_base_map``
→ PNG — MUST stay pixel-identical across that move. This test pins the
CURRENT rendered pixels so a future change to the transform's placement
(or to any render constant) fails loudly.

Fixture
-------
``tests/fixtures/cloud_map_golden.json`` is a real-shaped cloud-map JSON that
exercises EVERY transformed render path:

  - a **rotated polygon** no-go exclusion (``forbiddenAreas`` id 101, angle
    −30.77° — decode-time centroid rotation + midline reflection),
  - a **circle** no-go exclusion (id 102 — the cloud represents circles as a
    multi-point polygon; the decoder has no radius concept, it rotates+reflects
    the points like any polygon),
  - a **LINE** no-go exclusion (id 103 — a 2-point forbidden area; this is the
    KNOWN BUG: ``render_base_map`` skips polygons with ``< 3`` points, so it
    renders INVISIBLE. The golden pins that it stays invisible.),
  - an **ignore-obstacle** zone (``notObsAreas`` id 201, subtype="ignore"),
  - a **spot area** (``spotAreas`` id 301, angle 15° — rotated + reflected),
  - **clean / maintenance points** (``cleanPoints`` — "M" glyph markers),
  - **patrol / cruise points** (``cruisePoints`` type=8 — "P" glyph markers),
  - a **nav path** (``paths`` — gray polyline),
  - a **dock** position (charger, post-reflection + ``CHARGER_OFFSET_MM``),
  - a **contour** outline and the **mowing-zone boundary** (the lawn polygon).

Comparison strategy
-------------------
PNG file bytes are NOT compared (the zlib/PNG encoder is not guaranteed
byte-stable across PIL/zlib versions). Instead we compare the DECODED PIXEL
ARRAY: both the freshly-rendered PNG and the committed golden PNG are loaded
via PIL, normalised to RGBA, and their raw ``tobytes()`` pixel buffers are
sha256-hashed and compared. Same fixture → same pixels → same hash, every run.

Pinned bugs (see docs/TODO.md "Base-map render drops line no-go zones …")
-------------------------------------------------------------------------
The line-type (2-point) no-go is ABSENT from the golden render. The golden
captures the current (buggy) behaviour on purpose — the transform-move must
NOT make it visible. ``test_line_nogo_is_invisible_in_golden`` documents and
guards this.

Regenerating the golden
-----------------------
Only when the render output is *intentionally* changed (e.g. the post-3a TODO
that fixes the line-nogo bug). Run with ``DREAME_REGEN_GOLDEN=1`` set:

    DREAME_REGEN_GOLDEN=1 .venv-vanilla/bin/python -m pytest \
        tests/integration/test_map_render_golden.py -q

and commit the updated ``tests/fixtures/cloud_map_render_golden.png``.
"""
from __future__ import annotations

import hashlib
import io
import os
import pathlib
import sys

import pytest

# ---------------------------------------------------------------------------
# Path wiring — same as test_map_decoder.py / test_map_render.py.
# ---------------------------------------------------------------------------
_REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_FIXTURE_JSON = _REPO_ROOT / "tests" / "fixtures" / "cloud_map_golden.json"
_GOLDEN_PNG = _REPO_ROOT / "tests" / "fixtures" / "cloud_map_render_golden.png"

from custom_components.dreame_a2_mower.map_decoder import parse_cloud_map  # noqa: E402
from custom_components.dreame_a2_mower.map_render import render_base_map  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_fixture() -> dict:
    import json

    with open(_FIXTURE_JSON, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _map_data():
    md = parse_cloud_map(_load_fixture())
    assert md is not None, "parse_cloud_map returned None for the golden fixture"
    return md


def _render_png() -> bytes:
    """Render the golden fixture's base map to PNG bytes (current code)."""
    return render_base_map(_map_data())


def _pixel_hash(png_bytes: bytes) -> str:
    """sha256 of the decoded RGBA pixel buffer (encoder-independent)."""
    from PIL import Image

    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    return hashlib.sha256(img.tobytes()).hexdigest()


# ---------------------------------------------------------------------------
# Optional regeneration — only runs when DREAME_REGEN_GOLDEN=1 is set.
# ---------------------------------------------------------------------------


def test_regenerate_golden_when_requested():
    """Write the golden PNG from the CURRENT render. Skipped unless explicitly
    requested via DREAME_REGEN_GOLDEN=1 (so it never silently overwrites the
    gate during a normal run)."""
    if os.environ.get("DREAME_REGEN_GOLDEN") != "1":
        pytest.skip("set DREAME_REGEN_GOLDEN=1 to regenerate the golden PNG")
    png = _render_png()
    _GOLDEN_PNG.write_bytes(png)
    # Sanity: the file we just wrote round-trips to the same pixels.
    assert _pixel_hash(png) == _pixel_hash(_GOLDEN_PNG.read_bytes())


# ---------------------------------------------------------------------------
# Fixture-population guards — confirm parse_cloud_map exercised every path.
# ---------------------------------------------------------------------------


class TestFixturePopulatesEveryTransformedPath:
    """parse_cloud_map must populate every transformed element the golden
    is meant to cover; otherwise the gate would silently cover nothing."""

    def test_mowing_zone_present(self):
        md = _map_data()
        assert len(md.mowing_zones) == 1
        assert md.mowing_zones[0].name == "Front Lawn"
        assert len(md.mowing_zones[0].path) == 4

    def test_rotated_polygon_exclusion_present(self):
        """The angle=-30.77 forbidden area is rotated+reflected (≠ raw)."""
        md = _map_data()
        rot = [ez for ez in md.exclusion_zones if ez.obj_id == 101]
        assert len(rot) == 1
        ez = rot[0]
        assert ez.subtype is None  # classic red no-go
        assert len(ez.points) == 4
        # Decode applied rotation+reflection: first decoded corner differs
        # from the raw input corner (12819.85, 12543.97).
        dx, dy = ez.points[0]
        assert abs(dx - 12819.85) > 1 or abs(dy - 12543.97) > 1

    def test_circle_exclusion_present(self):
        """Circle no-go decodes as a multi-point polygon (≥3 → renders)."""
        md = _map_data()
        circ = [ez for ez in md.exclusion_zones if ez.obj_id == 102]
        assert len(circ) == 1
        assert len(circ[0].points) == 16  # 16-point circle approximation

    def test_line_exclusion_present_but_two_point(self):
        """The LINE no-go decodes as a 2-point exclusion (the bug input)."""
        md = _map_data()
        line = [ez for ez in md.exclusion_zones if ez.obj_id == 103]
        assert len(line) == 1
        assert len(line[0].points) == 2  # 2 points → render skips it

    def test_ignore_zone_present(self):
        md = _map_data()
        ig = [ez for ez in md.exclusion_zones if ez.subtype == "ignore"]
        assert len(ig) == 1
        assert len(ig[0].points) == 4

    def test_spot_zone_present(self):
        md = _map_data()
        assert len(md.spot_zones) == 1
        assert md.spot_zones[0].spot_id == 301
        assert md.spot_zones[0].name == "Patio Spot"
        assert len(md.spot_zones[0].points) == 4

    def test_maintenance_points_present(self):
        md = _map_data()
        assert len(md.maintenance_points) == 2

    def test_patrol_points_present(self):
        md = _map_data()
        assert len(md.patrol_points) == 1
        assert md.patrol_points[0].point_id == 1

    def test_nav_path_present(self):
        md = _map_data()
        assert len(md.nav_paths) == 1
        assert len(md.nav_paths[0].path) == 3

    def test_contour_present(self):
        md = _map_data()
        assert len(md.contour_paths) == 1
        assert md.available_contour_ids == ((1, 0),)

    def test_dock_present(self):
        md = _map_data()
        assert md.dock_xy is not None

    def test_boundary_polygon_present(self):
        md = _map_data()
        assert len(md.boundary_polygon) == 4


# ---------------------------------------------------------------------------
# The golden-image gate.
# ---------------------------------------------------------------------------


class TestGoldenRender:
    def test_golden_asset_exists(self):
        assert _GOLDEN_PNG.exists(), (
            f"golden PNG missing at {_GOLDEN_PNG}; regenerate with "
            "DREAME_REGEN_GOLDEN=1"
        )

    def test_render_is_pixel_identical_to_golden(self):
        """The CURRENT render reproduces the committed golden's pixels exactly.

        Compares the decoded RGBA pixel buffer (sha256), NOT the PNG file
        bytes — so the gate is immune to PNG-encoder nondeterminism but
        catches any change to the rendered pixels.
        """
        rendered = _render_png()
        got = _pixel_hash(rendered)
        want = _pixel_hash(_GOLDEN_PNG.read_bytes())
        assert got == want, (
            "Rendered map pixels diverged from the golden. If this is an "
            "INTENTIONAL render change, regenerate the golden with "
            "DREAME_REGEN_GOLDEN=1 and review the diff. The P3a transform-move "
            "must keep this pixel-identical.\n"
            f"  golden pixel-hash : {want}\n"
            f"  current pixel-hash: {got}"
        )

    def test_golden_dimensions_match_map_data(self):
        """Golden canvas is width_px × height_px from the decoded map."""
        from PIL import Image

        md = _map_data()
        img = Image.open(io.BytesIO(_GOLDEN_PNG.read_bytes()))
        assert (img.width, img.height) == (md.width_px, md.height_px)

    def test_render_is_deterministic(self):
        """Two fresh renders of the same fixture produce identical pixels."""
        a = _pixel_hash(_render_png())
        b = _pixel_hash(_render_png())
        assert a == b, "render is non-deterministic for a fixed fixture"


# ---------------------------------------------------------------------------
# Pinned-bug guards — the golden captures current (buggy) behaviour.
# ---------------------------------------------------------------------------


class TestGoldenPinsKnownRenderBugs:
    """docs/TODO.md "Base-map render drops line no-go zones + novelty shapes".

    These are PINNED, not fixed: the output-preserving P3a refactor must keep
    the current (buggy) render. Fixing them is the post-3a TODO, which will
    regenerate the golden to expect the corrected render.
    """

    def test_line_nogo_decoded_but_below_render_threshold(self):
        """The line no-go is present in MapData but has < 3 points, so
        ``render_base_map`` skips it (the invisible-line bug). The golden —
        rendered from this same MapData — therefore does NOT draw it."""
        md = _map_data()
        line = [ez for ez in md.exclusion_zones if ez.obj_id == 103]
        assert len(line) == 1
        assert len(line[0].points) < 3, (
            "line no-go must stay 2-point so the render's >=3 guard skips it"
        )

    def test_line_nogo_absent_from_render_via_ablation(self):
        """Render-level proof the line no-go contributes NO pixels.

        Re-parse the fixture, drop the 2-point line exclusion from the
        MapData, render that, and confirm the pixels are IDENTICAL to the
        full-fixture render. If the line were drawn, removing it would change
        pixels — so identical hashes prove it draws nothing (the pinned bug).
        """
        import dataclasses

        md_full = _map_data()
        kept = tuple(ez for ez in md_full.exclusion_zones if ez.obj_id != 103)
        assert len(kept) == len(md_full.exclusion_zones) - 1
        md_no_line = dataclasses.replace(md_full, exclusion_zones=kept)

        with_line = _pixel_hash(render_base_map(md_full))
        without_line = _pixel_hash(render_base_map(md_no_line))
        assert with_line == without_line, (
            "removing the 2-point line no-go changed the render — it is NOT "
            "invisible as the pinned bug asserts"
        )
