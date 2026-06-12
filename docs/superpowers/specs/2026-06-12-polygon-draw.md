# Click-to-add-vertices polygon draw (map-editor card)

Card-only feature. The wire already accepts N-point polygons (a no-go polygon is
`o=215 type 2` with the corner list; the device closes it implicitly — confirmed
by app captures). No backend change.

Replaces the current No-go ⬠ / Ignore ⬠ tools (which just drop a fixed 4-corner
square — indistinguishable from the rectangle tool) with a real freeform draw.

## UX (decided with the user)
- **Draw**: pick No-go ⬠ or Ignore ⬠ → draw mode. Each map click **adds a
  vertex**. In-progress shape renders as an OPEN polyline through the points + a
  vertex dot on each (first vertex highlighted) + a **dashed preview line from the
  last point back to the first** (the closing edge). No resize/rotate/bbox/delete
  handles while drawing.
- **Finish = a "Close" button** (the only close gesture — NOT click-first-vertex,
  NOT double-click). Enabled only when ≥3 points placed. Clicking it closes the
  polygon → `drawing=false` → it becomes a normal editable draft (per-vertex drag
  handles + move + rotate appear).
- **Undo point** button while drawing — removes the last placed vertex; if it
  empties, the draft clears.
- **Create/Save is BLOCKED while drawing.** Clicking Create while `drawing` does
  NOT submit; it shows an inline error: `<3 pts → "Place at least 3 points"`;
  `≥3 pts (not closed) → "Close the shape first"`. Once closed, Create works.
- **Edit** of an existing polygon is UNCHANGED and never gated: move the shape
  (body drag) + drag individual vertices; NO adding/removing points; Save submits
  directly (an existing polygon is already valid + closed).
- Only the two polygon tools change. Rectangle / circle / line / curved-mow tools
  keep their drop-and-drag behavior (immediately valid, no draw mode).

## Implementation (all in `www/dreame-map-editor-card.js`)
- **TOOLS**: add `draw: true` to `nogo_poly` and `ignore_poly`. Keep
  `model:"corners", resize:"vertex"`.
- **Draft model**: add a `drawing: boolean` field. Set `true` only when starting a
  NEW polygon via a draw-tool; `_draftFromObject` (edit) leaves it falsy.
- **`_onPointerDown`** — handle draw mode with TOP priority:
  1. If `this._draft && this._draft.drawing`: a click **appends** `pos` to
     `draft.pts`; re-render; return. (No drag, no handle logic.)
  2. Else existing: handle-controls on a (non-drawing) draft → overlay-select →
     tool-armed → body-move.
  3. In the tool-armed branch: if `tool.draw`, start a drawing draft
     `{category, shape, model:"corners", resize:"vertex", drawing:true,
       kind:(category==="ignore"?"ignore":"nogo"), objectId:null, pts:[pos]}`,
     re-render, return (NO move-drag). Else existing `_makeDraft` drop + move.
- **`_renderDraft`** — when `d.drawing`:
  - `<polyline>` through `d.pts` (open; stroke like the draft, fill none).
  - dashed `<line>` from `d.pts[last]` → `d.pts[0]` when `d.pts.length >= 2`.
  - a vertex `<circle>` at each point; the FIRST larger + distinct colour (close
    target hint).
  - NO bbox, NO resize/rotate/delete handles. Return after this.
  Else: the existing closed-polygon render (handles + bbox + rotate + del).
- **Action buttons** (`_buildActionButtons` + `_syncActionButtons`):
  - Add `closeBtn` ("Close") — shown only when `draft.drawing`; enabled when
    `pts.length >= 3`. Click → if ≥3: `draft.drawing=false`, clear msg, re-render;
    else set msg "Place at least 3 points".
  - Add `undoBtn` ("Undo point") — shown only when `draft.drawing`; enabled when
    `pts.length >= 1`. Click → `pts.pop()`; if empty → clear draft; re-render.
  - Hide closeBtn/undoBtn when not drawing; show submit/delete as today.
  - Submit (`_onSubmit`): at the top, `if (d.drawing) { set msg per above; return; }`.
- **Inline message**: add a `<span id="msg">` in the toolbar + `_setMsg(text)`
  (clear on tool-select, successful submit, close, and undo-to-empty).
- **`_selectTool`** clears draft + msg (existing clears draft).

## Tests
- `node --check` the card; `node tests/www/geom_harness.mjs` still OK (no geom
  change — pure point append; nothing new to node-test, but run it).
- Manual (post-deploy): draw a 5-point no-go, Undo a point, Close, drag a vertex,
  Create → appears; Create while drawing shows the error; edit an existing polygon
  (drag vertices/move, Save) still works and isn't gated.

## Release
JS-only → `release.sh` bump (a3 → a4); SCP the card to the host (no restart);
hard-refresh. No dashboard/resource change.
