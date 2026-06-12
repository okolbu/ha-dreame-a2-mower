# Map-edit frame verification — pixel↔meter inverse + points_m formula (2026-06-12)

**Task 1 of the Interactive Map-Editor Card plan (GATING).** Confirms that the
`o=215` edit-frame metres equal the `projectPoint(x_m, y_m, proj)` position frame
already used by the live/replay cards, so the card can convert pixels↔metres and
publish object geometry that lands exactly over the rendered object.

## Verdict: **PASS** — edit-frame == projectPoint frame. No reflection, no offset.

- The `o=215` wire `points` (metres) are **the final on-screen geometry expressed
  directly in the cloud frame** (cloud-mm ÷ 1000). They are *not* in any
  reflected/rotated intermediate frame.
- `projectPoint(wire_metres)` overlays the decoded no-go mask exactly (x exact;
  y off by a constant **+1.0 px** — the `height_px` vs `(height_px − 1)` flip
  convention, **not** a frame mismatch). See overlay PNG below.
- The proposed inverse recovers the wire metres to floating-point exactness
  (residual ≈ 1e-15). **Locked as-is, no correction needed.**

## Sources

- Map blobs + `o=215` creates: `/data/claude/homeassistant/dreame-app-capture-2026-06-09/miio-cloud-13267-http.jsonl`
  (the `:13267 device/sendCommand` and `iotuserdata/getDeviceData` flows).
- Decoder: `custom_components/dreame_a2_mower/map_decoder.py`
  (`join_map_parts` → `parse_cloud_map`); rotation helper
  `protocol/cloud_map_geom.py::_rotate_path_around_centroid`.
- Projection fields as published by the camera:
  `custom_components/dreame_a2_mower/_camera_map.py::extra_state_attributes`
  → `map_projection = { bx1_mm, by1_mm, bx2_mm, by2_mm, pixel_size_mm, width_px, height_px }`
  (`projectPoint` only consumes `bx2_mm, by2_mm, pixel_size_mm, height_px`).
- Forward projection: `www/_dreame-map-core.js::projectPoint`.

## Object used (clean angle=0 polygon no-go)

A captured create (`o=215 type:2`, polygon no-go) whose host map was re-read and
decodable right after the commit:

```
# wire create  (ts=1781024367, did=-112293549, siid:2 aiid:50 o=215)
{"id":-1,"type":2,"points":[[-1.68,-8.56],[-6.22,-8.56],[-6.22,-2.52],[-1.68,-2.52]],"radius":0}
ACK: out:[{m:"r",q:3561,r:0}]   (r=0 accepted)

# host map re-read  (ts=1781024533 getDeviceData) → forbiddenAreas:
[[101,{"id":101,"type":2,"shapeType":2,
       "path":[{"x":-1680,"y":-8560},{"x":-6220,"y":-8560},
               {"x":-6220,"y":-2520},{"x":-1680,"y":-2520}],
       "angle":0}]]
```

**Step A — wire metres == raw cloud path mm ÷ 1000:** all 4 corners match exactly
(`-1.68 == -1680/1000`, …). The device assigned `id:101` on commit (per the
rotate-edit doc, `id:-1` → device-assigned real id).

## Numbers (host map projection)

```
bx1_mm = -10920.0   by1_mm = -14080.0
bx2_mm =  20890.0   by2_mm =  21580.0
pixel_size_mm = 50.0
width_px = 637   height_px = 714
```

### Step B — projectPoint(wire metres) → pixels (all in-bounds)

```
[-1.68, -8.56] -> (451.40, 111.20)
[-6.22, -8.56] -> (542.20, 111.20)
[-6.22, -2.52] -> (542.20, 232.00)
[-1.68, -2.52] -> (451.40, 232.00)
```
All within [0,637]×[0,714]. ✔

### Step C/D — overlay vs the decoded no-go mask (served-PNG pixels)

Renderer mask formula (from `_camera_map.py` calibration / `map_render`):
`px = (bx2 − x_mm)/grid`, `served_py = (height_px − 1) − (by2 − y_mm)/grid`.

```
corner                projectPoint        renderer-mask      Δ(px)
(-1680,-8560)         (451.40,111.20)     (451.40,110.20)    (0.00, +1.00)
(-6220,-8560)         (542.20,111.20)     (542.20,110.20)    (0.00, +1.00)
(-6220,-2520)         (542.20,232.00)     (542.20,231.00)    (0.00, +1.00)
(-1680,-2520)         (451.40,232.00)     (451.40,231.00)    (0.00, +1.00)
```

