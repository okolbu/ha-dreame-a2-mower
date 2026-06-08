# WiFi coverage overlay on the live map — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a user-toggleable, translucent WiFi-coverage layer to the live-map SVG card, drawn in the same coordinate frame as the lawn/trail/mower without interfering with them.

**Architecture:** A new `wifi_overlay` attribute on `camera.dreame_a2_mower_map` carries the active map's WiFi cell grid (lazily loaded + cached coordinator-side). The card draws one `<rect>` per cell in a `<g>` layer placed *below* the trail and icon, using the card's existing `projectPoint`. Cell geometry inverts the already-tested `wifi_match.py` convention, so no flip hacks. Toggle is an in-card button (default off, persisted in localStorage); opacity is a card-config value.

**Tech Stack:** Python (Home Assistant custom integration), vanilla JS ES module Lovelace card, PIL (existing renderer, unchanged), pytest.

---

## Conventions for this plan

- **Test runner:** the vanilla stubbed-HA venv. Run pytest as:
  `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest <path> -v`
  (system `python3` is broken — always use this interpreter. Baseline: 1591 passed / 4 skipped.)
- **No JS test harness exists** (no node). Per the repo's established pattern for the
  `iconRotation` / `projectPoint` JS (see `tests/protocol/test_icon_direction_corpus.py`
  and `tests/test_extract_projection.py`), JS is kept *character-equivalent* to a
  pinned Python contract by discipline + a code comment that names the pinning test.
  We follow that pattern for the gradient and the cell-rect geometry.
- **CWD** for all commands: `/data/claude/homeassistant/ha-dreame-a2-mower`.

---

## File structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `custom_components/dreame_a2_mower/coordinator/_wifi_archive.py` | Modify | Resolve active-map WiFi entry; build overlay payload; schedule lazy body load |
| `custom_components/dreame_a2_mower/_camera_map.py` | Modify | Publish `wifi_overlay` attribute; schedule load on update; mark unrecorded |
| `custom_components/dreame_a2_mower/www/_dreame-map-core.js` | Modify | Port `rssiToRgb` gradient (mirror of Python `_rssi_to_rgb`) |
| `custom_components/dreame_a2_mower/www/dreame-mower-map-card.js` | Modify | Overlay `<g>` layer, in-card toggle, config opacity |
| `tests/integration/test_active_map_wifi_overlay.py` | Create | Coordinator accessor + payload shape |
| `tests/integration/test_map_camera_wifi_overlay_attr.py` | Create | Camera attribute present/absent/shape |
| `tests/protocol/test_wifi_gradient_contract.py` | Create | Pin `_rssi_to_rgb` at cardinals (the contract the JS mirrors) |
| `tests/protocol/test_wifi_overlay_geometry.py` | Create | Pin the cell→cloud-box→rect math (the contract the card mirrors) |
| `custom_components/dreame_a2_mower/inventory.yaml` | Modify | Record overlay-anchoring claim (status `presumed` until live-confirmed) |
| `custom_components/dreame_a2_mower/entity-inventory.yaml` | Modify | Note map camera now publishes `wifi_overlay` |
| `docs/TODO.md` | Modify | Remove the superseded "WiFi heatmap overlay on the live map" entry |

---

## Task 1: Coordinator — active-map WiFi overlay resolution + accessor

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_wifi_archive.py`
- Test: `tests/integration/test_active_map_wifi_overlay.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_active_map_wifi_overlay.py`:

```python
"""Coordinator-side active-map WiFi overlay accessor.

The live-map card reads camera.dreame_a2_mower_map.attributes.wifi_overlay;
that attribute is built by DreameA2MowerCoordinator.active_map_wifi_overlay,
which resolves the newest archived heatmap tagged with the ACTIVE map_id and
emits its cell grid in metre units (cm->m converted here)."""
from __future__ import annotations

from pathlib import Path

from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.wifi_archive_store import WifiArchiveStore


def _build_coord(tmp_path: Path):
    coord = object.__new__(DreameA2MowerCoordinator)
    coord._wifi_archive_store = WifiArchiveStore(tmp_path / "wifi_archive")
    coord._wifi_archive_index = []
    coord._wifi_body_cache = {}
    coord._active_map_id = None
    return coord


def _archive_heatmap(coord, *, object_name, map_id, width, height, res_m,
                     start_x_m, start_y_m, fill_dbm=-55, unix_ts=1000):
    body = {
        "data": [fill_dbm] * (width * height),
        "width": width, "height": height, "resolution": res_m,
        "startX": int(start_x_m * 100), "startY": int(start_y_m * 100),
    }
    store = coord._wifi_archive_store
    store.archive(object_name, body, first_seen_unix=unix_ts)
    # Tag with map_id + refresh the in-memory index the accessor reads.
    store.set_map_id(object_name, map_id)
    coord._wifi_archive_index = store.load_index()
    return body


def test_overlay_none_when_no_active_map(tmp_path):
    coord = _build_coord(tmp_path)
    assert coord.active_map_wifi_overlay is None


def test_overlay_none_when_body_not_cached(tmp_path):
    coord = _build_coord(tmp_path)
    _archive_heatmap(coord, object_name="hm1", map_id=0, width=2, height=2,
                     res_m=2, start_x_m=1.0, start_y_m=3.0)
    coord._active_map_id = 0
    # Entry resolves, but body has not been loaded into the cache yet.
    assert coord.active_map_wifi_overlay is None


