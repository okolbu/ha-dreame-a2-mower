"""Card-render gate: the map-editor handles spots (o=214) + maintenance points
(o=224) + patrol points (o=223) on top of the existing no-go/ignore/mow CRUD.

- Spots render as <polygon class="obj obj-spot"> (4 corners).
- Maintenance points render as a MARKER (<g class="obj obj-maint"> circle +
  crosshair), NOT a polygon line.
- Patrol points render as a DISTINCT marker (<g class="obj obj-patrol">),
  save via create_patrol_point, delete category 2.
- The NEW point-model draft (maintenance/patrol create tool) renders a draggable
  marker + delete handle (no resize/rotate/vertex handles) and saves via the
  create_maintenance_point / create_patrol_point service with a FLAT (x, y) +
  heading 0.
- A spot draft saves via create_spot with the 4 corner pairs.
- Delete categories are 1 (spot) / 3 (maintenance) / 2 (patrol).
- Selection-state lifecycle (Fix 3): selecting a point draws exactly one bright
  #draft marker, skips it in #objects, and leaves other points as muted
  non-selected markers; switching tools clears the draft; create-then-remove of
  a provisional leaves no existing point rendered as selected.

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
def test_delete_categories_spot_maintenance_patrol():
    cats = _run_harness()["deleteCalls"]
    assert cats == [1, 3, 2]  # spot=1, maintenance=3, patrol=2


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_patrol_renders_as_distinct_marker():
    html = _run_harness()["objectsHtml"]
    # Patrol id 401 is a marker <g class="obj obj-patrol"> (distinct from maint).
    assert 'class="obj obj-patrol"' in html
    assert 'data-id="401"' in html
    assert 'data-kind="patrol"' in html
    # Never drawn as a phantom polygon line.
    for chunk in html.split("<polygon"):
        if chunk.startswith(" "):
            attrs = chunk.split("/>", 1)[0]
            assert 'data-id="401"' not in attrs, "patrol drawn as a phantom polygon line"


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_patrol_draft_is_point_model_distinct_marker():
    data = _run_harness()
    d = data["patrolDraft"]
    assert d["model"] == "point"
    assert d["objectId"] == 401
    assert d["kind"] == "patrol"
    assert d["category"] == "patrol"
    assert d["nPts"] == 1
    # The SELECTED patrol draft marker uses the distinct marker-patrol class so
    # it reads differently from a maintenance selection.
    dh = data["patrolDraftHtml"]
    assert 'class="marker marker-patrol"' in dh
    assert 'data-role="move"' in dh
    assert 'data-role="del"' in dh


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_patrol_draft_saves_via_create_patrol_point():
    call = _run_harness()["patrolCreateCall"]
    assert call is not None, "expected a create_patrol_point service call"
    assert call["service"] == "create_patrol_point"
    data = call["data"]
    # Flat (x, y) + heading 0; new object => object_id -1.
    assert set(data) == {"map_id", "x", "y", "heading", "object_id"}
    assert isinstance(data["x"], (int, float))
    assert isinstance(data["y"], (int, float))
    assert data["heading"] == 0
    assert data["object_id"] == -1


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_selection_state_one_marker_selected():
    """Fix 3: selecting point A draws exactly one bright #draft marker, skips A
    in #objects, and leaves B as a muted non-selected marker (no bright marker
    in #objects)."""
    sel = _run_harness()["selA"]
    assert sel["draftMarkerCount"] == 1, "exactly one selected draft marker"
    assert sel["objectsHasA"] is False, "selected point A must be skipped in #objects"
    assert sel["objectsHasB"] is True, "non-selected point B still drawn in #objects"
    assert sel["objectsBIsMuted"] is True, "B drawn as muted obj-maint marker"
    assert sel["objectsHasBrightMarker"] is False, (
        "no #objects element may use the bright selected .marker class"
    )


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_selection_cleared_on_tool_switch():
    """Fix 3: switching tools clears the draft and re-renders both points
    unselected."""
    sel = _run_harness()["selB"]
    assert sel["draftEmpty"] is True, "#draft empties on tool switch"
    assert sel["objectsHasA"] is True
    assert sel["objectsHasB"] is True
    assert sel["objectsHasBrightMarker"] is False


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_selection_no_leak_after_create_then_remove():
    """Fix 3: create-then-remove of a provisional leaves the draft cleared and no
    existing point rendered as selected."""
    sel = _run_harness()["selC"]
    assert sel["provisionalAfterCreate"] == 1
    assert sel["draftClearedAfterRemove"] is True
    assert sel["noExistingSelected"] is True
