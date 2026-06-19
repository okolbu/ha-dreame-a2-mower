"""Tests for render_base in map_render/main_view.py (Task 2).

Covers:
- render_base returns valid PNG for all four BackgroundMode values.
- PNG dimensions match MapData.width_px / height_px.
- GREEN and STRIPES (with a state that causes stripe overlay) produce different bytes.
"""
from __future__ import annotations

import dataclasses
import io
from PIL import Image

from custom_components.dreame_a2_mower.map_decoder import ExclusionZone, MapData, MowingZone
from custom_components.dreame_a2_mower.map_render.main_view import (
    render_base,
    _render_pre_start_with_stripes,
)
from custom_components.dreame_a2_mower.map_render.background import BackgroundMode
from custom_components.dreame_a2_mower.mower.state import ActionMode
from tests.map_render.conftest import make_map_data


_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _png_size(b: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(b)).size


def _map_with_exclusion() -> MapData:
    """10m × 10m map with one mowing zone and one no-go exclusion polygon.

    The exclusion ``points`` are post-rotation cloud-frame mm (P3a transform-move:
    the renderer reflects them through the bx/by midlines, then divides by
    ``pixel_size_mm``). With ``cloud_*_reflect`` = 10000 the 3000–5000mm square
    renders reflected at 5000–7000mm — still solidly inside the lawn — and paints
    red exclusion fill onto the dark-green base. (This test asserts only that red
    fill is present, not its position.)
    """
    return MapData(
        md5="test-clean-bg",
        width_px=200,
        height_px=200,
        pixel_size_mm=50.0,
        bx1=0.0,
        by1=0.0,
        bx2=10000.0,
        by2=10000.0,
        cloud_x_reflect=10000.0,
        cloud_y_reflect=10000.0,
        rotation_deg=0.0,
        boundary_polygon=(
            (0.0, 0.0), (10000.0, 0.0), (10000.0, 10000.0), (0.0, 10000.0),
        ),
        mowing_zones=(
            MowingZone(
                zone_id=1,
                name="lawn",
                path=(
                    (0.0, 0.0), (10000.0, 0.0),
                    (10000.0, 10000.0), (0.0, 10000.0),
                ),
                area_m2=100.0,
            ),
        ),
        exclusion_zones=(
            ExclusionZone(
                points=(
                    (3000.0, 3000.0), (5000.0, 3000.0),
                    (5000.0, 5000.0), (3000.0, 5000.0),
                ),
                subtype=None,
                obj_id=1,
            ),
        ),
        spot_zones=(),
        contour_paths=(),
        available_contour_ids=(),
        maintenance_points=(),
        patrol_points=(),
        dock_xy=None,
        total_area_m2=100.0,
        nav_paths=(),
    )


def _reddish_pixel_count(png_bytes: bytes) -> int:
    """Count pixels whose red dominates green+blue — the exclusion fill paints
    a strongly-red (excl_fill (177,0,0,50) alpha-composited over dark-green
    lawn) region the clean render lacks. Dark-green lawn pixels are
    green-dominant, so this isolates the exclusion fill."""
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    n = 0
    for r, g, b in img.getdata():
        if r > g + 20 and r > b + 20:
            n += 1
    return n


def test_render_base_clean_variant_same_size_fewer_exclusion_pixels():
    """The clean (exclusion_zones=()) render keeps the IDENTICAL canvas size as
    the normal base (so the card's projectPoint overlays still align), but
    drops the red exclusion fill. This is the CRITICAL INVARIANT for the
    map-editor card's clean background."""
    md = _map_with_exclusion()
    clean_md = dataclasses.replace(md, exclusion_zones=())

    normal = render_base(md, background_mode=BackgroundMode.GREEN)
    clean = render_base(clean_md, background_mode=BackgroundMode.GREEN)

    # (a) Identical pixel dimensions + coordinate mapping (projection alignment).
    assert _png_size(normal) == _png_size(clean) == (md.width_px, md.height_px), (
        f"clean render must keep the same canvas: "
        f"normal={_png_size(normal)} clean={_png_size(clean)} "
        f"md=({md.width_px}, {md.height_px})"
    )

    # (b) The normal render has red exclusion fill the clean one lacks.
    normal_red = _reddish_pixel_count(normal)
    clean_red = _reddish_pixel_count(clean)
    assert normal_red > 0, (
        "expected the normal base render to paint some red exclusion fill"
    )
    assert clean_red < normal_red, (
        f"clean render must have FEWER exclusion-coloured pixels: "
        f"clean={clean_red} normal={normal_red}"
    )


class _FakeState:
    """Minimal state stub accepted by _render_pre_start_with_stripes.

    The stripe angle now comes from the authoritative cloud field
    ``settings_mowing_direction`` (the device-maintained next-run angle),
    drawn at pixel angle ``180 - value`` — NOT inferred from the track.
    """

    def __init__(self, direction: int | None = 26) -> None:
        self.action_mode = ActionMode.ALL_AREAS
        self.settings_mowing_direction = direction
        self.settings_mowing_direction_mode = 2  # metadata only; unused by render