def test_overlay_payload_shape_when_cached(tmp_path):
    coord = _build_coord(tmp_path)
    body = _archive_heatmap(coord, object_name="hm1", map_id=0, width=2,
                            height=3, res_m=2, start_x_m=1.0, start_y_m=3.0)
    coord._active_map_id = 0
    coord._wifi_body_cache["hm1"] = body  # simulate a completed load
    overlay = coord.active_map_wifi_overlay
    assert overlay is not None
    assert overlay["width"] == 2 and overlay["height"] == 3
    assert overlay["data"] == body["data"]
    assert overlay["resolution_m"] == 2.0
    assert overlay["start_x_m"] == 1.0   # cm -> m
    assert overlay["start_y_m"] == 3.0


def test_overlay_ignores_other_map(tmp_path):
    coord = _build_coord(tmp_path)
    body = _archive_heatmap(coord, object_name="hm9", map_id=9, width=2,
                            height=2, res_m=2, start_x_m=0.0, start_y_m=0.0)
    coord._wifi_body_cache["hm9"] = body
    coord._active_map_id = 0  # different map -> no entry
    assert coord.active_map_wifi_overlay is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_active_map_wifi_overlay.py -v`
Expected: FAIL — `AttributeError: 'DreameA2MowerCoordinator' object has no attribute 'active_map_wifi_overlay'`.

- [ ] **Step 3: Add the accessor methods to the mixin**

In `custom_components/dreame_a2_mower/coordinator/_wifi_archive.py`, add these three members to `class _WifiArchiveMixin` (place them after `refresh_wifi_archive`, before `_download_and_archive_wifi`). Note: `_get_wifi_body_cached` and `_async_load_wifi_body` live on `_LidarOssMixin` and resolve via the assembled coordinator's MRO.

```python
    # ---------- active-map overlay for the live-map card (2026-06-08) ----------

    def _resolve_active_map_wifi_entry(self):
        """Newest WiFi archive entry tagged with the ACTIVE map_id, or None.

        Mirrors ``DreameA2WifiPerMapCamera._resolve_entry`` but keyed on the
        live map's active map, so the overlay always matches what the live-map
        card is showing. Returns None when no active map is set or no archived
        heatmap carries that map_id yet.
        """
        active = getattr(self, "_active_map_id", None)
        if active is None:
            return None
        index = getattr(self, "_wifi_archive_index", None) or []
        matches = [e for e in index if int(getattr(e, "map_id", -1)) == int(active)]
        if not matches:
            return None
        matches.sort(key=lambda e: int(e.unix_ts), reverse=True)
        return matches[0]

    @property
    def active_map_wifi_overlay(self) -> "dict | None":
        """Overlay payload for the active map's WiFi heatmap, or None.

        Read-only and NON-BLOCKING: returns None when the body is not yet
        cached (the camera warms the cache via
        ``_schedule_active_map_wifi_load``). cm->m conversion happens here so
        the card stays in the same metre frame as ``map_projection`` and the
        live track points.

        Payload: ``{data, width, height, resolution_m, start_x_m, start_y_m}``.
        """
        entry = self._resolve_active_map_wifi_entry()
        if entry is None:
            return None
        body = self._get_wifi_body_cached(entry.object_name)
        if not isinstance(body, dict):
            return None
        data = body.get("data")
        width = body.get("width")
        height = body.get("height")
        if not (isinstance(data, list) and isinstance(width, int)
                and isinstance(height, int)):
            return None
        if width <= 0 or height <= 0 or len(data) != width * height:
            return None
        try:
            resolution_m = float(body.get("resolution", 1)) or 1.0
            start_x_m = float(body.get("startX", 0)) / 100.0
            start_y_m = float(body.get("startY", 0)) / 100.0
        except (TypeError, ValueError):
            return None
        return {
            "data": data,
            "width": width,
            "height": height,
            "resolution_m": resolution_m,
            "start_x_m": start_x_m,
            "start_y_m": start_y_m,
        }

    def _schedule_active_map_wifi_load(self) -> None:
        """Schedule an executor load of the active map's WiFi body if it is
        not cached yet, so the next coordinator broadcast carries the overlay.

        No-op when already cached, no entry exists, or hass is unavailable.
        """
        entry = self._resolve_active_map_wifi_entry()
        if entry is None:
            return
        if self._get_wifi_body_cached(entry.object_name) is not None:
            return
        hass = getattr(self, "hass", None)
        if hass is None:
            return
        hass.async_create_task(self._async_load_wifi_body(entry.object_name))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_active_map_wifi_overlay.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_wifi_archive.py tests/integration/test_active_map_wifi_overlay.py
git commit -m "feat(coordinator): active-map WiFi overlay accessor for live map

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Camera — publish `wifi_overlay` attribute + warm cache on update

**Files:**
- Modify: `custom_components/dreame_a2_mower/_camera_map.py`
- Test: `tests/integration/test_map_camera_wifi_overlay_attr.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_map_camera_wifi_overlay_attr.py`:

