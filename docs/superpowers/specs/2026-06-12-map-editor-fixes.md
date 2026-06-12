# Map-editor card fixes (a9) — interaction correctness

Fixes the live-tested defects in the v1.0.25a8 map-editor card. Root causes were
established by tracing card → service → device → render against the real g2408
(see the session debugging). **Create/Save/Delete already reach the device and
round-trip correctly** (a 4-corner no-go was created + read back as 4 corners +
deleted cleanly). The bugs are in the card's *manipulation + rendering model*,
plus one latent id-collision.

## Confirmed facts (ground truth)
- The device **preserves point counts**: a 4-corner no-go stays 4 corners on
  read-back. So a 2-point no-go is genuinely a 2-point shape (a wall/line), not a
  reduced rectangle. The base-PNG renderer already skips <3-point exclusions
  (`map_render/base_map.py:266`), so 2-point no-gos only show in the card overlay.
- **No-go / ignore share an id space** (both observed as `id 101`). The card keys
  selection + overlay rendering by `id` alone → collision.
- **Curved mow-shapes are a 2-point wire form, and the 2 points encode rotation**
  (user, who has the app): "there is no rotate-angle element; if the two points
  are not on the same vertical/horizontal line then the shape is rotated."
  → The 2 points are **one edge of an oriented bounding box**: edge direction =
  box orientation (axis-aligned edge ⇒ unrotated; off-axis edge ⇒ rotated), and
  the shape scales **uniformly** (aspect-locked) with the edge. This is a
  fundamentally different model than the current axis-aligned 2-corner bbox — and
  is why both resize (distorts) and rotate (flips v↔h) misbehave today.
- Square mow-shape (type 9) is a **4-corner** wire form (rotated square = 4
  rotated corners). No-go rectangle is a 4-corner **polygon** (type 2). Both are
  corner-based, free-rectangular resize, and rotatable.

## Two manipulation models

**A. Corner model** — shapes stored as their actual corner points; rotatable;
the wire sends the corners directly.
- no-go polygon, ignore polygon  → N corners, uniform resize (scale about centroid)
- no-go rectangle, square mow     → 4 corners, **free-rectangular** resize (drag a
  corner along the rect's own local axes; opposite corner anchored; stays a
  parallelogram/rectangle even when rotated)
- no-go line                      → 2 endpoints, per-endpoint drag
All rotate via `rotatePointsAroundCentroid`.

**B. Oriented-edge model** — curved mow-shapes (circle/heart/triangle/teardrop/
mushroom/cloud/rainbow). Stored as a 2-point edge `[p0, p1]`.
- The oriented bounding box = edge `p0→p1` + perpendicular extent (assume square:
  `W = |p0→p1|`, perpendicular to the **left** of `p0→p1`). The firmware draws
  the actual silhouette inside that oriented box; the card draws the oriented box
  as the WYSIWYG proxy.
- **Resize** = uniform: drag a corner → scale the edge length about the box
  centre, keep orientation, keep square aspect.
- **Rotate** = rotate `[p0, p1]` about the box centre.
- **Move** = translate both points.
- Wire = `[p0, p1]` (2 points). NOTE: the square-aspect (perpendicular = edge
  length) assumption affects only the rendered proxy's proportions; position +
  rotation are exact regardless. Flagged for in-app verification.

**C. Circle (no-go)** — center + rim; rim handle; NO rotate (rotation-invariant).

## Geometry module additions (`www/_dreame-map-edit-geom.js`, node-tested)
Add pure, exported, node-harness-covered functions:
- `orientedEdgeBox(p0, p1) -> [c0,c1,c2,c3]` — 4 corners of the square box whose
  bottom edge is `p0→p1`, extending perpendicular-left by `|p0→p1|`. Order
  `[p0, p1, p1+n, p0+n]` with `n = rot90ccw(p1-p0)` (i.e. `n=(-(dy),dx)`
  normalised? NO — use `n = (-(p1.y-p0.y), p1.x-p0.x)` un-normalised so |n|=|edge|
  ⇒ square).
