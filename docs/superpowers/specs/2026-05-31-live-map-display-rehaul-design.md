# Live-map display system — rehaul design

**Date:** 2026-05-31
**Status:** Design — pending review
**Topic:** Unify the live map and session-replay rendering onto one client-side
SVG-animation model; make the background lifecycle-driven, the mower icon
direction-correct, and the whole pipeline observable.

---

## 1. Why this exists

Three user-visible defects have each survived multiple point-fixes with **no
visible progress**:

1. **Background stripes persist through the ~41 s reorientation window.** When a
   session starts (e.g. *head to maintenance point*), the live-map background
   should switch from the striped idle-preview to the active (green) view *as
   soon as the session starts*. Today it only flips after the first position
   message — which the corpus shows arrives a **median of 41 s** (p90 44 s, max
   263 s) after the session-start signal.
2. **The mower icon advances only every 2–3 messages** (stutter).
3. **The icon faces the wrong way a lot of the time**, despite a prior fix that
   derived heading from the x/y motion delta.

### The meta-root-cause

Every prior fix targeted a **misdiagnosed cause**, and with **zero render
observability** nobody could see the fix had missed. The corpus (below) is the
feedback loop that was absent. Structurally:

- **No single render-intent model.** Each of ~6 trigger sites
  (`s2p1`→REPOSITIONING, dock-arrival, active-session s1p4, between-session
  s1p4, MAPL, 2-min refresh) independently recomputes background-mode +
  position + heading-source inline. The `_StateProxy` hack in
  `coordinator/_rendering.py:336` literally stitches `MowerState` and the state-
  machine snapshot together at render time.
- **Three divergent icon compositors** (`map_render/trail.py:186`,
  `trail.py:325`, `map_render/main_view.py:208`) apply **opposite vertical-flip
  treatment** to the icon. A heading fix in one path leaves the others wrong —
  and the path actually used for a to-point cruise is often *not* the one being
  edited.
- **The live map is a flat server-rendered PNG**, so the icon jumps frame-to-
  frame; there is no interpolation and the per-render token refresh is itself a
  source of stutter.

### Corpus grounding (71,936 position messages, all 9 `probe_log_*.jsonl`)

`analyze_move_corpus.py` (in `/data/claude/homeassistant/`) establishes the
facts the redesign depends on:

| Fact | Measured | Consequence |
|---|---|---|
| Frame mix | **99.2 %** are 33-byte full frames **with a heading byte**; 0.8 % are 8-byte beacons | "beacons lack heading" is a rounding error, not the main problem |
| Cadence | median **5.0 s** for both 33B and 8B (mean 4.8 s, p99 7 s) | the 1 s render throttle and 0.5 s/20 cm dedup can **never** fire → **#2 is not server throttling** |
| byte-heading vs motion-vector | median error **2.5°**, 72 % < 15° (p90 66°, p99 160° on pivots) | the **byte heading is excellent**; the vector derivation is *noisier* and was the wrong fix |
| move distance/frame | median **1.07 m**; only 10.5 % < 20 cm | dedup confirmed irrelevant |
| s2p1-active → first move | median **41 s**, p90 44 s, max 263 s | **#1 quantified**: background must be lifecycle-driven, not position-driven |

**Re-diagnosis:**

- **#1** — real and quantified. Fix: background keys on the state-machine
  *activity*, which transitions ~41 s before the first move.
- **#2** — not the server throttle (5 s cadence proves it). Fix structurally via
  **client-side interpolation** over the known cadence, not by tuning a throttle.
- **#3** — not the heading *value* (median 2.5° correct). Fix the **render
  convention**: one icon, one flip convention, trust the byte heading; derive
  from the motion vector only for the 0.8 % headingless beacons.

---

## 2. The core idea

There are already **two** rendering systems:

- **Live map** — server renders a full PNG (`_main_view_png`) every frame
  (base + trail + icon, all in PIL); shown via picture-entity / the
  `dreame-mower-live-image-card` (which just swaps `<img src>`).
- **Session replay** (`www/dreame-mower-replay-card.js`) — a **client-side SVG
  card**: a `<svg viewBox>` with the server base-map PNG as an `<image>`
  backdrop, and a client-animated trail (`<path>` stroke-dash reveal) + a
  `#head` marker, positioned via a `map_projection` read from entity
  attributes, animated with `requestAnimationFrame`. It glides smoothly and
  looks markedly better — but its marker is a **round circle** (no heading).

