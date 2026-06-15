"""Card-render gate: the map-editor draws decorative no-go shapes (heart etc.)
as a faint dashed bbox hit-area <rect>, NOT a 2-point <polygon> ("phantom no-go
line"). Standard zones (line shapeType 1, polygon shapeType 2) keep their normal
<polygon> overlays. Selecting a decorative shape yields a DELETE-ONLY draft
(bbox outline + delete handle, no resize/rotate/vertex handles).

Runs the REAL card render functions in node (per
feedback_frontend_card_verification — `node --check` only catches syntax) and
asserts the produced SVG markup. The companion server-side filter
(_render_base keeps decorative exclusions in the editor base, drops standard
ones) is covered in tests/coordinator/test_base_render_on_activity.py.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

NODE = shutil.which("node")
HARNESS = pathlib.Path(__file__).parent / "map_editor_decorative_harness.mjs"


def _run_harness() -> dict:
    r = subprocess.run(
        [NODE, str(HARNESS)], capture_output=True, text=True, timeout=30
    )
    assert r.returncode == 0, f"node harness failed:\n{r.stdout}\n{r.stderr}"
    # The card prints a version banner to stdout at import; the JSON payload is
    # the last non-empty line.
    last = [ln for ln in r.stdout.splitlines() if ln.strip()][-1]
    return json.loads(last)


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_decorative_heart_renders_as_rect_not_line():
    data = _run_harness()

    # shape_type carried through _effectiveObjects (was dropped before the fix).
    assert data["effShapeTypes"] == [13, 1, 2]

    html = data["objectsHtml"]
    # The heart (id 101) is a dashed bbox hit-area rect, NOT a polygon.
    assert 'class="obj obj-decorative"' in html
    assert 'data-id="101"' in html
    # No <polygon> for the heart: assert the heart's id never appears on a polygon.
    for chunk in html.split("<polygon"):
        if chunk.startswith(" "):
            assert 'data-id="101"' not in chunk, "heart drawn as a phantom polygon line"
    # Standard line (102) + polygon (103) keep their <polygon> overlays.
    assert '<polygon class="obj obj-nogo"' in html
    assert 'data-id="102"' in html
    assert 'data-id="103"' in html
    # The heart-decorative rect must come from the decorative branch, so it must
    # be a <rect ...obj-decorative...> carrying the heart id.
    assert any(
        seg.startswith(" ") and 'data-id="101"' in seg and "obj-decorative" in seg
        for seg in html.split("<rect")
    )


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_decorative_select_is_delete_only_draft():
    data = _run_harness()

    draft = data["heartDraft"]
    assert draft["model"] == "decorative"
    assert draft["objectId"] == 101
    assert draft["kind"] == "heart"
    assert draft["category"] == "nogo"
    assert draft["nPts"] == 4  # bbox corners for the selection outline

    dh = data["draftHtml"]
    # bbox outline + delete handle ONLY — no resize/rotate/vertex/endpoint handles.
    assert 'class="bbox"' in dh
    assert 'data-role="del"' in dh
    assert 'data-role="resize"' not in dh
    assert 'data-role="rotate"' not in dh
    assert 'data-role="endpoint"' not in dh
    assert 'class="vtx"' not in dh and 'class="vtx0"' not in dh