x is exact; y differs by a **constant +1.0 px** because `projectPoint` uses
`height_px −` while the mask uses `(height_px − 1) −`. This is a known 1-px
rounding convention, **not** a frame reflection/offset — the geometry overlays.
Visual: `map-edit-frame-verification-overlay.png` (green = `projectPoint(wire)`
corners, red = decoded no-go mask; corners sit on the mask).

### Step E — inverse round-trip is exact

`pixelToMeters(projectPoint(wire))` recovers the wire metres to ≈1e-15:

```
(451.40,111.20) -> (-1.6800, -8.5600)   d=(0, 3.5e-15)
(542.20,111.20) -> (-6.2200, -8.5600)   d=(-3.5e-15, 3.5e-15)
(542.20,232.00) -> (-6.2200, -2.5200)   d=(-3.5e-15, 0)
(451.40,232.00) -> (-1.6800, -2.5200)   d=(0, 0)
```

## Step 4 — rotation sign for `points_m` (LOCKED: `−angle`)

The cloud stores an exclusion object as `(path_mm, angle_deg)`. The decoder
produces its (visually-confirmed, shipped) render via
`rotate(path_mm, −angle)` then a midline reflection
(`map_decoder.py::_collect_exclusion_entries`, `cloud_map_geom`).

Two facts lock the sign:

1. **Wire `points` carry the final, already-rotated corners.** The rotate-edit
   capture's rotated square
   `points:[[-4.71,-9.87],[-6.05,-7.19],[-3.37,-5.85],[-2.03,-8.53]]` measures as
   a true **3.00 m × 3.00 m** square at **~26.6°** (first edge 116.57° = 90+26.6),
   confirming the wire already holds the on-screen geometry — the app does **not**
   send a separate angle for it (`angle≈0` in the stored `path`).
2. **`projectPoint(rotate(path, −angle)/1000)` reproduces the decoder's rendered
   pixels exactly; `+angle` does not.** Across the three in-corpus nonzero-angle
   forbidden objects (`angle = 0.03, −0.03, 0.04`):

   ```
   sign −angle : max pixel error vs decoder render = 0.0000  ✔ MATCH
   sign +angle : max pixel error vs decoder render = 0.13–0.16  ✗
   ```
   (decoder pre-reflection points == `rotate(path, −angle)` to ≤1e-12, confirming
   the decoder convention the card must mirror.)

So when reconstructing the edit-frame metres of an existing exclusion object from
its raw cloud `(path_mm, angle)`:

> **`points_m = rotate(path_mm, −angle) / 1000`** (rotation about the path
> centroid, CCW-positive in the cloud X/Y frame — same as
> `_rotate_path_around_centroid`).

For a brand-new object drawn in the card, `points_m` are simply the corner
positions in the position/projectPoint frame (no rotation term — the geometry is
already final), sent on the wire as `points` (metres) with `radius:0` for
polygons.

---

## LOCKED FORMULAS (consumed by Task 3 + Task 4)

`proj` = `camera.dreame_a2_mower_map`'s `map_projection`
(`bx2_mm, by2_mm, pixel_size_mm, height_px`).

**Forward (metres → pixels)** — unchanged, already shipped in `_dreame-map-core.js`:
```
px = (bx2_mm − x_m*1000) / pixel_size_mm
py = height_px − (by2_mm − y_m*1000) / pixel_size_mm
```

**Inverse — `pixelToMeters(px, py, proj)` (LOCKED, verified exact):**
```
x_m = (bx2_mm − px*pixel_size_mm) / 1000
y_m = (by2_mm − (height_px − py)*pixel_size_mm) / 1000
```

**`points_m` for an existing exclusion object (LOCKED):**
```
points_m = rotate(path_mm, −angle) / 1000      # centroid rotation, CCW-positive cloud frame
```
(New objects: `points_m` = the card's drawn corners in the projectPoint frame,
sent directly as `points` in metres.)

## Reproduction

Throwaway scripts (not committed): decode via the
`spec_from_file_location` package-skeleton trick (register
`dreame_a2_mower` + `dreame_a2_mower.protocol` namespaces, exec
`protocol/cloud_map_geom.py` then `map_decoder.py`), then
`M.join_map_parts(getDeviceData['data'])` → `M.parse_cloud_map(joined)`.
Python: `/data/claude/homeassistant/.venv-vanilla/bin/python`.