```python
"""DreameA2MapCamera publishes wifi_overlay when the active map has a
cached heatmap body, and omits it otherwise."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock


def _make_camera(tmp_path: Path, *, with_body: bool):
    from custom_components.dreame_a2_mower.camera import DreameA2MapCamera
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.mower.state_machine import MowerStateMachine
    from custom_components.dreame_a2_mower.wifi_archive_store import WifiArchiveStore

    md = SimpleNamespace(
        name="Main Lawn", bx1=0.0, by1=0.0, bx2=20000.0, by2=21000.0,
        pixel_size_mm=50.0, width_px=400, height_px=420, nav_paths=(),
    )
    cloud_state = SimpleNamespace(
        maps_by_id={0: md}, forbidden_node_types_by_map={},
        settings=SimpleNamespace(raw=[]),
    )
    coord = object.__new__(DreameA2MowerCoordinator)
    coord._base_png = b"\x89PNGbase"
    coord._base_png_mode = SimpleNamespace(value="green")
    coord._live_point_seq = 0
    coord._latest_point = None
    coord._track_snapshot = []
    coord.cloud_state = cloud_state
    coord._active_map_id = 0
    coord.state_machine = MowerStateMachine()
    coord._cloud = MagicMock()
    coord._cloud.model = "dreame.mower.g2408"
    coord._cloud.mac_address = None
    coord.entry = MagicMock(); coord.entry.entry_id = "e"
    coord.data = MagicMock(); coord.data.hardware_serial = None

    store = WifiArchiveStore(tmp_path / "wifi")
    body = {"data": [-55, -60, -70, 1], "width": 2, "height": 2,
            "resolution": 2, "startX": 100, "startY": 300}
    store.archive("hm1", body, first_seen_unix=1000)
    store.set_map_id("hm1", 0)
    coord._wifi_archive_store = store
    coord._wifi_archive_index = store.load_index()
    coord._wifi_body_cache = {"hm1": body} if with_body else {}

    return DreameA2MapCamera(coord)


def test_wifi_overlay_present_when_cached(tmp_path):
    cam = _make_camera(tmp_path, with_body=True)
    attrs = cam.extra_state_attributes
    assert "wifi_overlay" in attrs
    o = attrs["wifi_overlay"]
    assert o["width"] == 2 and o["height"] == 2
    assert o["start_x_m"] == 1.0 and o["start_y_m"] == 3.0


def test_wifi_overlay_absent_when_not_cached(tmp_path):
    cam = _make_camera(tmp_path, with_body=False)
    assert "wifi_overlay" not in cam.extra_state_attributes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_map_camera_wifi_overlay_attr.py -v`
Expected: FAIL — `assert "wifi_overlay" in attrs` (KeyError / missing).

- [ ] **Step 3: Publish the attribute + warm the cache**

In `custom_components/dreame_a2_mower/_camera_map.py`:

(a) Add `"wifi_overlay"` to the `_unrecorded_attributes` frozenset on `DreameA2MapCamera`:

```python
    _unrecorded_attributes = frozenset({
        "track_snapshot", "latest_point", "point_seq", "last_known_point",
        "settings_dual_level_diagnostic", "nav_paths_pt_count_by_map",
        "calibration_points",  # legacy name; harmless if ever re-added
        "wifi_overlay",        # cell grid; large + changes rarely, no restore value
    })
```

(b) In `extra_state_attributes`, immediately before the final `return attrs`, add:

```python
        overlay = self.coordinator.active_map_wifi_overlay
        if overlay is not None:
            attrs["wifi_overlay"] = overlay
```

(c) In `_handle_coordinator_update`, warm the cache so the body is present on the
next broadcast. Add this as the first statement of the method body (before the
`cur = self.coordinator._base_png` line):

```python
        # Warm the active-map WiFi body cache so wifi_overlay can be published
        # on a subsequent broadcast (load is async + self-notifies on completion).
        self.coordinator._schedule_active_map_wifi_load()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_map_camera_wifi_overlay_attr.py tests/integration/test_map_camera_attributes.py -v`
Expected: PASS (new tests + existing camera-attribute tests still green).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/_camera_map.py tests/integration/test_map_camera_wifi_overlay_attr.py
git commit -m "feat(camera): publish wifi_overlay attribute on the live map camera

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Gradient — pin the Python contract + port `rssiToRgb` to JS

**Files:**
- Create: `tests/protocol/test_wifi_gradient_contract.py`
- Modify: `custom_components/dreame_a2_mower/www/_dreame-map-core.js`

- [ ] **Step 1: Write the pinning test**

Create `tests/protocol/test_wifi_gradient_contract.py`. This locks the exact RGB
the JS `rssiToRgb` must mirror (the JS is not executed — this is its contract).

