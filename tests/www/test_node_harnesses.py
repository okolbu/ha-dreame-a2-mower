"""Parametrized runner for the byte-identical single-harness www tests.

The detection-label / live-map-trail / map-edit-geom / wifi-overlay-key node
harnesses each had their own byte-identical `test_*.py` shell that differed only
in which `*_harness.mjs` it ran (T7-13). They are collapsed here into one
`pytest.mark.parametrize` over the harness scripts — still one test item per
harness (4 collected), still skipped gracefully when node is unavailable.

More elaborate www harnesses (map_editor_points, projection_parity,
schedule_modal_persistence, …) keep their own files — they carry harness-specific
setup/assertions beyond the plain run-and-grep-OK contract.
"""
import pathlib
import shutil
import subprocess

import pytest

NODE = shutil.which("node")
HERE = pathlib.Path(__file__).parent

HARNESSES = [
    "detection_label_harness.mjs",
    "live_map_trail_harness.mjs",
    "geom_harness.mjs",
    "wifi_overlay_key_harness.mjs",
    # R-54 / P5.2 card hygiene: guarded defineCard, renderMissingEntity,
    # per-card no-throw on empty hass (the missing-entity path).
    "card_core_harness.mjs",
]


@pytest.mark.skipif(NODE is None, reason="node not available")
@pytest.mark.parametrize("harness", HARNESSES)
def test_harness(harness):
    r = subprocess.run(
        [NODE, str(HERE / harness)], capture_output=True, text=True, timeout=30
    )
    assert r.returncode == 0, f"node harness failed:\n{r.stdout}\n{r.stderr}"
    assert "OK" in r.stdout
