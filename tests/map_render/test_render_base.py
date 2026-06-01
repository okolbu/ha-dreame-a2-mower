"""Tests for render_base in map_render/main_view.py (Task 2).

Covers:
- render_base returns valid PNG for all four BackgroundMode values.
- PNG dimensions match MapData.width_px / height_px.
- GREEN and STRIPES (with a state that causes stripe overlay) produce different bytes.
"""
from __future__ import annotations

import io
from PIL import Image

from custom_components.dreame_a2_mower.map_render.main_view import render_base
from custom_components.dreame_a2_mower.map_render.background import BackgroundMode
from custom_components.dreame_a2_mower.mower.state import ActionMode
from tests.map_render.conftest import make_map_data


_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _png_size(b: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(b)).size


class _FakeState:
    """Minimal state stub accepted by _render_pre_start_with_stripes."""

    def __init__(self) -> None:
        self.action_mode = ActionMode.ALL_AREAS
        # Provide a non-zero direction so the stripe overlay differs from
        # the plain dark base (e.g. 45 degrees).
        self.last_all_area_mow_direction_deg: dict = {0: 45}
        self.settings_mowing_direction_mode: int = 0  # fixed-angle mode


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
