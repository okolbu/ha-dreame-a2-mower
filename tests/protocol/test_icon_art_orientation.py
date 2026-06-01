"""Regression guard for the mower-icon ART-orientation compensation.

The shared client core (``www/_dreame-map-core.js``) rotates the mower icon by
``iconRotation(...)``, which is the corpus-validated heading->screen-angle math
(see ``test_icon_direction_corpus.py``). That math assumes the icon ART points
screen-UP. The shipped ``mower-icon.png`` is authored pointing screen-LEFT
(front/lidar at left), which rendered every replay (and the live map) a constant
90 deg anticlockwise off until 2026-06-01.

The fix compensates at the ART layer: ``buildMowerIconSvg`` pre-rotates the
``<image>`` by ``ICON_ART_FORWARD_DEG`` (=90) so the art's forward becomes
screen-UP, leaving ``iconRotation`` (and its corpus test) untouched.

There is no JS test runner in CI, so this guard reads the source text and pins:
  1. the compensation constant is 90, and
  2. ``buildMowerIconSvg`` actually applies it to the <image> transform.

If a future icon asset is re-authored pointing UP, set the constant to 0 and
update this test in the same change.
"""
from __future__ import annotations

from pathlib import Path

_CORE_JS = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "dreame_a2_mower"
    / "www"
    / "_dreame-map-core.js"
)


def test_core_js_exists() -> None:
    assert _CORE_JS.is_file(), f"shared map core missing: {_CORE_JS}"


def test_icon_art_forward_compensation_present() -> None:
    src = _CORE_JS.read_text()
    # The compensation constant must be exactly 90 (art points LEFT -> rotate
    # +90 CW to make forward = screen-UP). Flipping/dropping this re-introduces
    # the 90 deg sideways-icon regression.
    assert "export const ICON_ART_FORWARD_DEG = 90;" in src, (
        "ICON_ART_FORWARD_DEG must be 90 (mower-icon.png art points LEFT)"
    )
    # And it must actually be wired into the icon <image> transform.
    assert 'transform="rotate(${ICON_ART_FORWARD_DEG})"' in src, (
        "buildMowerIconSvg must apply ICON_ART_FORWARD_DEG to the <image>"
    )
