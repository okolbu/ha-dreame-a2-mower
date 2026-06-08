# WiFi coverage overlay on the live map — design

**Date:** 2026-06-08
**Status:** approved (brainstorming) — pending plan
**Supersedes:** the `TODO.md` "WiFi heatmap overlay on the live map" entry
(2026-05-09), whose plan assumed *server-side* compositing in `map_render`.
The live-map rehaul (2026-05-31, v1.0.18a4) moved the trail + icon
client-side into a self-contained SVG card, so the overlay is now a
**client-side card layer**, not a renderer change.

## Goal

Let the user toggle a translucent WiFi-coverage layer on/off on the live
map card, drawn in the same coordinate frame as the lawn map, mower icon,
and path — without interfering with any of them.

## Decisions (from brainstorming)

| Decision | Choice |
|---|---|
| Render approach | SVG `<rect>` cells in a `<g>` layer, drawn with the card's existing `projectPoint` |
| Toggle | In-card corner `<button>`; client-side state; **default off**; persisted in `localStorage` |
| Opacity | Fixed `wifi_overlay_opacity` card-config key (default `0.5`) |
| Data source | Auto-match the live map's **active** `map_id` |
| Staleness indicator | None |
| Gradient | Port `_rssi_to_rgb` to JS, pinned by a Python-parity test |

## Architecture / data flow

```
coordinator  (active-map WiFi body, lazily loaded + cached)
   └─► camera.dreame_a2_mower_map  .attributes.wifi_overlay   ← NEW attribute
          └─► dreame-mower-map-card.js
                 ├─ <g id="wifi" opacity=cfg>  rect layer   ← NEW (paint order: first)
                 ├─ <path id="trail">          (unchanged)
                 └─ <g id="mower">             (unchanged, last → always on top)
                 + corner toggle button + localStorage state ← NEW
```

The card keeps its single-entity contract: the overlay rides along as a
new attribute on the same `camera.dreame_a2_mower_map` it already reads.

## Geometry — reuse the matcher's confirmed convention

`wifi_match.py:score_candidates` already maps a cloud-frame sample
`(x_m, y_m)` to a heatmap cell, in production and under test:

```
cx = int((x_m - start_x_m) / res)     # col index grows with +X
cy = int((y_m - start_y_m) / res)     # row index grows with +Y
grid_index = cy * width + cx          # row-major
```

Those `(x_m, y_m)` samples are recorded in `LiveMapState.wifi_samples` at
s1p1 heartbeats — the **same cloud frame** as the live track points the
card already projects with `projectPoint`. The overlay inverts the
mapping: cell `(cx, cy)` covers the cloud-metre box

```
x ∈ [start_x_m + cx·res,  start_x_m + (cx+1)·res]
y ∈ [start_y_m + cy·res,  start_y_m + (cy+1)·res]
```

Project the two opposite corners with the existing `projectPoint`, take
`min/max`, draw one `<rect x y width height>`. `projectPoint` is affine
with axis flips, so a cloud-frame box stays an axis-aligned screen rect.

**No `flip_x` / `flip_y` needed.** Those escape hatches exist only on the
standalone PNG path, which lays cells on a fixed `CELL_PX` grid and never
anchors to coordinates. The overlay derives every cell position from the
matcher convention + `projectPoint`, so it is anchored by construction.

**Confidence / verification [UNVERIFIED until live-confirmed]:** the
matcher convention gives a high prior that the anchoring is correct first
try, but the cell→cloud-frame *forward* projection has never been rendered
against the live map before. A one-time live visual-confirmation pass
(overlay vs dock marker + lawn extent) is required before the geometry is
marked `confirmed` in `inventory.yaml`. Per repo fact-discipline, the
overlay-anchoring claim ships `presumed` and is promoted only on a
screenshot.

## Component changes

### Coordinator (`coordinator/_wifi_archive.py`)

`extra_state_attributes` runs in the event loop and must not hit disk.
Add an active-map WiFi-body cache mirroring the selected-camera path
(`_async_load_wifi_body` / `_get_wifi_body_cached`):

- Resolve the newest `_wifi_archive_index` entry whose
  `map_id == _active_map_id` (same logic as
  `DreameA2WifiPerMapCamera._resolve_entry`).