**The rehaul unifies the live map onto the replay's SVG-animation model.** This
is *less* work than it sounds, because the base PNG and projection already
exist, and it turns all three bugs into structural non-issues:

- The server renders only the **base** (lawn + zones + dock + the
  stripes-or-green background). The base re-renders **rarely** — on map change
  or on a **background-mode flip driven by a state-machine activity
  transition**. That flip is lifecycle-driven and position-independent → **#1
  fixed**, ~41 s earlier.
- The **trail + mower icon move to the client SVG overlay**, fed by a published
  position/heading stream. The client **interpolates** the icon from the
  previous point to the latest over the measured inter-message interval → smooth
  glide → **#2 fixed** regardless of server render cadence or token refresh.
- The icon is drawn **once** in SVG with **one** rotation convention, rotated by
  the trusted byte heading → **#3 fixed**. The same directional icon replaces
  the replay card's round circle, so **live and replay share one icon + heading
  + projection model**.

This deletes the three PIL compositors, the `_StateProxy` hack, and the per-
trigger heading/throttle logic.

---

## 3. Goals / non-goals

### Goals
- Background reflects "is a session active" within one state-machine tick of the
  activity transition (target: < 2 s after session start, vs 41 s today).
- Mower icon animates smoothly between position messages (no visible per-message
  jump) and points in the direction of travel.
- **One** icon/heading/projection convention shared by live and replay, pinned
  by a corpus-backed test.
- Every render/publish emits one structured log line so the next anomaly is
  diagnosable from a log, not a live undock.
- Net deletion of code: 3 compositors → 1, `_StateProxy` removed, scattered
  render triggers → one publisher.

### Non-goals
- Rendering the base-map *geometry* client-side. The base stays a server PNG
  `<image>` backdrop (lawn/zone/dock geometry is non-trivial PIL work and
  changes rarely).
- Changing the protocol decode, the session-archive format, or the
  area-delta role classification (CLAUDE.md "Session replay data model").
- LiDAR (3D) card and WiFi heatmap rendering — out of scope.
- Replacing the work-log / per-map static cameras (still server PNGs).

---

## 4. Architecture

```
                         STATE MACHINE  (owns current_activity, mow_session)
                                │  activity transition
                                ▼
   coordinator/_rendering.py  ──┴──────────────────────────────────────────┐
     MapDisplayState (derived, pure):                                       │
       background_mode  ← f(current_activity, action_mode)                  │
       base_dirty       ← background_mode changed OR map md5 changed        │
                                │                                           │
        ┌───────────────────────┴───────────┐                              │
        ▼ (only when base_dirty)             ▼ (every position push)        │
   render_base(map, background_mode)    publish live stream:                │
     → base PNG (lawn+zones+dock+bg)       latest_point {x,y,heading,seq,t} │
     → served at /…/map.png?v=<md5>        background_mode, activity         │
        │                                  map_projection                   │
        ▼                                  (+ track_snapshot on cold-start)  │
   camera.…_map entity_picture ───────────────────────────────────────────┘
        │                                            │
        ▼ both consumed client-side                  ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  www/dreame-mower-map-card.js  (NEW shared SVG card)               │
   │   <svg viewBox=w×h>                                                │
   │     <image href=base.png>          ← background (stripes / green)  │
   │     <path  class=trail>            ← client-accumulated, animated  │
   │     <g     id=mower>               ← directional icon, rotate(θ)   │
   │   live mode:  append latest_point on seq++, animate icon over Δt   │
   │   replay mode: play archived track (existing behaviour) + icon     │
   └──────────────────────────────────────────────────────────────────┘
```

### 4.1 `MapDisplayState` — the single render-intent (server)

A small pure dataclass derived once per coordinator update, replacing the
`_StateProxy` and the per-trigger inline logic:

```python
@dataclass(frozen=True)
class MapDisplayState:
    background_mode: BackgroundMode      # STRIPES | GREEN_DARK | GREEN_LIGHT | EDGE | SPOT
    active_map_id: int | None
    # icon/trail are published as a stream, not baked into this struct
```

`background_mode` is a **pure projection of the state machine**:

