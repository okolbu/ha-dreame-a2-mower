"""Empirical icon-rotation convention test (bug #3: icon facing wrong way).

This module is the AUTHORITATIVE gate for the mower-icon rotation/projection
convention shared by the live-map and replay cards. The JS pure functions in
``custom_components/dreame_a2_mower/www/_dreame-map-core.js``
(``iconRotation`` / ``projectPoint``) MUST use the identical formula validated
here.

THE VALIDATED CONVENTION
------------------------
The served base PNG is ``FLIP_TOP_BOTTOM``'d, so the replay/live cards project
cloud-mm -> screen-px as::

    px = (bx2_mm - x_mm) / pixel_size_mm          # cloud +X -> screen LEFT
    py = height_px - (by2_mm - y_mm) / pixel_size_mm  # cloud +Y -> screen DOWN

The byte heading ``H`` (degrees, 0 = +X axis, cloud frame) is the cloud-frame
travel direction. For an icon whose source art points UP (screen -y), the SVG
rotation (CW-positive in y-down screen space) that makes it point along travel
is::

    A_svg = (270 - H) mod 360        # VALIDATED

Cardinals: H=0 -> 270, H=90 -> 180, H=180 -> 90, H=270 -> 0.

Validation result (this file, full local corpus, straight-line frames):
    n=43182  median=1.35 deg  p90=7.23 deg  (p99 tail ~47 deg is turn pivots)

The ``(270 - H)`` derivation in the design note turned out to be CORRECT (no
sign error): byte H agrees with the cloud-frame chord direction at median
~2.5 deg, and the screen projection + (270-H) SVG rotation reproduces the
screen-space travel direction at median ~1.4 deg on straight runs.
"""
from __future__ import annotations

import glob
import json
import math
import statistics

import pytest

# The probe corpus lives in the PARENT dir, outside the worktree.
CORPUS = sorted(glob.glob("/data/claude/homeassistant/probe_log_*.jsonl"))

# Fixed projection. The affine constants cancel in an angle, so identity-ish
# values are fine -- the point is to exercise the SAME formula shape the JS
# uses (px = (bx2 - x)/g ; py = h - (by2 - y)/g).
_PROJ = {"bx2_mm": 0.0, "by2_mm": 0.0, "pixel_size_mm": 1.0, "height_px": 0.0}


def _pose(v):
    """Decode (x_mm, y_mm) from a 33-byte s1p4 frame.

    Mirrors protocol/telemetry.py:_decode_pose with offset=1.
    """
    b0, b1, b2, b3, b4 = v[1], v[2], v[3], v[4], v[5]
    x = ((b2 & 0x0F) << 16) | (b1 << 8) | b0
    if x & 0x80000:
        x -= 0x100000
    y = (b4 << 12) | (b3 << 4) | ((b2 & 0xF0) >> 4)
    if y & 0x80000:
        y -= 0x100000
    return x * 10, y * 10  # mm


def _project(x_mm, y_mm, proj):
    """CANONICAL projection -- SAME FORMULA SHAPE as the replay card's
    _projectPoint and the shared JS projectPoint(), but note the unit
    contract differs: this takes cloud-MM, the JS takes cloud-METRES (it
    multiplies by 1000 internally). The angle this test measures is
    scale-invariant, so the mm-vs-m difference does not affect the result."""
    px = (proj["bx2_mm"] - x_mm) / proj["pixel_size_mm"]
    py = proj["height_px"] - (proj["by2_mm"] - y_mm) / proj["pixel_size_mm"]
    return px, py


def _icon_rotation(heading_deg):
    """CANONICAL icon-rotation formula (VALIDATED -- see module docstring).

    Returns the CW-positive SVG rotation (y-down screen space) that aims an
    up-pointing icon along the cloud-frame travel heading H.

    The JS iconRotation() byte-branch is character-equivalent:
        ((270 - H) % 360 + 360) % 360
    """
    return (270.0 - heading_deg) % 360.0


def _fold180(deg):
    """Absolute angular error folded to [0, 180]."""
    a = abs(deg) % 360.0
    return 360.0 - a if a > 180.0 else a


def _screen_travel_svg(dpx, dpy):
    """SVG rotation (for an up-pointing icon) that matches a screen motion
    vector (dpx, dpy) in y-down screen space.

    This is the VECTOR-FALLBACK branch: when no byte heading is available the
    card derives the rotation from the screen displacement. atan2(dpy, dpx) is
    the screen travel angle (CW-positive, y-down); +90 maps it to the up-art
    SVG rotation. Must match the JS iconRotation() vector branch.
    """
    return (math.degrees(math.atan2(dpy, dpx)) + 90.0) % 360.0