def test_stripes_use_settings_mowing_direction_angle():
    """The overlay angle is settings_mowing_direction itself (in pixel-map axes),
    read straight from the stored cloud field — no track inference.

    Frame: our rendered map reads 0°=left/90°=up/180°=right; that's the L↔R
    mirror of the app's cvtMowingDirection (180-value) frame, so the two 180s
    cancel and we feed the stored value directly (owner-observed 2026-06-19)."""
    md = make_map_data()
    captured: dict = {}

    def _spy(**kwargs):
        captured["angle"] = kwargs["angle_deg"]
        return Image.new("RGBA", (md.width_px, md.height_px), (0, 0, 0, 0))

    _render_pre_start_with_stripes(
        md, state=_FakeState(direction=26), palette=None,
        compute_stripe_overlay_fn=_spy,
    )
    assert captured["angle"] == 26 % 180  # stored value, pixel-map frame


def test_stripes_cover_every_mowing_zone():
    """All mowing zones get striped, not just the first — a map with N zones
    builds N overlays (fixes 'second zone renders solid')."""
    md = make_map_data()
    z = md.mowing_zones[0]
    z2 = MowingZone(zone_id=2, name="z2", path=z.path, area_m2=z.area_m2)
    md2 = dataclasses.replace(md, mowing_zones=(z, z2))
    calls: list = []

    def _spy(**kwargs):
        calls.append(kwargs["lawn_polygon_px"])
        return Image.new("RGBA", (md2.width_px, md2.height_px), (0, 0, 0, 0))

    _render_pre_start_with_stripes(
        md2, state=_FakeState(direction=26), palette=None,
        compute_stripe_overlay_fn=_spy,
    )
    assert len(calls) == 2  # one overlay per mowing zone


def test_stripes_use_distinct_colors_per_zone():
    """Each mowing zone gets its own stripe colour pair so adjacent zones are
    visually distinguishable (zone 0 green, zone 1 sand, …)."""
    md = make_map_data()
    z = md.mowing_zones[0]
    z2 = MowingZone(zone_id=2, name="z2", path=z.path, area_m2=z.area_m2)
    md2 = dataclasses.replace(md, mowing_zones=(z, z2))
    pairs: list = []

    def _spy(**kwargs):
        pairs.append((kwargs["dark_color"], kwargs["light_color"]))
        return Image.new("RGBA", (md2.width_px, md2.height_px), (0, 0, 0, 0))

    _render_pre_start_with_stripes(
        md2, state=_FakeState(direction=26), palette=None,
        compute_stripe_overlay_fn=_spy,
    )
    assert len(pairs) == 2
    assert pairs[0] != pairs[1], "adjacent zones must use different stripe colours"


def test_stripes_none_direction_falls_back_to_dark_base():
    """No stored angle yet (cloud not polled) → plain dark base, no guessed stripes."""
    md = make_map_data()
    striped = render_base(md, background_mode=BackgroundMode.STRIPES, state=_FakeState(direction=None))
    dark = render_base(md, background_mode=BackgroundMode.GREEN)
    assert striped == dark


def test_render_base_returns_png_for_each_mode():
    md = make_map_data()
    for mode in BackgroundMode:
        png = render_base(md, background_mode=mode)
        assert isinstance(png, bytes), f"render_base({mode}) did not return bytes"
        assert png[:8] == _PNG_SIG, f"render_base({mode}) is not a PNG: {png[:8]!r}"
        assert _png_size(png) == (md.width_px, md.height_px), (
            f"render_base({mode}) returned wrong size: "
            f"{_png_size(png)} != ({md.width_px}, {md.height_px})"
        )


def test_green_and_stripes_differ():
    """STRIPES with a state that generates a stripe overlay should differ from GREEN."""
    md = make_map_data()
    state = _FakeState()
    green_png = render_base(md, background_mode=BackgroundMode.GREEN)
    stripes_png = render_base(md, background_mode=BackgroundMode.STRIPES, state=state, map_id=0)
    assert green_png != stripes_png, (
        "render_base(GREEN) and render_base(STRIPES, state=...) produced identical bytes; "
        "the stripe overlay is not being applied"
    )


def test_stripes_without_state_falls_back_to_dark_base():
    """STRIPES without state must not crash and returns a valid PNG (dark base fallback)."""
    md = make_map_data()
    png = render_base(md, background_mode=BackgroundMode.STRIPES)
    assert isinstance(png, bytes)
    assert png[:8] == _PNG_SIG


def test_render_base_no_trail_or_mower_icon():
    """render_base must not call trail render or composite a mower icon.

    Indirect test: all modes return without error even with no legs/position.
    (If trail code were called it would fail on missing 'legs' arg or similar.)
    """
    md = make_map_data()
    for mode in BackgroundMode:
        png = render_base(md, background_mode=mode)
        assert png[:8] == _PNG_SIG