```
if mow_session == IN_SESSION or current_activity in {REPOSITIONING, RETURNING,
        CRUISING_TO_POINT, MOWING, PAUSED, CHARGE_RESUME, DRIVING_BLADES_UP,
        FAST_MAPPING}:
    → GREEN_DARK   (active; the green active view)
else  (IDLE / AT_POINT / AT_DOCK idle):
    → idle preview by action_mode:
        ALL_AREAS|ZONE → STRIPES
        EDGE           → EDGE
        SPOT           → SPOT
```

The decisive change vs today: the "active" set is **every non-idle activity**,
not just `REPOSITIONING` + `live_map.is_active()`. The reorientation window
(`REPOSITIONING`, entered on the s2p1 undock/return transition ~41 s before the
first move) now maps to GREEN, so the stripes clear immediately. This is
**state-machine-derived** (the decision agreed during brainstorming): the
renderer holds no parallel session state.

> Optimistic-at-dispatch is **not** required: the state machine already enters
> `REPOSITIONING`/`CRUISING_TO_POINT` on the device echo within a few seconds of
> dispatch — far inside the 41 s gap. If a later measurement shows the echo lags
> unacceptably, an optimistic `current_activity` set in
> `start_go_to_point`/`start_mowing_*` is a localized follow-up, not part of
> this rehaul.

### 4.2 Server renders the base only

`_render_main_view` is replaced by `_render_base(map_data, background_mode)`
producing the base PNG (lawn + zones + dock + the stripes/green background +
last-session obstacle overlay between sessions). It is invoked **only** when
`base_dirty` — i.e. `background_mode` changed or the active map's md5 changed.
No trail, no icon are drawn server-side. The output is served at the existing
`/api/dreame_a2_mower/map.png?v=<sha1>` view; `v` keying on the base bytes means
the URL changes exactly when the background flips, so the client `<image>`
re-fetches precisely then.

`render_main_view`, `render_with_trail`, the two trail-path icon compositors,
`_composite_mower_icon`, and `_StateProxy` are **deleted**. `render_base_map`
and the pre-start preview builders (`_render_pre_start_*`) survive (they produce
the background). The `map_render/` package shrinks to: `_geometry`, `base_map`,
`main_view` (now base + background dispatch only, no trail/icon), `work_log`.

### 4.3 Server publishes the live stream

On every position push (`_on_state_update`), instead of rendering, publish onto
the live-map camera entity's attributes:

| Attribute | Meaning |
|---|---|
| `map_projection` | `{bx1_mm,by1_mm,bx2_mm,by2_mm,pixel_size_mm,width_px,height_px}` — same dict the replay card consumes; replaces the ad-hoc `calibration_points` |
| `background_mode` | string, for client labels / debug |
| `point_seq` | monotonic int, ++ on each appended point |
| `latest_point` | `[x_m, y_m, heading_deg|null, t_unix]` |
| `track_snapshot` | full session-so-far `[[x,y,heading,t],…]`, **only** rewritten on session begin / cold-start / seq gap |

**Efficiency:** the card accumulates the trail itself from `latest_point` as
`point_seq` increments — only one point per push crosses the wire. The full
`track_snapshot` is published just at session-begin and when the card reports it
missed points (or on its first load), so steady-state pushes stay tiny. The
live-map camera entity is **excluded from the recorder** (live-only; no history
value) so the streamed attributes don't bloat the DB.

Heading on `latest_point` is the **byte heading** when the frame carried one
(99.2 %); `null` for the 0.8 % beacons — the client falls back to the
last-segment screen vector for those (see §5).

### 4.4 The shared client card

New `www/dreame-mower-map-card.js` (or refactor the replay card to a shared
core + two thin entry points — see §7). Two modes:

- **live** (`entity: camera.dreame_a2_mower_map`): on each `hass` push, read
  `latest_point`/`point_seq`; if `seq` advanced, append the segment to the trail
  `<path>` and **animate the `#mower` icon** from its current rendered position
  to the new point over `Δt = clamp(measured_interval, 1 s, 7 s)` via
  `requestAnimationFrame`, interpolating position and slerping the rotation. The
  glide finishes ~as the next point arrives → continuous motion. On a `seq` gap
  or first load, seed from `track_snapshot`.
- **replay** (`entity: <archived session>`): existing compressed-timeline
  playback, unchanged — but its marker becomes the directional icon.

Both modes share `_projectPoint` (already correct: `map_render/main_view.py`
flip ⇄ `replay-card.js:73-76`) and the icon-rotation function (§5).

---

## 5. The single icon + heading convention (fixes #3)