def _iter_s1p4_frames(path):
    """Yield (x_mm, y_mm, H) for every 33-byte s1p4 frame in a probe log."""
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except (ValueError, json.JSONDecodeError):
                continue
            if d.get("method") != "properties_changed":
                continue
            for p in d.get("params", []):
                if not isinstance(p, dict):
                    continue
                if p.get("siid") != 1 or p.get("piid") != 4:
                    continue
                v = p.get("value")
                if not (isinstance(v, list) and len(v) == 33):
                    continue
                x, y = _pose(v)
                yield x, y, v[6] / 255.0 * 360.0


# Gates. Straight-line travel only: when the mower pivots/turns between two
# samples the chord direction necessarily diverges from the instantaneous
# heading, which is a property of two-point sampling, not the convention. We
# isolate frames where the heading is steady (turn delta small) so the chord
# genuinely reflects the travel direction the icon should point along.
_MOTION_LO_MM = 100.0     # skip near-zero motion (atan2 noise)
_MOTION_HI_MM = 3000.0    # skip session-boundary jumps
_STRAIGHT_HEADING_DELTA = 20.0  # deg: prev/cur heading must agree (no turn)


@pytest.mark.skipif(not CORPUS, reason="probe corpus not present")
def test_icon_rotation_matches_corpus_motion():
    """The (270 - H) icon rotation reproduces screen-space travel direction."""
    errs = []
    for path in CORPUS:
        prev = None  # reset per file (no cross-session chords)
        for x, y, H in _iter_s1p4_frames(path):
            px, py = _project(x, y, _PROJ)
            if prev is not None:
                # prev screen-px (spx0,spy0) and prev cloud-mm (x0_mm,y0_mm).
                spx0, spy0, x0_mm, y0_mm, pH = prev
                dmm = abs(x - x0_mm) + abs(y - y0_mm)
                straight = _fold180(pH - H) <= _STRAIGHT_HEADING_DELTA
                if _MOTION_LO_MM <= dmm <= _MOTION_HI_MM and straight:
                    # Screen motion vector this interval.
                    dpx, dpy = px - spx0, py - spy0
                    travel_svg = _screen_travel_svg(dpx, dpy)
                    # Icon rotation from the EARLIER frame's byte heading.
                    icon_svg = _icon_rotation(pH)
                    errs.append(_fold180(icon_svg - travel_svg))
            prev = (px, py, x, y, H)

    assert errs, "no qualifying straight-line s1p4 frame pairs found"
    errs.sort()
    n = len(errs)
    median = statistics.median(errs)
    p90 = errs[int(n * 0.90)]
    # Visible in -s output for the report.
    print(
        f"\nicon-direction corpus: n={n} median={median:.2f} "
        f"p90={p90:.2f} p95={errs[int(n * 0.95)]:.2f} p99={errs[int(n * 0.99)]:.2f}"
    )
    assert median < 10.0, f"median icon error {median:.2f} deg too large"
    assert p90 < 45.0, f"p90 icon error {p90:.2f} deg too large"


# --- CI guard (NOT skipped): pins the formula at cardinals even without corpus.
def test_icon_rotation_cardinals():
    """Hardcoded cardinals lock the validated (270 - H) formula in CI."""
    assert _icon_rotation(0.0) == 270.0
    assert _icon_rotation(90.0) == 180.0
    assert _icon_rotation(180.0) == 90.0
    assert _icon_rotation(270.0) == 0.0


def test_projection_matches_replay_card_convention():
    """projectPoint convention: cloud +X -> screen LEFT, +Y -> screen DOWN."""
    proj = {"bx2_mm": 1000.0, "by2_mm": 1000.0, "pixel_size_mm": 10.0, "height_px": 50.0}
    px0, py0 = _project(0.0, 0.0, proj)
    # Increasing cloud X moves screen px LEFT (smaller px).
    px1, _ = _project(500.0, 0.0, proj)
    assert px1 < px0
    # Increasing cloud Y moves screen py DOWN (larger py).
    _, py1 = _project(0.0, 500.0, proj)
    assert py1 > py0


def test_vector_fallback_agrees_with_byte_branch():
    """For a straight screen move, the vector-fallback rotation equals the
    byte-branch rotation -- the two iconRotation paths are consistent."""
    # A frame heading H projects to a screen travel vector; the fallback,
    # given that same screen vector, must return the same SVG rotation.
    for H in (0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0):
        # Cloud-frame unit travel for heading H.
        dx_cloud = math.cos(math.radians(H))
        dy_cloud = math.sin(math.radians(H))
        # Project a short displacement (cloud +X -> screen -x, +Y -> +y).
        dpx = -dx_cloud  # px = (bx2 - x)/g, so dpx = -dx_cloud / g
        dpy = dy_cloud   # py = h - (by2 - y)/g, so dpy = +dy_cloud / g
        byte_rot = _icon_rotation(H)
        vec_rot = _screen_travel_svg(dpx, dpy)
        assert _fold180(byte_rot - vec_rot) < 1e-6, (
            f"H={H}: byte={byte_rot} vec={vec_rot}"
        )