- `edgeBoxCenter(p0, p1) -> [cx,cy]` — centre of that box = `midpoint(p0,p1) + n/2`.
- `resizeOrientedEdge(p0, p1, handleIdx, newPos) -> [np0, np1]` — uniform scale of
  the edge about the box centre by the ratio of `|newPos-center| / |corner[handleIdx]-center|`,
  preserving orientation. (handleIdx indexes the 4 `orientedEdgeBox` corners.)
- `rotateEdgeAboutCenter(p0, p1, deg) -> [np0, np1]` — rotate both points about
  `edgeBoxCenter` by `deg`.
- `resizeRectCorner(corners, handleIdx, newPos) -> [4 corners]` — free-rect resize
  of a (possibly rotated) 4-corner rectangle: the dragged corner moves to `newPos`
  projected onto the rect's local axes from the anchored opposite corner; the two
  adjacent corners follow so it stays a rectangle. (Local axes = the rect's two
  edge directions at the opposite corner.)
Keep existing exports. Every new function gets node-harness assertions
(`tests/www/geom_harness.mjs`): axis-aligned edge ⇒ axis-aligned box; off-axis
edge ⇒ rotated box (corner not axis-aligned); resize preserves aspect; rotate
preserves edge length; rect-corner resize keeps right angles.

## Card changes (`www/dreame-map-editor-card.js`)
- Tool catalogue: tag each tool with a `model`: `"corners"` (nogo rect/poly, ignore
  poly, square mow, with a `resize:"rect"|"uniform"` sub-mode), `"edge"` (curved
  mow), `"line"`, `"circle"`.
- `_makeDraft`: corner shapes store 4/N corners (rect/square = `rectCorners`);
  edge shapes store a 2-point edge (default a small axis-aligned edge); circle
  unchanged.
- `_applyResize`: dispatch by model — `resizeRectCorner` (rect/square),
  `resizeUniform` (free polygon/ignore), `resizeOrientedEdge` (curved),
  circle rim unchanged.
- Rotate: `rotatePointsAroundCentroid` for corner/line models;
  `rotateEdgeAboutCenter` for the edge model; **hide the rotate handle for circle**
  (rotation-invariant).
- Render draft: corner shapes draw their polygon from the stored corners (NOT
  `rectCorners(pts[0],pts[1])` — that forced axis-aligned and broke rotation);
  edge shapes draw `orientedEdgeBox`; handles placed at the model's corners.
- `_meterState`/`shapeToPoints`: corner shapes send their corners; edge shapes
  send `[p0,p1]` (2 points) — extend `shapeToPoints` mow branch so square→4
  corners (rectCorners over the 4 stored corners' bbox-in-local-frame… actually
  square stores 4 corners already → send them) and curved→the 2 edge points.
  Net: the wire for a curved shape = its 2 edge points; for square/rect = its 4
  corners.
- **id-collision**: key selection + the "skip selected" overlay test by a composite
  `${kind}:${id}` (a no-go and an ignore with the same numeric id are distinct).
  `_objs.find` must match BOTH id and kind.
- **Edit feedback**: while a Create/Save/Delete service call is awaiting, show a
  "writing…" state on the submit/delete button (disabled + label), restore on
  completion. On success keep clearing the draft. (edit_map already calls
  `_refresh_cloud_state`, so the overlay updates within a poll; the missing piece
  is just user feedback during the multi-second device transaction.)

## Out of scope (note in knowledge-gaps, do NOT build now)
- Distinguishing an existing 2-point no-go *wall* (type 1) from other 2-point
  forms for editing — needs the decoder to surface the real `shapeType`
  (currently `_editable_objects_from_map` hardcodes type 2). Existing walls render
  correctly as lines; editing them as walls is a follow-up.
- The exact firmware perpendicular-width convention for curved shapes (assumed
  square). Verify in-app; refine if proportions are off.

## Tests
- Node geom harness: new functions (see above). `node --check` both JS files.
- pytest: unchanged (no Python changes) — full suite must stay green.
- Manual (post-deploy, user): curved shapes resize without distortion + rotate;
  square/rect rotate as true rotated rectangles; no-go & ignore with same id are
  independently selectable; Create shows feedback then the shape appears.

## Release
`release.sh` owns the bump (a8 → a9). Merge to main, push, release, then SCP the
(unchanged) dashboard only if the view changed — it didn't, so no dashboard
redeploy needed unless the resource list changes (it doesn't).