The base PNG is flipped (`FLIP_TOP_BOTTOM`) before serving. The replay card
already projects cloud-mm → screen-px consistently with that flip
(`replay-card.js:70-78`):

```
px = (bx2_mm - x_mm) / grid                  # cloud +X → screen LEFT
py = height_px - (by2_mm - y_mm) / grid      # cloud +Y → screen DOWN
```

So a cloud motion `(dx, dy)` maps to a **screen** motion `(dpx, dpy) =
(-dx, +dy)/grid`. The on-screen travel angle (SVG y-down) is therefore:

```
θ_screen = atan2(dy, -dx)        # = 180° − φ, where φ = cloud motion angle
```

The byte heading `H` is the **cloud** motion angle `φ` (`0° = +X`), validated by
the corpus at median 2.5° vs `atan2(dy_cloud, dx_cloud)`. For an icon whose
source art points **up** (screen −y), the SVG rotation (CW-positive in y-down
space) that aligns it with travel is:

```
A = θ_screen + 90°  = (270° − H) mod 360        # applied as transform="rotate(A, cx, cy)"
```

**This formula is derived, not authoritative — the corpus test pins it
(§8).** Heading source priority:

1. `latest_point.heading_deg` (byte heading) when present — **always preferred**
   (the 2.5° datum). Do **not** override it with the motion vector.
