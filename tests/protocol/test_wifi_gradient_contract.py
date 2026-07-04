"""Pin wifi_map_render._rssi_to_rgb at cardinal dBm values.

The live-map card's JS rssiToRgb (www/_dreame-map-core.js) is kept
character-equivalent to this function by discipline; this test is the
authoritative contract it mirrors. The card uses the RGB channels only and
supplies translucency via the layer's config opacity, so only R/G/B and the
no-data sentinel are contractually pinned here (the Python alpha 220 is not
mirrored)."""
from __future__ import annotations

from custom_components.dreame_a2_mower.wifi.map_render import _rssi_to_rgb


def test_no_data_sentinel_is_transparent():
    assert _rssi_to_rgb(1) == (0, 0, 0, 0)


def test_weakest_is_red():
    assert _rssi_to_rgb(-99)[:3] == (255, 0, 0)


def test_strongest_is_green():
    assert _rssi_to_rgb(-50)[:3] == (0, 255, 0)


def test_midband_is_orange_yellow():
    # -75 dBm: normalised ~0.49 -> red full, green ramps up.
    assert _rssi_to_rgb(-75)[:3] == (255, 250, 0)


def test_first_upper_branch_value():
    # -74 dBm: n ~ 0.510 -> upper branch (red ramps down, green full). Probes
    # the (1-n)*2*255 ramp that the n==1.0 endpoint (test_strongest) can't.
    assert _rssi_to_rgb(-74)[:3] == (250, 255, 0)


def test_clamps_beyond_range():
    assert _rssi_to_rgb(-120)[:3] == (255, 0, 0)   # weaker than WEAKEST
    assert _rssi_to_rgb(-40)[:3] == (0, 255, 0)    # stronger than STRONGEST


def test_data_cells_carry_partial_alpha():
    # Non-sentinel cells are partially transparent in the standalone PNG;
    # the card overrides this with layer opacity but the Python value is fixed.
    assert _rssi_to_rgb(-60)[3] == 220