```python
"""Pin wifi_map_render._rssi_to_rgb at cardinal dBm values.

The live-map card's JS rssiToRgb (www/_dreame-map-core.js) is kept
character-equivalent to this function by discipline; this test is the
authoritative contract it mirrors. The card uses the RGB channels only and
supplies translucency via the layer's config opacity, so only R/G/B and the
no-data sentinel are contractually pinned here (the Python alpha 220 is not
mirrored)."""
from __future__ import annotations

from custom_components.dreame_a2_mower.wifi_map_render import _rssi_to_rgb


def test_no_data_sentinel_is_transparent():
    assert _rssi_to_rgb(1) == (0, 0, 0, 0)


def test_weakest_is_red():
    assert _rssi_to_rgb(-99)[:3] == (255, 0, 0)


def test_strongest_is_green():
    assert _rssi_to_rgb(-50)[:3] == (0, 255, 0)


def test_midband_is_orange_yellow():
    # -75 dBm: normalised ~0.49 -> red full, green ramps up.
    assert _rssi_to_rgb(-75)[:3] == (255, 250, 0)


def test_clamps_beyond_range():
    assert _rssi_to_rgb(-120)[:3] == (255, 0, 0)   # weaker than WEAKEST
    assert _rssi_to_rgb(-40)[:3] == (0, 255, 0)    # stronger than STRONGEST


def test_data_cells_carry_partial_alpha():
    # Non-sentinel cells are partially transparent in the standalone PNG;
    # the card overrides this with layer opacity but the Python value is fixed.
    assert _rssi_to_rgb(-60)[3] == 220
```

- [ ] **Step 2: Run test to verify it passes (documents current behaviour)**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_wifi_gradient_contract.py -v`
Expected: PASS — `_rssi_to_rgb` already exists; this pins it. (If any cardinal
fails, STOP and reconcile the expected value against `wifi_map_render.py` before
porting to JS — the JS must match whatever Python actually does.)

- [ ] **Step 3: Port `rssiToRgb` into the JS core module**

In `custom_components/dreame_a2_mower/www/_dreame-map-core.js`, add this function
after `iconRotation` (before `buildMowerIconSvg`):

```javascript
// WiFi heatmap colour gradient — character-equivalent mirror of
// wifi_map_render.py:_rssi_to_rgb. Returns { r, g, b } for a data cell or
// null for the no-data sentinel (rssi === 1). The card supplies translucency
// via the overlay layer's config opacity, so alpha is NOT mirrored here.
// THE GRADIENT CONTRACT IS PINNED by tests/protocol/test_wifi_gradient_contract.py
// — do not change the channel math without re-running it.
export const WIFI_STRONGEST = -50; // dBm -> full green
export const WIFI_WEAKEST = -99;   // dBm -> full red
export function rssiToRgb(rssi) {
  if (rssi === 1) return null; // no-data sentinel
  let n = (rssi - WIFI_WEAKEST) / (WIFI_STRONGEST - WIFI_WEAKEST);
  n = Math.max(0, Math.min(1, n));
  let r;
  let g;
  if (n < 0.5) {
    r = 255;
    g = Math.round(n * 2 * 255);
  } else {
    r = Math.round((1 - n) * 2 * 255);
    g = 255;
  }
  return { r, g, b: 0 };
}
```

Then add `rssiToRgb` (and the two consts) to the `window.DreameMapCore` object at
the bottom of the file:

```javascript
if (typeof window !== "undefined") {
  window.DreameMapCore = {
    projectPoint,
    iconRotation,
    buildMowerIconSvg,
    ICON_ART_FORWARD_DEG,
    rssiToRgb,
    WIFI_STRONGEST,
    WIFI_WEAKEST,
  };
}
```

- [ ] **Step 4: Re-run the pin test (still green)**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_wifi_gradient_contract.py -v`
Expected: PASS (unchanged — Python side untouched; JS mirrors it).

- [ ] **Step 5: Commit**

```bash
git add tests/protocol/test_wifi_gradient_contract.py custom_components/dreame_a2_mower/www/_dreame-map-core.js
git commit -m "feat(card): port wifi RSSI gradient to JS core, pin Python contract

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Card — overlay layer, in-card toggle, config opacity

**Files:**
- Create: `tests/protocol/test_wifi_overlay_geometry.py`
- Modify: `custom_components/dreame_a2_mower/www/dreame-mower-map-card.js`

- [ ] **Step 1: Pin the cell→rect geometry contract (Python mirror)**

Create `tests/protocol/test_wifi_overlay_geometry.py`. The card computes each
cell's screen rect in JS; this Python mirror pins the math (cell box in cloud
metres -> projectPoint corners -> min/max rect) the JS must reproduce. It mirrors
the projection used in `test_extract_projection.py`.

```python
"""Pin the WiFi-overlay cell->rect geometry the live-map card implements.

The card derives each heatmap cell's screen rectangle by:
  1. cell (cx, cy) covers cloud-metre box
       x in [start_x_m + cx*res, start_x_m + (cx+1)*res]
       y in [start_y_m + cy*res, start_y_m + (cy+1)*res]
     (the inverse of wifi_match.score_candidates' cx/cy formula)
  2. projecting the two opposite corners with projectPoint (same as the live
     trail), then taking min/max for an axis-aligned <rect>.
This is the contract dreame-mower-map-card.js mirrors in JS (not executed here)."""
from __future__ import annotations


def _project_point(x_m, y_m, proj):
    # Character-equivalent to _dreame-map-core.js:projectPoint.
    px = (proj["bx2_mm"] - x_m * 1000) / proj["pixel_size_mm"]
    py = proj["height_px"] - (proj["by2_mm"] - y_m * 1000) / proj["pixel_size_mm"]
    return (px, py)