2. Else (0.8 % beacons, or a stationary first point): the screen-space vector
   from the previous rendered position; if that is < ~5 cm, keep the last
   rendered angle (don't spin on noise).

There is exactly **one** implementation of `A`, used by both modes and both the
live and archived icon. The opposite-flip divergence is gone because there is
only one compositor and it operates in the single SVG screen frame.

---

## 6. Trigger consolidation

All position/lifecycle handling collapses to:

| Event | Action |
|---|---|
| state-machine activity transition | recompute `MapDisplayState`; if `background_mode` changed → `_render_base`; always re-publish `background_mode` |
| position push (s1p4, any frame len) | append to live track; `point_seq++`; publish `latest_point` |
| session begin | publish fresh `track_snapshot` (empty) + `background_mode=GREEN` |
| active-map / MAPL change | `base_dirty`; `_render_base`; new `map_projection` |
| dock arrival / finalize | activity → IDLE → `background_mode` recompute → base flips to idle preview |

The 2-minute cloud refresh no longer needs to render the live view (only ensures
the base is current). The leading-edge 1 s throttle, the 3 s/0.3 m between-
session throttle, `_maybe_rerender_between_session_icon`, and the
`_StateProxy` are removed.

---

## 7. Code-organization plan

- **Server**
  - `coordinator/_rendering.py`: replace `_render_main_view` family with
    `_compute_display_state()` (pure), `_render_base()`, `_publish_live_stream()`.
    Delete `_maybe_rerender_between_session_icon`, `_rerender_live_trail`,
    `_StateProxy`, `_current_mower_heading` (icon heading now client-side).
  - `mower/state_snapshot.py` / state machine: add the `background_mode`
    projection helper (pure function of the snapshot) — co-located with the
    snapshot so it's the single source of the active/idle predicate.
  - `map_render/`: drop `trail.py`; trim `main_view.py` to base+background.
  - `_camera_map.py`: `DreameA2MapCamera` publishes the §4.3 attributes;
    `entity_picture` = base PNG URL (unchanged shape). Exclude entity from
    recorder.
- **Client** — factor `replay-card.js` into:
  - `_map-core.js` (shared): SVG scaffold, `_projectPoint`, `iconRotation(H,
    prevScreenXY, curScreenXY)`, the `#mower` directional `<g>`, trail-append.
  - `dreame-mower-replay-card.js`: archived-playback timeline (thin).
  - `dreame-mower-map-card.js`: live incremental animation (thin). Replaces the
    `dreame-mower-live-image-card` for the live map.
  - Bundled dashboard (`dashboards/mower/`) swaps the live-map card type;
    deploy per `reference_ha_dashboard_deploy` (SCP, browser-reload).

> The directional icon art: reuse the existing `_mower_icon` PNG asset as an
> SVG `<image>` inside the `#mower` `<g>`, or inline a small SVG path. Either
> way the up-pointing-source assumption in §5 must match the asset; the corpus
> test catches a mismatch.

---

## 8. Testing

- **Corpus-backed icon-direction test (the regression guard that was
  missing).** Using `probe_log_*.jsonl`: for every consecutive 33-byte pair with
  a straight move > 0.5 m, assert the icon rotation `A` computed from the byte
  heading points within tolerance of the **screen-space** motion direction
  `θ_screen` derived from the two projected points. Tolerance: median < 10°,
  p90 < 45° (the pivot tail is expected). This pins the §5 formula empirically
  and fails loudly if the flip convention regresses.
- **`background_mode` projection unit tests:** table of
  `(mow_session, current_activity, action_mode) → BackgroundMode`. Explicitly
  assert REPOSITIONING/CRUISING_TO_POINT/RETURNING → GREEN (the #1 fix) and
  IDLE@dock + ALL_AREAS → STRIPES.
- **Publisher tests:** `point_seq` monotonicity; `latest_point` carries byte
  heading when present, `null` for beacon; `track_snapshot` only on
  begin/cold-start.
- **Client (lightweight):** a node/jsdom unit test for `_projectPoint` round-
  trip and `iconRotation` against a few hand-checked vectors; interpolation
  clamp bounds.
- **Manual / live:** one to-point run — confirm (a) stripes clear at undock
  (~immediately, not +41 s), (b) icon glides continuously, (c) icon points along
  travel. Capture the new render log line.

## 9. Observability

One structured DEBUG line on each base render and each publish, e.g.:

```
[MAP] base render: bg=GREEN_DARK map=2 md5=… reason=activity:REPOSITIONING
[MAP] publish: seq=137 pt=(3.21,-1.04) hdg=88.2(byte) bg=GREEN_DARK Δt=5.0s
```

`hdg=…(byte|vector|stale)` makes the heading source visible — the single most
useful datum the old system never logged.

---

## 10. Rollout, risks, migration

- **Single-user deployment** (per `feedback_no_migration_overengineering`): no
  registry migration, no back-compat shims. Reinstall/reload is fine. The old
  `dreame-mower-live-image-card` is removed from the bundled dashboard; if a
  user-managed Lovelace resource references it, document the swap.
- **Recorder exclusion** must land with the streamed attributes or the DB grows;
  verify via `recorder` config / entity glob.
- **Risk: attribute push frequency.** HA re-sends all attributes per state
  change. Mitigated by streaming one `latest_point` (not the whole track) +
  recorder exclusion. If still heavy, move the stream to a dedicated
  `sensor`/event channel — noted, not built.
- **Risk: card not registered on YAML dashboards** (the prior live-image-card
  pain, `project_live_image_card_render_bug`): the new card must self-register
  via `customElements.define` + a Lovelace resource entry, **not** rely on
  `add_extra_js_url` (which never registered at render time on YAML-mode
  dashboards).
- **Fact discipline:** adding the §4.3 camera attributes and removing
  `calibration_points` touches an entity definition → update
  `entity-inventory.yaml` per CLAUDE.md when implementing. The byte-heading
  median-2.5° corpus result refines the existing 13°-median note in
  `protocol/telemetry.py` / `inventory.yaml` → record a `verified` verification
  citing `analyze_move_corpus.py` over the 9 probe logs.

---

## 11. Resolved decisions

1. **Trail length on long mows — keep the full polyline.** SVG handles
   thousands of points fine. If users ever appear with lawns large enough to
   cause client jank, cap/simplify (e.g. Douglas–Peucker) then; not built now.
2. **Icon art — reuse the existing live-mow `_mower_icon` raster** as an SVG
   `<image>` inside the `#mower` `<g>`. It is an exact top-down copy of the
   mower, so front/back read unambiguously. The §5 up-pointing-source
   assumption is matched to this asset and pinned by the corpus test.
3. **Base-only — no fully-composited live PNG is served anywhere.** Nothing
   else consumes it; users who need the overlays can screenshot the rendered
   card. `render_main_view`'s composited output and all icon/trail PIL paths are
   deleted outright, not retained "just in case."
4. **`background_mode` active-activity set** (§4.1): `FAST_MAPPING` and
   `DRIVING_BLADES_UP` are treated as **GREEN** (active) — the mower is out and
   moving, so the idle stripe preview would reproduce the #1 bug. Trivially
   movable to idle-preview later if a state should read as "not a session."

## 12. Scope / phasing

Delivered as **one plan**. (For sequencing within that plan, the server
decoupling — `background_mode` projection + base-only render + publisher — is a
natural first tranche that independently fixes #1 and can be validated before
the client card lands; the planner may order tasks that way, but it ships as a
single effort.)
