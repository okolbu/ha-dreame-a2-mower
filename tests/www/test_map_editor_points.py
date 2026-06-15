"""Card-render gate: the map-editor handles spots (o=214) + maintenance points
(o=224) on top of the existing no-go/ignore/mow CRUD.

- Spots render as <polygon class="obj obj-spot"> (4 corners).
- Maintenance points render as a MARKER (<g class="obj obj-maint"> circle +
  crosshair), NOT a polygon line.
- The NEW point-model draft (maintenance create tool) renders a draggable marker
  + delete handle (no resize/rotate/vertex handles) and saves via the
  create_maintenance_point service with a FLAT (x, y) + heading 0.
- A spot draft saves via create_spot with the 4 corner pairs.
- Delete categories are 1 (spot) / 3 (maintenance).

Runs the REAL card render + submit functions in node (per
feedback_frontend_card_verification — `node --check` only catches syntax).
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

NODE = shutil.which("node")
HARNESS = pathlib.Path(__file__).parent / "map_editor_points_harness.mjs"


def _run_harness() -> dict:
    r = subprocess.run(
        [NODE, str(HARNESS)], capture_output=True, text=True, timeout=30
    )
    assert r.returncode == 0, f"node harness failed:\n{r.stdout}\n{r.stderr}"
    last = [ln for ln in r.stdout.splitlines() if ln.strip()][-1]
    return json.loads(last)


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_spot_renders_as_polygon():
    html = _run_harness()["objectsHtml"]
    # Spot id 201 is a <polygon class="obj obj-spot">.
    assert '<polygon class="obj obj-spot"' in html
    assert 'data-id="201"' in html
    assert 'data-kind="spot"' in html


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_maintenance_renders_as_marker_not_line():
    html = _run_harness()["objectsHtml"]
    # Maintenance id 301 is a marker <g class="obj obj-maint"> (circle), NOT a
    # polygon line.
    assert 'class="obj obj-maint"' in html
    assert 'data-id="301"' in html
    assert 'data-kind="maintenance"' in html
    # The maintenance id must never appear on a <polygon ...> element (phantom
    # line bug): inspect the attribute span of each polygon (up to its '/>').
    for chunk in html.split("<polygon"):
        if chunk.startswith(" "):
            attrs = chunk.split("/>", 1)[0]
            assert 'data-id="301"' not in attrs, "maintenance drawn as a phantom polygon line"


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_maintenance_draft_is_point_model_marker():
    data = _run_harness()
    d = data["maintDraft"]
    assert d["model"] == "point"
    assert d["objectId"] == 301
    assert d["kind"] == "maintenance"
    assert d["category"] == "maintenance"
    assert d["nPts"] == 1  # single point

    dh = data["maintDraftHtml"]
    # A draggable marker + a delete handle — NO resize/rotate/vertex/endpoint.
    assert 'class="marker"' in dh
    assert 'data-role="move"' in dh
    assert 'data-role="del"' in dh
    assert 'data-role="resize"' not in dh
    assert 'data-role="rotate"' not in dh
    assert 'data-role="endpoint"' not in dh


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_spot_draft_is_corners_rect():
    d = _run_harness()["spotDraft"]
    assert d["model"] == "corners"
    assert d["objectId"] == 201
    assert d["kind"] == "spot"
    assert d["category"] == "spot"
    assert d["nPts"] == 4


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_point_draft_saves_via_create_maintenance_point():
    call = _run_harness()["maintCreateCall"]
    assert call is not None, "expected a create_maintenance_point service call"
    assert call["service"] == "create_maintenance_point"
    data = call["data"]
    # Flat (x, y) + heading 0; new object => object_id -1.
    assert set(data) == {"map_id", "x", "y", "heading", "object_id"}
    assert isinstance(data["x"], (int, float))
    assert isinstance(data["y"], (int, float))
    assert data["heading"] == 0
    assert data["object_id"] == -1


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_spot_draft_saves_via_create_spot():
    call = _run_harness()["spotCreateCall"]
    assert call is not None, "expected a create_spot service call"
    assert call["service"] == "create_spot"
    data = call["data"]
    assert set(data) == {"map_id", "points", "object_id"}
    assert len(data["points"]) == 4
    assert data["object_id"] == -1


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_delete_categories_spot_and_maintenance():
    cats = _run_harness()["deleteCalls"]
    assert cats == [1, 3]  # spot=1, maintenance=3