def _cell_rect(cx, cy, overlay, proj):
    res = overlay["resolution_m"]
    x0 = overlay["start_x_m"] + cx * res
    x1 = overlay["start_x_m"] + (cx + 1) * res
    y0 = overlay["start_y_m"] + cy * res
    y1 = overlay["start_y_m"] + (cy + 1) * res
    p00 = _project_point(x0, y0, proj)
    p11 = _project_point(x1, y1, proj)
    xmin, xmax = sorted((p00[0], p11[0]))
    ymin, ymax = sorted((p00[1], p11[1]))
    return (xmin, ymin, xmax - xmin, ymax - ymin)


def test_cell_rect_matches_projection():
    proj = {"bx2_mm": 20000.0, "by2_mm": 21000.0,
            "pixel_size_mm": 50.0, "width_px": 400, "height_px": 420}
    overlay = {"resolution_m": 2.0, "start_x_m": 0.0, "start_y_m": 0.0}
    # Cell (0,0) covers cloud x in [0,2] m, y in [0,2] m.
    x, y, w, h = _cell_rect(0, 0, overlay, proj)
    # 2 m / 0.05 m-per-px = 40 px square.
    assert round(w, 6) == 40.0
    assert round(h, 6) == 40.0
    # Corner (0,0) cloud -> px=(20000-0)/50=400, py=420-(21000-0)/50=0.
    # Corner (2,2) cloud -> px=(20000-2000)/50=360, py=420-(21000-2000)/50=40.
    assert round(x, 6) == 360.0   # min of {400, 360}
    assert round(y, 6) == 0.0     # min of {0, 40}


def test_cell_index_is_row_major():
    # idx = cy*width + cx, matching wifi_match.score_candidates.
    width = 3
    assert 1 * width + 2 == 5  # cell (cx=2, cy=1) -> data index 5
```

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_wifi_overlay_geometry.py -v`
Expected: PASS (pure Python; documents the contract).

- [ ] **Step 2: Implement the overlay in the card**

Rewrite `custom_components/dreame_a2_mower/www/dreame-mower-map-card.js` to the
following. (Changes: import `rssiToRgb`; read `wifi_overlay_opacity`; restore
`_wifiOn` from localStorage; wrap the SVG in a positioned container with a toggle
button; insert the `<g id="wifi">` layer first; repaint it when `wifi_overlay`
changes; show/hide the button.)