- Lazy-load its body via the executor; cache the decoded dict.
- Invalidate the cache when the active map changes or a new WiFi archive
  is ingested.
- Expose a cheap synchronous accessor for the camera attribute (returns
  the cached dict or `None`; never blocks).

### Camera attribute (`_camera_map.py`)

Add to `extra_state_attributes`, present only when a body is cached:

```python
attrs["wifi_overlay"] = {
    "data": [...],            # flat row-major RSSI ints; 1 = no-data
    "width": int,
    "height": int,
    "resolution_m": float,    # metres per cell
    "start_x_m": float,       # cm→m converted here
    "start_y_m": float,
}
```

Absent attribute ⇒ the card draws no overlay and hides the toggle.

### Card (`www/dreame-mower-map-card.js` + `www/_dreame-map-core.js`)

- **Layer:** build `<g id="wifi" opacity="${cfg}">` and insert it **before**
  `#trail`/`#mower` in `_ensureSvg`, so SVG paint order keeps the path and
  icon on top. Populate it from `wifi_overlay` only when the attribute
  changes (track a hash/identity); skip `rssi === 1` cells.
- **Non-interference:** `_onNewPoint` / `_animateIcon` / `_redrawTrail`
  touch only `#trail` and `#mower`; they never read or rebuild `#wifi`.
  Toggling/repainting the overlay cannot perturb the live trail or icon.
- **Toggle:** a small corner `<button>` in the shadow DOM. State
  `this._wifiOn` (default `false`), persisted to `localStorage` under a
  per-card key; restored in `setConfig`. Button + layer hidden entirely
  when no `wifi_overlay` attribute is present.
- **Opacity:** `wifi_overlay_opacity` config key (default `0.5`) → the
  `<g opacity>`.
- **Gradient:** port `_rssi_to_rgb` (red→yellow→green over −99→−50 dBm,
  `1` = transparent) into `_dreame-map-core.js` as `rssiToRgb`, and pin it
  with a Python-parity test following the `iconRotation` corpus-test
  pattern, so the JS and Python gradients cannot drift.

## Liveness

WiFi data is occasional (overnight cloud generation + the manual
`request_wifi_map` button). The overlay is decoupled from the ~5 s
position stream: it repaints only when the `wifi_overlay` attribute
changes, which is rare, and imposes zero cost on the live animation. It
shows *last-known coverage*, by design — no staleness badge.

## Testing

- **JS↔Python gradient parity** — new test asserting `rssiToRgb` matches
  `wifi_map_render._rssi_to_rgb` across the dBm range + the `1` sentinel.
- **Camera attribute** — `wifi_overlay` present/shape when a body is
  cached; absent when none; cm→m conversion correct.
- **Coordinator cache** — resolves the active-map entry; invalidates on
  active-map change / new archive; accessor never blocks.
- **Geometry** — unit test that a known cell `(cx, cy)` + projection
  produces the expected screen rect (inverse of the matcher formula).
- Existing live-map card behaviour (trail, icon, idle icon) unchanged —
  guarded by the current suite.
- **Live visual confirmation** — manual: overlay aligns with dock + lawn
  extent; promote the anchoring claim to `confirmed` in `inventory.yaml`
  on a screenshot.

## Scope / non-goals

**In:** overlay `<g>` layer, in-card toggle (default off, localStorage),
config opacity, coordinator active-map cache + camera attribute, gradient
parity test, one live-confirmation pass, fold/close the `TODO.md` entry.

**Out:** changing the standalone WiFi camera or the WiFi Coverage tab; the
`flip_x` / `flip_y` booleans; a runtime opacity slider; any LiDAR overlay;
`map_render` server-side compositing (explicitly abandoned).

## Cross-refs

- `www/dreame-mower-map-card.js`, `www/_dreame-map-core.js` — the card.
- `_camera_map.py` — `extra_state_attributes`.
- `coordinator/_wifi_archive.py` — WiFi archive refresh + matcher plumbing.
- `wifi_match.py:score_candidates` — the cell↔coordinate convention reused here.
- `wifi_map_render.py:_rssi_to_rgb` — gradient ported to JS.
- `docs/research/cloud-map-geometry.md` — projection background.
- Supersedes `docs/TODO.md` "WiFi heatmap overlay on the live map".