```javascript
// Live map card: SVG base <image> + client-accumulated trail + directional
// mower icon, animated between ~5s position messages, plus an optional
// translucent WiFi-coverage overlay toggled in-card. Reads the published
// stream (map_projection, point_seq, latest_point, track_snapshot,
// background_mode, wifi_overlay) from camera.dreame_a2_mower_map.
//
// Load as a Lovelace resource (type: module):
//   url: /dreame_a2_mower/dreame-mower-map-card.js
import {
  projectPoint,
  iconRotation,
  buildMowerIconSvg,
  rssiToRgb,
} from "./_dreame-map-core.js";

const ICON_PX = 32;
const GLIDE_MS = 5000;   // glide duration ~ the observed s1p4 cadence (~5s)
const WIFI_LS_KEY = "dreame-mower-wifi-overlay-on";

class DreameMowerMapCard extends HTMLElement {
  setConfig(cfg) {
    if (!cfg || !cfg.entity) throw new Error("entity is required");
    this._cfg = cfg;
    this._seq = -1;
    this._trail = [];
    this._iconAt = null;
    this._iconAngle = 0;
    this._anim = null;
    this._wifiKey = null;            // identity of the last-rendered overlay
    this._wifiOpacity =
      cfg.wifi_overlay_opacity != null ? Number(cfg.wifi_overlay_opacity) : 0.5;
    // Toggle state persists across reloads (per browser); default off.
    let on = false;
    try { on = window.localStorage.getItem(WIFI_LS_KEY) === "1"; } catch (e) { /* ignore */ }
    this._wifiOn = on;
  }
  set hass(hass) {
    this._hass = hass;
    const ent = hass.states[this._cfg.entity];
    if (!ent || !ent.attributes) return;
    const a = ent.attributes;
    if (!a.map_projection || !a.entity_picture) return;
    this._ensureSvg(a);
    const img = this.shadowRoot.getElementById("base");
    if (img && img.getAttribute("href") !== a.entity_picture) {
      img.setAttribute("href", a.entity_picture);
    }
    this._syncWifi(a);
    // Cold start / gap / session reset -> seed from snapshot.
    if (a.point_seq != null &&
        (this._seq < 0 || a.point_seq < this._seq || a.point_seq - this._seq > 1)) {
      this._seedFromSnapshot(a);
    }
    if (a.latest_point && a.point_seq > this._seq) {
      this._seq = a.point_seq;
      this._onNewPoint(a.latest_point, a.map_projection);
    }
    // Between sessions the live stream is empty (no latest_point, seq 0): draw
    // a STATIC icon at the last-known position so it's clear where the mower is
    // sitting. A live session (latest_point present, seq > 0) drives the icon
    // instead — handled above and skipped here. Heading isn't persisted, so the
    // idle icon keeps its default orientation. Known limitation: a manual move /
    // carrying the mower while idle won't be reflected until it next reports.
    const hasLivePoint = a.latest_point && a.point_seq > 0;
    if (!hasLivePoint && a.last_known_point) {
      const lp = a.last_known_point;
      this._iconAt = projectPoint(lp[0], lp[1], a.map_projection);
      const ang = iconRotation(lp[2], null, this._iconAt);
      if (ang != null) this._iconAngle = ang;
      this._placeIcon();
    }
  }
  _ensureSvg(a) {
    if (this.shadowRoot && this.shadowRoot.getElementById("svg")) return;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const p = a.map_projection;
    const iconUrl = this._cfg.icon_url || "/dreame_a2_mower/mower-icon.png";
    // The wifi <g> is FIRST in document order so SVG paint order keeps the
    // trail + mower icon on top of the overlay.
    this.shadowRoot.innerHTML =
      `<style>:host{display:block}.wrap{position:relative}` +
      `svg{width:100%;height:auto;display:block}` +
      `.trail{fill:none;stroke:rgb(178,223,138);stroke-width:3;` +
      `stroke-linejoin:round;stroke-linecap:round}` +
      `#wifiToggle{position:absolute;top:8px;right:8px;z-index:2;` +
      `font:12px/1 system-ui,sans-serif;padding:4px 8px;border-radius:6px;` +
      `border:1px solid rgba(0,0,0,.3);background:rgba(255,255,255,.85);` +
      `cursor:pointer;display:none}` +
      `#wifiToggle.on{background:rgb(120,200,120)}</style>` +
      `<div class="wrap">` +
      `<svg id="svg" viewBox="0 0 ${p.width_px} ${p.height_px}">` +
      `<g id="wifi" opacity="${this._wifiOpacity}"></g>` +
      `<image id="base" href="${a.entity_picture}" x="0" y="0" ` +
      `width="${p.width_px}" height="${p.height_px}"/>` +
      `<path id="trail" class="trail" d=""/>` +
      buildMowerIconSvg(iconUrl, ICON_PX) +
      `</svg>` +
      `<button id="wifiToggle" type="button">WiFi</button>` +
      `</div>`;
    // Base image must sit ABOVE the wifi layer; re-order so wifi is behind it.
    const svg = this.shadowRoot.getElementById("svg");
    const wifi = this.shadowRoot.getElementById("wifi");
    svg.insertBefore(wifi, svg.firstChild);
    const btn = this.shadowRoot.getElementById("wifiToggle");
    btn.addEventListener("click", () => this._toggleWifi());
  }
  _toggleWifi() {
    this._wifiOn = !this._wifiOn;
    try { window.localStorage.setItem(WIFI_LS_KEY, this._wifiOn ? "1" : "0"); }
    catch (e) { /* ignore */ }
    this._applyWifiVisibility();
  }
  _applyWifiVisibility() {
    const g = this.shadowRoot && this.shadowRoot.getElementById("wifi");
    const btn = this.shadowRoot && this.shadowRoot.getElementById("wifiToggle");
    if (g) g.setAttribute("display", this._wifiOn ? "inline" : "none");
    if (btn) btn.classList.toggle("on", this._wifiOn);
  }
  _syncWifi(a) {
    const btn = this.shadowRoot.getElementById("wifiToggle");
    const overlay = a.wifi_overlay;
    if (!overlay || !Array.isArray(overlay.data)) {
      if (btn) btn.style.display = "none";
      return;
    }
    if (btn) btn.style.display = "block";
    const key =
      `${overlay.width}x${overlay.height}@${overlay.start_x_m},${overlay.start_y_m}:` +
      `${overlay.data.length}`;
    if (key !== this._wifiKey) {
      this._wifiKey = key;
      this._renderWifi(overlay, a.map_projection);
    }
    this._applyWifiVisibility();
  }
  _renderWifi(overlay, proj) {
    const g = this.shadowRoot.getElementById("wifi");
    if (!g) return;
    const { data, width, height } = overlay;
    const res = overlay.resolution_m;
    const parts = [];
    for (let cy = 0; cy < height; cy += 1) {
      for (let cx = 0; cx < width; cx += 1) {
        const rssi = data[cy * width + cx];
        const rgb = rssiToRgb(rssi);
        if (!rgb) continue; // no-data sentinel
        const x0 = overlay.start_x_m + cx * res;
        const x1 = overlay.start_x_m + (cx + 1) * res;
        const y0 = overlay.start_y_m + cy * res;
        const y1 = overlay.start_y_m + (cy + 1) * res;
        const p00 = projectPoint(x0, y0, proj);
        const p11 = projectPoint(x1, y1, proj);
        const xmin = Math.min(p00[0], p11[0]);
        const ymin = Math.min(p00[1], p11[1]);
        const w = Math.abs(p11[0] - p00[0]);
        const h = Math.abs(p11[1] - p00[1]);
        parts.push(
          `<rect x="${xmin.toFixed(1)}" y="${ymin.toFixed(1)}" ` +
          `width="${w.toFixed(1)}" height="${h.toFixed(1)}" ` +
          `fill="rgb(${rgb.r},${rgb.g},${rgb.b})"/>`
        );
      }
    }
    g.innerHTML = parts.join("");
  }
  _seedFromSnapshot(a) {
    const snap = a.track_snapshot || [];
    this._trail = snap.map((pt) => projectPoint(pt[0], pt[1], a.map_projection));
    this._redrawTrail();
    if (this._trail.length) {
      this._iconAt = this._trail[this._trail.length - 1];
      const last = snap[snap.length - 1];
      const ang = iconRotation(
        last[2],
        this._trail[this._trail.length - 2] || null,
        this._iconAt
      );
      if (ang != null) this._iconAngle = ang;
      this._placeIcon();
    }
    this._seq = a.point_seq;
  }
  _onNewPoint(pt, proj) {
    const target = projectPoint(pt[0], pt[1], proj);
    const from = this._iconAt || target;
    const ang = iconRotation(pt[2], this._iconAt, target);
    this._trail.push(target);
    this._redrawTrail();
    this._animateIcon(from, target, ang == null ? this._iconAngle : ang);
  }
  _redrawTrail() {
    const path = this.shadowRoot.getElementById("trail");
    if (!path) return;
    path.setAttribute(
      "d",
      this._trail
        .map((q, i) => `${i ? "L" : "M"} ${q[0].toFixed(1)} ${q[1].toFixed(1)}`)
        .join(" ")
    );
  }
  _animateIcon(from, to, toAngle) {
    if (this._anim) cancelAnimationFrame(this._anim);
    const fromAngle = this._iconAngle;
    const dA = ((toAngle - fromAngle + 540) % 360) - 180; // shortest arc
    const start =
      (typeof performance !== "undefined" ? performance.now() : Date.now());
    const step = (now) => {
      const k = Math.min(1, (now - start) / GLIDE_MS);
      this._iconAt = [from[0] + (to[0] - from[0]) * k, from[1] + (to[1] - from[1]) * k];
      this._iconAngle = fromAngle + dA * k;
      this._placeIcon();
      if (k < 1) this._anim = requestAnimationFrame(step);
    };
    this._anim = requestAnimationFrame(step);
  }
  _placeIcon() {
    const g = this.shadowRoot.getElementById("mower");
    if (!g || !this._iconAt) return;
    g.setAttribute("visibility", "visible");
    g.setAttribute(
      "transform",
      `translate(${this._iconAt[0].toFixed(1)},${this._iconAt[1].toFixed(1)}) rotate(${this._iconAngle.toFixed(1)})`
    );
  }
  getCardSize() { return 6; }
  static getStubConfig() { return { entity: "camera.dreame_a2_mower_map" }; }
}
if (!customElements.get("dreame-mower-map-card")) {
  customElements.define("dreame-mower-map-card", DreameMowerMapCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "dreame-mower-map-card",
    name: "Dreame Mower Live Map",
    description: "Animated live map: base + trail + directional mower icon + WiFi overlay.",
  });
}
```

Note on paint order: the literal `<g id="wifi">` is written before `<image id="base">`, then the explicit `insertBefore(wifi, svg.firstChild)` is a belt-and-braces guarantee it stays the first child even if the innerHTML order is ever edited. The overlay therefore renders *under* the base PNG, trail, and icon — it tints the lawn without occluding anything. (If you prefer the colour to sit on TOP of the lawn PNG but still under trail/icon, move the `<g>` to just before `<path id="trail">` and drop the `insertBefore`. Default chosen: under the base, so cell colour blends with lawn texture like the standalone tab.)

- [ ] **Step 3: Run the geometry pin + full card-adjacent suite**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_wifi_overlay_geometry.py tests/protocol/test_extract_projection.py tests/integration/test_map_camera_attributes.py -v`
Expected: PASS. (No JS execution; the geometry/projection contracts the card mirrors are green.)

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/www/dreame-mower-map-card.js tests/protocol/test_wifi_overlay_geometry.py
git commit -m "feat(card): toggleable WiFi coverage overlay layer on the live map

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Inventory + docs — record the (presumed) anchoring, close the TODO

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory.yaml`
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml`
- Modify: `docs/TODO.md`

- [ ] **Step 1: Locate the WiFi heatmap inventory entry**

Run: `grep -n "wifimap\|wifi_map\|heatmap\|startX\|wifi_overlay" custom_components/dreame_a2_mower/inventory.yaml`
Expected: finds the existing wifimap OBJ entry (the heatmap body schema). Note its
key/anchor; the new verification attaches to it (or to the nearest WiFi surface).

- [ ] **Step 2: Append the overlay-anchoring verification (status `presumed`)**

Under that entry's `verifications:` list, append (using today's date 2026-06-08):

```yaml
      - date: "2026-06-08"
        status: presumed
        claim: "Live-map WiFi overlay anchors cells to the cloud frame by inverting wifi_match.score_candidates (cell (cx,cy) -> cloud box [startX_m+cx*res .. +(cx+1)*res] x [startY_m+cy*res .. ]) and projecting with the card's projectPoint; no flip needed. Forward projection onto the live map not yet visually confirmed."
```

Also update that entry's (or the file's) `status.last_seen` to `"2026-06-08"` if the
schema carries one. Run the inventory audit to confirm the file still validates:

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory -v`
Expected: PASS (schema validation green).

- [ ] **Step 3: Note the new camera attribute in entity-inventory**

Run: `grep -n "wifi_overlay\|map_projection\|DreameA2MapCamera\|live.*map.*camera\|map_static\|\"Map\"" custom_components/dreame_a2_mower/entity-inventory.yaml | head`
Find the live map camera entry (the one publishing `map_projection` / the live
stream). Add `wifi_overlay` to its documented attributes list (match the file's
existing structure for attribute lists — copy the shape of a sibling attribute
entry; do not invent new fields). If the entry has a `notes:`/`semantic:` field,
add: "Publishes wifi_overlay (active-map heatmap cell grid) consumed by the card's
overlay layer (2026-06-08)."

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_entity_inventory* tests/inventory -v 2>/dev/null || /data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory -v`
Expected: PASS (entity-inventory CI gate green).

- [ ] **Step 4: Remove the superseded TODO entry**

In `docs/TODO.md`, delete the entire `### WiFi heatmap overlay on the live map`
section (from that heading through its closing `---`, lines ~564-597). It is now
shipped; per CLAUDE.md, TODO.md is the open-work list only. (Do NOT migrate it to a
new in-tree history doc — the spec/plan + git history are the record.)

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/inventory.yaml custom_components/dreame_a2_mower/entity-inventory.yaml docs/TODO.md
git commit -m "docs: record wifi-overlay anchoring (presumed) + close TODO entry

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Verify, ship, and live-confirm

**Files:** none (build/verify/release + manual confirmation)

- [ ] **Step 1: Run the full test suite**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q`
Expected: PASS — baseline 1591 passed / 4 skipped, **plus** the new tests
(Task 1: 4, Task 2: 2, Task 3: 6, Task 4: 2). No regressions. If anything fails,
STOP and fix before shipping.

- [ ] **Step 2: Ship via the release pipeline**

The integration ships its `www/*.js` with the HACS download, so no separate
resource upload is needed for the card code; HACS pulls from origin/main.

Run the release script (handles version bump + tag + GitHub Release + HACS refresh
in one shot — see `feedback_subagent_release_pipeline`):
`./tools/release/release.sh` (or the repo's documented release entrypoint;
confirm the exact path with `ls tools/release/`).
Mind the HACS digit-boundary ladder: if the alpha counter would grow a digit
(e.g. a9 -> a10), bump the patch instead (see `feedback_hacs_version_ladder`).

- [ ] **Step 3: Reload in HA + browser hard-refresh**

After HACS updates the integration, reload the config entry (or restart HA) and
hard-refresh the dashboard so the new `dreame-mower-map-card.js` /
`_dreame-map-core.js` modules load (browser caches ES modules aggressively — see
`reference_lovelace_card_errors` for diagnosing a stale/error card).

- [ ] **Step 4: Live visual confirmation (promotes the inventory claim)**

On the Mower dashboard live map:
1. Confirm the **WiFi** toggle button appears (only when the active map has an
   archived heatmap; if none yet, press the `request_wifi_map` button / wait for
   the overnight cloud generation, then re-check).
2. Toggle it ON. Confirm: the trail and mower icon remain fully visible on top;
   toggling does not reset/clear the live trail; cells tint the lawn at ~0.5
   opacity with the same red→yellow→green gradient as the WiFi Coverage tab.
3. **Alignment check:** the coloured field should cover the lawn extent and sit
   correctly relative to the dock marker. If it is mirrored/rotated/offset,
   capture a screenshot and STOP — the anchoring assumption is wrong; revisit the
   cell→cloud-box mapping (the matcher convention) before promoting.
4. If alignment is correct, update the Task-5 `inventory.yaml` verification:
   change `status: presumed` → `status: verified` and add
   `evidence: "app-screenshot:<name>"`, then commit:

```bash
git add custom_components/dreame_a2_mower/inventory.yaml
git commit -m "docs: confirm wifi-overlay anchoring on the live map (screenshot)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Finish the branch**

Use `superpowers:finishing-a-development-branch`. Per CLAUDE.md doc lifecycle, move
this spec + plan OUT of the tree to
`/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/superpowers/{specs,plans}/`
as part of the wrap-up (target state: zero `docs/superpowers/` in-tree).

---

## Self-review notes

- **Spec coverage:** §Architecture → T1+T2; §Geometry → T1 (payload) + T4 (rect math + geometry pin); §Coordinator cache → T1; §Camera attribute → T2; §Card layer/toggle/opacity → T4; §Gradient parity → T3; §Liveness (repaint-on-change only) → T4 `_syncWifi` key guard; §Testing → T1–T4 tests + T6 step 1; §live-confirmation → T6 step 4; supersede TODO → T5. No gaps.
- **Type consistency:** payload keys `data/width/height/resolution_m/start_x_m/start_y_m` are identical across T1 (producer), T2 (test), T4 (`_renderWifi` consumer) and the geometry pin. `rssiToRgb` returns `{r,g,b}|null` in T3 and is consumed exactly that way in T4. `_resolve_active_map_wifi_entry` / `active_map_wifi_overlay` / `_schedule_active_map_wifi_load` names match between T1 (defn), T2 (camera call sites).
- **Placeholders:** none — every code step shows complete code; the only deliberately open items are the inventory anchor key (T5 step 1 locates it) and the entity-inventory attribute-list shape (T5 step 3 says to copy a sibling), both of which require reading the live file structure rather than guessing.
```
