// Interactive map-editor card: base <image> in an SVG viewBox plus draggable
// SVG overlays for the map's no-go / ignore / mow-shape / spot / maintenance
// edit objects.
//
// Reads camera.dreame_a2_mower_map .attributes:
//   map_projection, editor_base_url (clean no-exclusions bg; falls back to
//   entity_picture), editable_objects, map_id, available_map_ids
// and writes via the dreame_a2_mower create_no_go_zone / create_ignore_obstacle
// / create_mow_shape / create_spot / create_maintenance_point /
// create_patrol_point / delete_map_object services.
//
// Patrol points (cruisePoints, o=223) ARE editable here (wire-confirmed
// app-mitm 2026-06-15): a single oriented point, DISTINCT opcode from the
// maintenance point (o=224), delete category 2 (not 3).
//
// ALL numeric geometry (projection, rect/bbox corners, rotate, resize, circle,
// wire-shape mapping) lives in ./_dreame-map-edit-geom.js — this card is DOM +
// pointer-event plumbing only. If you find yourself writing trig or scaling
// math here, it belongs in that (node-tested) module instead.
//
// Load as a Lovelace resource (type: module):
//   url: /dreame_a2_mower/dreame-map-editor-card.js
import {
  pixelToMeters,
  metersToPixel,
  rectCorners,
  rotatePointsAroundCentroid,
  pointerAngleAboutCentroid,
  resizeRectCorner,
  orientedEdgeBox,
  resizeOrientedEdge,
  rotateEdgeAboutCenter,
  circleFromCenterEdge,
  patrolConfigServiceData,
} from "./_dreame-map-edit-geom.js";

// ----- read-only overlay rendering (Task 5) -------------------------------
// Manual post-merge verification: the overlays must sit EXACTLY over the
// no-go / ignore areas baked into the served PNG. If they're offset, the bug
// is in the Task-1 edit frame or in editable_objects.points_m — NOT in this
// card. Do NOT fudge a correction factor here.

const NOGO_STROKE = "rgb(220,60,60)";
const NOGO_FILL = "rgba(220,60,60,0.18)";
const IGNORE_STROKE = "rgb(60,170,90)";
const IGNORE_FILL = "rgba(60,170,90,0.18)";

// Per-category accent RGB — each toolbar button is tinted with a
// semi-transparent version of the colour of the SHAPE it draws (so the
// "No-go" buttons read light-red because no-go zones render red, etc.).
// Values mirror the overlay CSS below: nogo->.obj-nogo, ignore->.obj-ignore,
// mow->.obj-decorative, spot->.obj-spot, maintenance->.obj-maint,
// patrol->.obj-patrol. Used as the `--btn` custom property per button.
const CAT_RGB = {
  nogo: "220,60,60",
  ignore: "60,170,90",
  mow: "177,0,0",
  spot: "0,150,200",
  maintenance: "180,120,0",
  patrol: "0,140,140",
};

const HANDLE_R = 7;       // resize-handle radius (px, viewBox units)
const ROTATE_OFF = 36;    // rotate-handle offset above the bbox top (px)
const DEL_OFF = 18;       // delete-X offset (px)
const DEFAULT_PX = 60;    // default half-extent of a freshly dropped shape

// Toolbar tool catalogue. `model` selects the manipulation model (Task 1):
//   corners -> shape stored as actual corner points; rotatePointsAroundCentroid.
//              `resize` sub-mode: "rect" (free-aspect 4-corner) | "uniform" (N-corner scale).
//   edge    -> curved mow shapes; stored as a 2-point edge [p0,p1]; rendered as
//              orientedEdgeBox; resizeOrientedEdge (aspect-locked) + rotateEdgeAboutCenter.
//   line    -> 2 endpoints (per-endpoint drag); rotate via rotatePointsAroundCentroid.
//   circle  -> center + rim point (single rim handle); NO rotate (rotation-invariant).
// `save` is { category, shape } sent to the create_* service at save time (Task 7).
const TOOLS = [
  { id: "nogo_rect", label: "No-go ▭", model: "corners", resize: "rect", save: { category: "nogo", shape: "polygon" } },
  { id: "nogo_circle", label: "No-go ◯", model: "circle", save: { category: "nogo", shape: "circle" } },
  { id: "nogo_line", label: "No-go ╱", model: "line", save: { category: "nogo", shape: "line" } },
  { id: "nogo_poly", label: "No-go ⬠", model: "corners", resize: "vertex", draw: true, save: { category: "nogo", shape: "polygon" } },
  { id: "ignore_poly", label: "Ignore ⬠", model: "corners", resize: "vertex", draw: true, save: { category: "ignore", shape: "polygon" } },
  { id: "mow_square", label: "Mow ▢", model: "corners", resize: "rect", save: { category: "mow", shape: "square" } },
  { id: "mow_circle", label: "Mow ◯", model: "edge", save: { category: "mow", shape: "circle" } },
  { id: "mow_heart", label: "Mow ♥", model: "edge", save: { category: "mow", shape: "heart" } },
  { id: "mow_triangle", label: "Mow △", model: "edge", save: { category: "mow", shape: "triangle" } },
  { id: "mow_teardrop", label: "Mow Teardrop", model: "edge", save: { category: "mow", shape: "teardrop" } },
  { id: "mow_mushroom", label: "Mow Mushroom", model: "edge", save: { category: "mow", shape: "mushroom" } },
  { id: "mow_cloud", label: "Mow Cloud", model: "edge", save: { category: "mow", shape: "cloud" } },
  { id: "mow_rainbow", label: "Mow Rainbow", model: "edge", save: { category: "mow", shape: "rainbow" } },
  // Spot = own opcode (o=214), same 4-corner rect geometry as a no-go rect.
  { id: "spot_rect", label: "Spot ▭", model: "corners", resize: "rect", save: { category: "spot", shape: "rect" } },
  // Maintenance point = single-point model (o=224): click to place, drag to
  // move (edit-in-place), X to delete. No resize/rotate/vertex.
  { id: "maint_point", label: "Maint ⊕", model: "point", save: { category: "maintenance", shape: "point" } },
  // Patrol / cruise point = single-point model (o=223): DISTINCT opcode from
  // maintenance, delete category 2. Same point model (place / move / delete).
  { id: "patrol_point", label: "Patrol ⊕", model: "point", save: { category: "patrol", shape: "point" } },
];

class DreameMapEditorCard extends HTMLElement {
  setConfig(cfg) {
    if (!cfg || !cfg.entity) throw new Error("entity is required");
    this._cfg = cfg;
    this._objKey = null; // identity of the last-rendered editable_objects set
    // Optimistic edit state (HA's cloud-sourced editable_objects lags the
    // device by minutes after an edit, so without this a Save/Delete snaps the
    // overlay back to the stale pre-edit shape). `_overrides` maps
    // `${kind}:${id}` -> {points_m,radius} (edited) or null (deleted);
    // `_provisional` holds just-created shapes that have no real id yet. Both
    // are cleared whenever genuinely-new server data arrives (_syncObjects).
    this._overrides = {};
    this._provisional = [];
    this._tool = null;    // selected toolbar tool (TOOLS entry) or null
    this._draft = null;   // in-edit shape (see _makeDraft) or null
    this._drag = null;    // active pointer drag descriptor or null
    this._editMapId = null; // toolbar map-id selector value
  }

  set hass(hass) {
    this._hass = hass;
    const ent = hass.states[this._cfg.entity];
    if (!ent || !ent.attributes) return;
    const a = ent.attributes;
    // The editor uses a no-exclusions background (editor_base_url) so the
    // no-go/ignore zones render ONLY as the editable overlays below — the
    // normal entity_picture bakes them in, which double-draws/ghosts while a
    // device edit is still propagating to the cloud. Fall back to
    // entity_picture when the clean URL isn't published (backward compat).
    const baseHref = a.editor_base_url || a.entity_picture;
    if (!a.map_projection || !baseHref) return;
    this._proj = a.map_projection;
    this._ensureSvg(a);
    const img = this.shadowRoot.getElementById("base");
    if (img && img.getAttribute("href") !== baseHref) {
      img.setAttribute("href", baseHref);
    }
    if (this._editMapId == null && a.map_id != null) this._editMapId = a.map_id;
    this._syncMapIds(a);
    this._syncObjects(a);
  }

  // ----- DOM skeleton ------------------------------------------------------
  _ensureSvg(a) {
    if (this.shadowRoot && this.shadowRoot.getElementById("svg")) return;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const p = a.map_projection;
    this.shadowRoot.innerHTML =
      `<style>:host{display:block}` +
      `.bar{display:flex;flex-wrap:wrap;gap:4px;align-items:center;padding:6px 4px}` +
      // Each button is tinted with its shape's colour via the per-button
      // `--btn` custom property (set in _buildToolbar); fallback grey for any
      // button without a known category. Resting = faint tint + coloured
      // border; selected (.on) = strong fill of the same colour + white text.
      `.bar button{font:12px/1 system-ui,sans-serif;padding:4px 8px;border-radius:6px;` +
      `border:1px solid rgba(var(--btn,120,120,120),.55);` +
      `background:rgba(var(--btn,120,120,120),.16);cursor:pointer}` +
      `.bar button.on{background:rgba(var(--btn,120,170,230),.92);` +
      `border-color:rgba(var(--btn,120,170,230),.92);color:#fff}` +
      `.bar select{font:12px/1 system-ui,sans-serif;padding:3px 6px;border-radius:6px}` +
      `.bar .sp{flex:1}` +
      `.bar #msg{font:12px/1 system-ui,sans-serif;color:#d32f2f;padding:0 4px}` +
      `#patrol-panel{display:none;align-items:center;gap:8px;flex-wrap:wrap;` +
      `padding:6px 4px;border-top:1px solid rgba(0,140,140,.25);` +
      `background:rgba(0,140,140,.06);font:12px/1 system-ui,sans-serif}` +
      `#patrol-panel.visible{display:flex}` +
      `#patrol-panel label{color:#555;margin-right:2px}` +
      `#patrol-panel .pcyc{display:flex;gap:3px}` +
      `#patrol-panel .pcyc button{font:12px/1 system-ui,sans-serif;padding:3px 8px;` +
      `border-radius:6px;border:1px solid rgba(0,140,140,.55);` +
      `background:rgba(0,140,140,.16);cursor:pointer}` +
      `#patrol-panel .pcyc button.on{background:rgba(0,140,140,.85);` +
      `border-color:rgba(0,140,140,.85);color:#fff}` +
      `.wrap{position:relative}` +
      `svg{width:100%;height:auto;display:block;touch-action:none}` +
      `.obj{cursor:pointer}` +
      `.obj-nogo{stroke:${NOGO_STROKE};fill:${NOGO_FILL};stroke-width:2}` +
      `.obj-ignore{stroke:${IGNORE_STROKE};fill:${IGNORE_FILL};stroke-width:2}` +
      `.obj-decorative{fill:rgba(177,0,0,0.06);stroke:rgba(177,0,0,0.5);stroke-width:1.5;stroke-dasharray:5 4}` +
      `.obj-spot{fill:rgba(0,150,200,0.12);stroke:rgba(0,150,200,0.8);stroke-width:2}` +
      // NON-selected point markers — muted/desaturated so the SELECTED draft
      // marker (.marker, bright orange) is visually distinct (selection state).
      // Maintenance = muted amber, patrol = muted teal (distinct kinds).
      `.obj-maint circle{fill:rgba(180,120,0,0.45);stroke:#fff;stroke-width:1.5}` +
      `.obj-maint line{stroke:#fff;stroke-width:1.5;pointer-events:none}` +
      `.obj-patrol circle{fill:rgba(0,140,140,0.45);stroke:#fff;stroke-width:1.5}` +
      `.obj-patrol line{stroke:#fff;stroke-width:1.5;pointer-events:none}` +
      // SELECTED draft marker — bright (full-saturation), so exactly the one
      // selected point reads as active. Patrol selection uses a teal accent.
      `.marker circle{fill:rgba(255,160,0,0.95);stroke:#fff;stroke-width:2}` +
      `.marker line{stroke:#fff;stroke-width:1.5;pointer-events:none}` +
      `.marker-patrol circle{fill:rgba(0,200,200,0.95);stroke:#fff;stroke-width:2}` +
      `.marker-patrol line{stroke:#fff;stroke-width:1.5;pointer-events:none}` +
      `.draft{stroke:#1565c0;stroke-width:2;fill:rgba(21,101,192,0.15)}` +
      `.bbox{stroke:#1565c0;stroke-width:1;stroke-dasharray:4 3;fill:none;pointer-events:none}` +
      `.drawline{stroke:#1565c0;stroke-width:2;fill:none;pointer-events:none}` +
      `.closehint{stroke:#1565c0;stroke-width:1.5;stroke-dasharray:4 3;fill:none;pointer-events:none}` +
      `.vtx{fill:#1565c0;stroke:#fff;stroke-width:1;pointer-events:none}` +
      `.vtx0{fill:#ff9800;stroke:#fff;stroke-width:1.5;pointer-events:none}` +
      `.handle{fill:#fff;stroke:#1565c0;stroke-width:2;cursor:pointer}` +
      `.rot{fill:#1565c0;cursor:grab}` +
      `.del{fill:#d32f2f;cursor:pointer}` +
      `.del text{fill:#fff}` +
      `</style>` +
      `<div class="bar" id="bar"></div>` +
      `<div class="wrap">` +
      `<svg id="svg" viewBox="0 0 ${p.width_px} ${p.height_px}">` +
      `<image id="base" href="${a.editor_base_url || a.entity_picture}" x="0" y="0" ` +
      `width="${p.width_px}" height="${p.height_px}"/>` +
      `<g id="objects"></g>` +
      `<g id="draft"></g>` +
      `</svg>` +
      `</div>` +
      `<div id="patrol-panel"></div>`;
    this._buildToolbar();
    const svg = this.shadowRoot.getElementById("svg");
    svg.addEventListener("pointerdown", (e) => this._onPointerDown(e));
    svg.addEventListener("pointermove", (e) => this._onPointerMove(e));
    svg.addEventListener("pointerup", (e) => this._onPointerUp(e));
    svg.addEventListener("pointercancel", (e) => this._onPointerUp(e));
  }

  _buildToolbar() {
    const bar = this.shadowRoot.getElementById("bar");
    if (!bar) return;
    bar.innerHTML = "";
    for (const t of TOOLS) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = t.label;
      b.dataset.tool = t.id;
      // Tint the button with its shape's colour (see CAT_RGB).
      b.style.setProperty("--btn", CAT_RGB[t.save && t.save.category] || "120,120,120");
      b.addEventListener("click", () => this._selectTool(t.id));
      bar.appendChild(b);
    }
    const sp = document.createElement("span");
    sp.className = "sp";
    bar.appendChild(sp);
    const sel = document.createElement("select");
    sel.id = "mapSel";
    sel.title = "Map";
    sel.addEventListener("change", () => {
      this._editMapId = Number(sel.value);
    });
    bar.appendChild(sel);
    const msg = document.createElement("span");
    msg.id = "msg";
    bar.appendChild(msg);
    this._buildActionButtons(bar);
  }

  // Create / Save / Delete actions (Task 7). One submit button (label flips
  // Create<->Save depending on whether the draft is a new shape or an edit of
  // an existing object) plus a Delete button for existing objects.
  _buildActionButtons(bar) {
    const submit = document.createElement("button");
    submit.type = "button";
    submit.id = "submitBtn";
    submit.textContent = "Create";
    submit.addEventListener("click", () => this._onSubmit());
    bar.appendChild(submit);
    const del = document.createElement("button");
    del.type = "button";
    del.id = "deleteBtn";
    del.textContent = "Delete";
    del.addEventListener("click", () => {
      if (this._draft) this._onDeleteHandle();
    });
    bar.appendChild(del);
    // Draw-mode actions (polygon draw): shown only while drawing.
    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.id = "closeBtn";
    closeBtn.textContent = "Close";
    closeBtn.addEventListener("click", () => this._onClosePolygon());
    bar.appendChild(closeBtn);
    const undoBtn = document.createElement("button");
    undoBtn.type = "button";
    undoBtn.id = "undoBtn";
    undoBtn.textContent = "Undo point";
    undoBtn.addEventListener("click", () => this._onUndoPoint());
    bar.appendChild(undoBtn);
  }

  // Refresh the submit/delete button labels + enabled state from the draft.
  _syncActionButtons() {
    const submit = this.shadowRoot && this.shadowRoot.getElementById("submitBtn");
    const del = this.shadowRoot && this.shadowRoot.getElementById("deleteBtn");
    const closeBtn = this.shadowRoot && this.shadowRoot.getElementById("closeBtn");
    const undoBtn = this.shadowRoot && this.shadowRoot.getElementById("undoBtn");
    const drawing = !!(this._draft && this._draft.drawing);
    const editing = !!(this._draft && this._draft.objectId != null);
    if (submit) {
      // Stays visible while drawing (Create is gated in _onSubmit), so the user
      // sees it but the click shows an inline message instead of submitting.
      submit.disabled = !this._draft;
      // mow-shapes are create-only (no edit-in-place path).
      submit.textContent = editing ? "Save" : "Create";
    }
    // Delete only applies to a closed/existing draft — hide it while drawing.
    if (del) {
      del.style.display = drawing ? "none" : "";
      del.disabled = !editing;
    }
    // Close / Undo only exist while drawing a fresh polygon.
    const pts = drawing ? (this._draft.pts || []) : [];
    if (closeBtn) {
      closeBtn.style.display = drawing ? "" : "none";
      closeBtn.disabled = pts.length < 3;
    }
    if (undoBtn) {
      undoBtn.style.display = drawing ? "" : "none";
      undoBtn.disabled = pts.length < 1;
    }
  }

  // Toggle the submit/delete buttons into a disabled "writing…" state while a
  // Create/Save/Delete service call is in flight; restore labels on completion
  // (both success and the catch path) via _syncActionButtons.
  _setBusy(busy) {
    const submit = this.shadowRoot && this.shadowRoot.getElementById("submitBtn");
    const del = this.shadowRoot && this.shadowRoot.getElementById("deleteBtn");
    if (busy) {
      if (submit) { submit.disabled = true; submit.textContent = "writing…"; }
      if (del) { del.disabled = true; del.textContent = "writing…"; }
    } else {
      if (del) del.textContent = "Delete";
      this._syncActionButtons();
    }
  }

  _syncMapIds(a) {
    const sel = this.shadowRoot.getElementById("mapSel");
    if (!sel) return;
    const ids = Array.isArray(a.available_map_ids) && a.available_map_ids.length
      ? a.available_map_ids
      : (a.map_id != null ? [a.map_id] : []);
    const key = ids.join(",");
    if (sel.dataset.key !== key) {
      sel.dataset.key = key;
      sel.innerHTML = ids
        .map((id) => `<option value="${id}">Map ${id}</option>`)
        .join("");
    }
    if (this._editMapId != null) sel.value = String(this._editMapId);
  }

  _selectTool(id) {
    this._tool = this._tool && this._tool.id === id ? null : TOOLS.find((t) => t.id === id);
    this._draft = null;
    this._setMsg("");
    for (const b of this.shadowRoot.querySelectorAll(".bar button[data-tool]")) {
      b.classList.toggle("on", !!this._tool && b.dataset.tool === id);
    }
    this._renderDraft();
  }

  // Inline message area (#msg) — used to surface the draw-mode submit gate.
  _setMsg(text) {
    const m = this.shadowRoot && this.shadowRoot.getElementById("msg");
    if (m) m.textContent = text || "";
  }

  // ----- existing-object overlays (unselected) ----------------------------
  _syncObjects(a) {
    const objs = Array.isArray(a.editable_objects) ? a.editable_objects : [];
    this._objs = objs;
    const key = JSON.stringify(
      objs.map((o) => [o.id, o.op, o.type, o.kind, o.shape_type, o.points_m, o.point_m, o.radius])
    );
    if (key === this._objKey) return;
    this._objKey = key;
    // Genuinely-new server data is authoritative — drop optimistic state.
    this._overrides = {};
    this._provisional = [];
    this._renderObjects(objs);
  }

  // Merge server objects with optimistic overrides + provisional creates.
  _effectiveObjects(objs) {
    const eff = [];
    for (const o of objs) {
      const k = `${o.kind}:${o.id}`;
      if (Object.prototype.hasOwnProperty.call(this._overrides, k)) {
        const ov = this._overrides[k];
        if (ov === null) continue; // optimistically deleted
        // cycles/auto_capture carry from the base object — a geometry override
        // never changes them (they're set via set_patrol_point_config, not edit_map).
        eff.push({ id: o.id, kind: o.kind, shape_type: o.shape_type, points_m: ov.points_m, point_m: ov.point_m, radius: ov.radius || 0, cycles: o.cycles, auto_capture: o.auto_capture });
      } else {
        eff.push({ id: o.id, kind: o.kind, shape_type: o.shape_type, points_m: o.points_m, point_m: o.point_m, radius: o.radius, cycles: o.cycles, auto_capture: o.auto_capture });
      }
    }
    for (const p of this._provisional || []) eff.push(p); // created (no id)
    return eff;
  }

  _renderObjects(objs) {
    const g = this.shadowRoot.getElementById("objects");
    if (!g) return;
    // Skip the selected object (drawn as the draft). No-go & ignore share an id
    // space, so the skip test must match BOTH id AND kind (Task 9).
    const selId = this._draft && this._draft.objectId != null ? this._draft.objectId : null;
    const selKind = this._draft ? this._draft.kind : null;
    const parts = [];
    for (const o of this._effectiveObjects(objs)) {
      if (selId != null && o.id === selId && o.kind === selKind) continue;
      // Maintenance (o=224) / patrol (o=223) points are single-point objects —
      // draw a marker (circle + crosshair), NOT a polygon line. The click
      // target is the <g>. Patrol uses a distinct (teal) marker class.
      if ((o.kind === "maintenance" || o.kind === "patrol") && Array.isArray(o.point_m)) {
        const c = metersToPixel(o.point_m[0], o.point_m[1], this._proj);
        const cls = o.kind === "patrol" ? "obj obj-patrol" : "obj obj-maint";
        parts.push(this._markerSvg(c, cls, o.id, o.kind));
        continue;
      }
      const pts = Array.isArray(o.points_m) ? o.points_m : [];
      const pix = pts.map((m) => metersToPixel(m[0], m[1], this._proj));
      // Decorative mow-shapes (shape_type >= 9: heart/cloud/etc.) are already
      // drawn in the server-rendered editor background, pixel-identical to the
      // live map. The card must NOT draw a 2-point <polygon> over them (that's
      // the "phantom no-go line" bug) — draw ONLY a faint axis-aligned bbox
      // <rect> as the select/delete hit-area. Decorative shapes are
      // create+delete (no reshape-in-place), so the rect is purely a click
      // target; the visible shape comes from the background.
      if ((o.shape_type || 0) >= 9) {
        if (pix.length >= 2) {
          const bb = this._pixBbox(pix);
          parts.push(
            `<rect class="obj obj-decorative" x="${bb.x.toFixed(1)}" ` +
            `y="${bb.y.toFixed(1)}" width="${bb.w.toFixed(1)}" ` +
            `height="${bb.h.toFixed(1)}" data-id="${o.id}" data-kind="${o.kind}"/>`
          );
        }
        continue;
      }
      const cls =
        o.kind === "ignore" ? "obj obj-ignore"
        : o.kind === "spot" ? "obj obj-spot"
        : "obj obj-nogo";
      if (pix.length >= 2) {
        const d = pix.map((q) => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(" ");
        parts.push(`<polygon class="${cls}" points="${d}" data-id="${o.id}" data-kind="${o.kind}"/>`);
      } else if (pix.length === 1 && o.radius) {
        const c = pix[0];
        const rim = metersToPixel(o.points_m[0][0] + o.radius, o.points_m[0][1], this._proj);
        const rpx = circleFromCenterEdge(c, rim).radius;
        parts.push(
          `<circle class="${cls}" cx="${c[0].toFixed(1)}" cy="${c[1].toFixed(1)}" ` +
          `r="${rpx.toFixed(1)}" data-id="${o.id}" data-kind="${o.kind}"/>`
        );
      }
    }
    g.innerHTML = parts.join("");
  }

  // ----- draft model -------------------------------------------------------
  // pts are in PIXELS; geom helpers are frame-agnostic so live manipulation in
  // pixel space is fine. Conversion to meters happens only at save (Task 7).
  _makeDraft(tool, center) {
    const [cx, cy] = center;
    const d = DEFAULT_PX;
    const draft = {
      category: tool.save.category,
      shape: tool.save.shape,
      model: tool.model,
      resize: tool.resize || null,
      kind: null,
      objectId: null,
      pts: [],
      radius: 0,
    };
    if (tool.model === "corners") {
      // rect/square (resize "rect") and free polygon/ignore (resize "uniform")
      // both start as a 4-corner axis-aligned square the user reshapes.
      draft.pts = rectCorners([cx - d, cy - d], [cx + d, cy + d]);
    } else if (tool.model === "edge") {
      // a small axis-aligned edge => unrotated default oriented box.
      draft.pts = [[cx - d, cy], [cx + d, cy]];
    } else if (tool.model === "circle") {
      draft.pts = [[cx, cy], [cx + d, cy]]; // center, rim
      draft.radius = d;
    } else if (tool.model === "line") {
      draft.pts = [[cx - d, cy], [cx + d, cy]];
    } else if (tool.model === "point") {
      // single point (maintenance): no drag-to-size, just a placed marker.
      draft.pts = [[cx, cy]];
      draft.radius = 0;
    }
    return draft;
  }

  // Build a draft from an existing editable_object (for select / edit-in-place).
  // NOTE: decoded exclusions arrive as path polygons — `editable_objects`
  // carries no shape/radius for them (always type 2, radius 0), so the shape is
  // INFERRED from point count below. A no-go originally drawn as circle/line
  // therefore edits back as a `polygon` (geometry-preserving — the corners are
  // identical — but the shape label is lost). Re-typing on edit is expected,
  // not a bug; surfacing the original shape needs the decoder to expose it.
  _draftFromObject(o) {
    // Maintenance (o=224) / patrol (o=223) point: single-point draft.
    // Drag-to-move = edit-in-place. Patrol is a DISTINCT category (delete 2).
    if ((o.kind === "maintenance" || o.kind === "patrol") && Array.isArray(o.point_m)) {
      const c = metersToPixel(o.point_m[0], o.point_m[1], this._proj);
      const draft = {
        category: o.kind, // "maintenance" | "patrol"
        shape: "point",
        model: "point",
        resize: null,
        kind: o.kind,
        objectId: o.id,
        pts: [c],
        radius: 0,
      };
      // Carry patrol-specific config fields so the panel pre-fills correctly.
      if (o.kind === "patrol") {
        draft.cycles = o.cycles ?? 1;
        draft.auto_capture = !!o.auto_capture;
      }
      return draft;
    }
    const pix = (o.points_m || []).map((m) => metersToPixel(m[0], m[1], this._proj));
    // Spot (o=214): a 4-corner rect, reshaped like a no-go rect.
    if (o.kind === "spot") {
      return {
        category: "spot",
        shape: "rect",
        model: "corners",
        resize: "rect",
        kind: "spot",
        objectId: o.id,
        pts: pix,
        radius: 0,
      };
    }
    // Decorative mow-shapes (shape_type >= 9) are create+delete — there is no
    // reshape-in-place op. Build a DELETE-ONLY draft: no line/polygon model
    // inference, just the bbox corners for the selection outline + delete
    // handle. The shape itself stays drawn in the server-rendered background.
    if ((o.shape_type || 0) >= 9) {
      const bb = this._pixBbox(pix);
      return {
        category: o.kind === "ignore" ? "ignore" : "nogo",
        shape: o.kind,
        model: "decorative",
        resize: null,
        kind: o.kind,
        objectId: o.id,
        category_code: o.kind === "ignore" ? 4 : 0,
        pts: [
          [bb.x, bb.y],
          [bb.x + bb.w, bb.y],
          [bb.x + bb.w, bb.y + bb.h],
          [bb.x, bb.y + bb.h],
        ],
        radius: 0,
      };
    }
    const draft = {
      category: o.kind === "ignore" ? "ignore" : "nogo",
      shape: o.kind === "ignore" ? "polygon" : null,
      model: null,
      resize: null,
      kind: o.kind, // composite (id+kind) selection key (Task 9)
      objectId: o.id,
      category_code: o.kind === "ignore" ? 4 : 0,
      pts: pix,
      radius: 0,
    };
    if (pix.length === 1 && o.radius) {
      // circle no-go: center + synthesized rim point
      const c = pix[0];
      const rim = metersToPixel(o.points_m[0][0] + o.radius, o.points_m[0][1], this._proj);
      const rpx = circleFromCenterEdge(c, rim).radius;
      draft.model = "circle";
      draft.shape = "circle";
      draft.pts = [c, [c[0] + rpx, c[1]]];
      draft.radius = rpx;
    } else if (pix.length === 2) {
      // a genuine 2-point no-go is a wall/line: render + edit as a line.
      draft.model = "line";
      draft.shape = "line";
    } else {
      // >=3 points: freeform polygon — drag each vertex; rotate works.
      draft.model = "corners";
      draft.resize = "vertex";
      if (draft.category === "nogo") draft.shape = "polygon";
    }
    return draft;
  }

  // ----- pointer handling --------------------------------------------------
  _svgPoint(e) {
    const svg = this.shadowRoot.getElementById("svg");
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const m = svg.getScreenCTM();
    if (!m) return [e.offsetX, e.offsetY];
    const p = pt.matrixTransform(m.inverse());
    return [p.x, p.y];
  }

  _onPointerDown(e) {
    const pos = this._svgPoint(e);
    // Draw mode (polygon) — TOP priority: each click APPENDS a vertex. No drag,
    // no handles (there are none while drawing), no overlay/tool logic.
    if (this._draft && this._draft.drawing) {
      this._draft.pts.push(pos);
      this._setMsg("");
      this._renderDraft();
      return;
    }
    const role = e.target && e.target.dataset ? e.target.dataset.role : null;
    // Handle controls on the active draft first.
    if (this._draft && role) {
      if (role === "del") { this._onDeleteHandle(); return; }
      e.target.setPointerCapture && e.target.setPointerCapture(e.pointerId);
      this._drag = { mode: role, idx: Number(e.target.dataset.idx), start: pos, refAngle: 0 };
      if (role === "rotate") this._drag.refAngle = this._rotateBasisAngle(this._draft, pos);
      return;
    }
    // Click an existing overlay -> select it. No-go & ignore share an id space,
    // so match BOTH id AND kind (Task 9).
    const id = e.target && e.target.dataset ? e.target.dataset.id : null;
    const kind = e.target && e.target.dataset ? e.target.dataset.kind : null;
    if (id != null && id !== "") {
      // Search the EFFECTIVE objects so re-selecting a just-edited shape picks
      // up the optimistic geometry, not HA's stale pre-edit data.
      const o = this._effectiveObjects(this._objs || []).find(
        (x) => String(x.id) === String(id) && (kind == null || x.kind === kind)
      );
      if (o) {
        this._tool = null;
        for (const b of this.shadowRoot.querySelectorAll(".bar button[data-tool]")) {
          b.classList.remove("on");
        }
        this._draft = this._draftFromObject(o);
        this._renderObjects(this._objs || []);
        this._renderDraft();
        return;
      }
    }
    // A tool is armed.
    if (this._tool) {
      // Draw tools (polygon / ignore): the first click starts a freeform draw —
      // seed a drawing draft with this point and wait for more clicks. No move.
      if (this._tool.draw) {
        this._draft = {
          category: this._tool.save.category,
          shape: this._tool.save.shape,
          model: "corners",
          resize: "vertex",
          drawing: true,
          kind: this._tool.save.category === "ignore" ? "ignore" : "nogo",
          objectId: null,
          pts: [pos],
        };
        this._setMsg("");
        this._renderDraft();
        return;
      }
      // Other tools: drop a new shape centered at the click and start move.
      this._draft = this._makeDraft(this._tool, pos);
      this._renderDraft();
      this._drag = { mode: "move", idx: -1, start: pos };
      const svg = this.shadowRoot.getElementById("svg");
      svg.setPointerCapture && svg.setPointerCapture(e.pointerId);
      return;
    }
    // Click on body of an active draft -> begin move-drag.
    if (this._draft) {
      this._drag = { mode: "move", idx: -1, start: pos };
      const svg = this.shadowRoot.getElementById("svg");
      svg.setPointerCapture && svg.setPointerCapture(e.pointerId);
    }
  }

  _onPointerMove(e) {
    if (!this._drag || !this._draft) return;
    const pos = this._svgPoint(e);
    const mode = this._drag.mode;
    if (mode === "move") {
      const dx = pos[0] - this._drag.start[0];
      const dy = pos[1] - this._drag.start[1];
      this._draft.pts = this._draft.pts.map(([x, y]) => [x + dx, y + dy]);
      this._drag.start = pos;
    } else if (mode === "rotate") {
      const d = this._draft;
      const ang = this._rotateBasisAngle(d, pos);
      const delta = ang - this._drag.refAngle;
      if (d.model === "edge") {
        d.pts = rotateEdgeAboutCenter(d.pts[0], d.pts[1], delta);
      } else {
        // corners / line: rigid rotation about the points' centroid.
        d.pts = rotatePointsAroundCentroid(d.pts, delta);
      }
      this._drag.refAngle = ang;
    } else if (mode === "resize") {
      this._applyResize(this._drag.idx, pos);
    } else if (mode === "endpoint") {
      this._draft.pts[this._drag.idx] = pos;
    }
    this._renderDraft();
  }

  _onPointerUp() {
    this._drag = null;
  }

  // Compute the rotate-drag basis angle for a draft (consistent ref/move basis
  // so the per-move delta is correct). Edge model rotates about the box centre,
  // but the delta angle about the points' centroid is what drives the sweep.
  _rotateBasisAngle(d, pos) {
    return pointerAngleAboutCentroid(d.pts, pos);
  }

  _applyResize(idx, pos) {
    const d = this._draft;
    if (d.model === "circle") {
      // Drag the rim handle; keep center fixed, recompute the rim radius via the
      // geom helper (no card-side distance math).
      d.pts[1] = pos;
      d.radius = circleFromCenterEdge(d.pts[0], pos).radius;
    } else if (d.model === "edge") {
      // aspect-locked scale of the oriented edge about the box centre.
      d.pts = resizeOrientedEdge(d.pts[0], d.pts[1], idx, pos);
    } else if (d.model === "corners" && d.resize === "rect") {
      // free-aspect 4-corner rectangle, anchored opposite, orientation preserved.
      d.pts = resizeRectCorner(d.pts, idx, pos);
    } else {
      // corners + "vertex" (free polygon / ignore) -> move just the dragged
      // vertex, so the user can reshape it into any freeform polygon (this is
      // what makes the polygon tool distinct from the rectangle tool).
      d.pts[idx] = [pos[0], pos[1]];
    }
  }

  _onDeleteHandle() {
    // For a new (un-saved) draft, delete just clears it. For an existing object
    // it deletes via the delete_map_object service (Task 7).
    if (this._draft && this._draft.objectId != null) {
      this._deleteExisting(this._draft);
      return;
    }
    this._draft = null;
    this._renderObjects(this._objs || []);
    this._renderDraft();
  }

  // Close the in-progress polygon: needs >=3 points. Flipping drawing=false
  // turns it into a normal editable draft (handles/move/rotate appear). The
  // only finish gesture — no click-first-vertex, no double-click.
  _onClosePolygon() {
    const d = this._draft;
    if (!d || !d.drawing) return;
    if ((d.pts || []).length < 3) {
      this._setMsg("Place at least 3 points");
      return;
    }
    d.drawing = false;
    this._setMsg("");
    this._renderDraft();
  }

  // Undo the last placed vertex while drawing. If that empties the draft, clear
  // it (back to the armed-tool state) and clear the message.
  _onUndoPoint() {
    const d = this._draft;
    if (!d || !d.drawing) return;
    d.pts.pop();
    if (d.pts.length === 0) {
      this._draft = null;
      this._setMsg("");
    }
    this._renderDraft();
  }

  // ----- service dispatch (Task 7) ----------------------------------------
  // Convert one pixel point -> meters (cloud edit frame). The geom helpers are
  // frame-agnostic, so all wire-point math runs in the meter frame here.
  _pxToM(p) { return pixelToMeters(p[0], p[1], this._proj); }

  // Build the wire { points, radius } (meter frame) directly from the draft's
  // stored defining points. Rotation is carried BY the points themselves:
  //   circle -> [center] + radius
  //   corners (rect/poly), line, edge -> the stored points in meters
  //     (square mow = 4 corners; curved mow = 2 edge points; rect/poly = N
  //      corners; line = 2 endpoints).
  _wirePoints(d) {
    if (d.model === "circle") {
      const center = this._pxToM(d.pts[0]);
      const radius = circleFromCenterEdge(center, this._pxToM(d.pts[1])).radius;
      return { points: [center], radius };
    }
    return { points: d.pts.map((p) => this._pxToM(p)), radius: 0 };
  }

  async _onSubmit() {
    const d = this._draft;
    if (!d || !this._hass) return;
    // Create/Save is blocked while drawing — the polygon isn't closed yet.
    if (d.drawing) {
      this._setMsg(d.pts.length < 3 ? "Place at least 3 points" : "Close the shape first");
      return;
    }
    const { points, radius } = this._wirePoints(d);
    const mapId = this._editMapId;
    this._setBusy(true);
    try {
      if (d.category === "nogo") {
        await this._hass.callService("dreame_a2_mower", "create_no_go_zone", {
          map_id: mapId,
          shape: d.shape, // "line" | "polygon" | "circle"
          points,
          radius,
          object_id: d.objectId != null ? d.objectId : -1,
        });
      } else if (d.category === "ignore") {
        await this._hass.callService("dreame_a2_mower", "create_ignore_obstacle", {
          map_id: mapId,
          points,
          object_id: d.objectId != null ? d.objectId : -1,
        });
      } else if (d.category === "mow") {
        // mow-shapes are create-only (not in editable_objects -> no edit path).
        await this._hass.callService("dreame_a2_mower", "create_mow_shape", {
          map_id: mapId,
          shape: d.shape,
          points,
        });
      } else if (d.category === "spot") {
        // o=214: 4 corner points, own opcode (no type/radius). Create or edit.
        await this._hass.callService("dreame_a2_mower", "create_spot", {
          map_id: mapId,
          points,
          object_id: d.objectId != null ? d.objectId : -1,
        });
      } else if (d.category === "maintenance") {
        // o=224: a single point -> flat (x, y); heading defaults 0 (read map has
        // none, so a MOVE resets heading to 0). Create or move (edit-in-place).
        const [x, y] = points[0];
        await this._hass.callService("dreame_a2_mower", "create_maintenance_point", {
          map_id: mapId,
          x,
          y,
          heading: 0,
          object_id: d.objectId != null ? d.objectId : -1,
        });
      } else if (d.category === "patrol") {
        // o=223: a single oriented point -> flat (x, y); heading defaults 0
        // (read map has none, so a MOVE resets heading to 0). DISTINCT opcode
        // from maintenance. Create or move (edit-in-place).
        const [x, y] = points[0];
        await this._hass.callService("dreame_a2_mower", "create_patrol_point", {
          map_id: mapId,
          x,
          y,
          heading: 0,
          object_id: d.objectId != null ? d.objectId : -1,
        });
      }
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("dreame-map-editor: submit failed", err);
      this._setBusy(false);
      return;
    }
    this._setBusy(false);
    // Optimistically reflect the edit so the overlay does NOT snap back to HA's
    // stale pre-edit data (which can lag the device by minutes). The descriptor
    // `kind` mirrors the editable_objects kind for this category.
    const kind = this._kindForCategory(d.category);
    const isPoint = d.category === "maintenance" || d.category === "patrol";
    const overlay = isPoint
      ? { point_m: points[0] }
      : { points_m: points, radius };
    if (d.objectId != null) {
      this._overrides[`${kind}:${d.objectId}`] = overlay;
    } else if (d.category !== "mow") {
      // new nogo/ignore/spot/maintenance -> provisional overlay (mow shapes
      // aren't decoded into editable_objects, so there's nothing to reconcile).
      this._provisional.push({ id: null, kind, ...overlay });
    }
    // Clear selection; the next camera refresh re-publishes editable_objects.
    this._draft = null;
    this._setMsg("");
    this._renderObjects(this._objs || []);
    this._renderDraft();
  }

  // Map a draft category to its editable_objects descriptor kind.
  _kindForCategory(cat) {
    if (cat === "ignore") return "ignore";
    if (cat === "spot") return "spot";
    if (cat === "maintenance") return "maintenance";
    if (cat === "patrol") return "patrol";
    return "nogo";
  }

  // Map a draft category to the delete_map_object wire category (o=218 type):
  // 0 = nogo/mow, 1 = spot, 2 = patrol, 3 = maintenance, 4 = ignore.
  _deleteCategory(cat) {
    if (cat === "ignore") return 4;
    if (cat === "spot") return 1;
    if (cat === "patrol") return 2;
    if (cat === "maintenance") return 3;
    return 0;
  }

  async _deleteExisting(d) {
    if (!this._hass || d.objectId == null) return;
    const category = this._deleteCategory(d.category);
    this._setBusy(true);
    try {
      await this._hass.callService("dreame_a2_mower", "delete_map_object", {
        map_id: this._editMapId,
        object_id: d.objectId,
        category,
      });
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("dreame-map-editor: delete failed", err);
      this._setBusy(false);
      return;
    }
    this._setBusy(false);
    // Optimistically hide the deleted object until HA's lagging data catches up.
    const kind = this._kindForCategory(d.category);
    this._overrides[`${kind}:${d.objectId}`] = null;
    this._draft = null;
    this._renderObjects(this._objs || []);
    this._renderDraft();
  }

  // ----- draft rendering ---------------------------------------------------
  _renderDraft() {
    const g = this.shadowRoot.getElementById("draft");
    if (!g) return;
    const d = this._draft;
    if (!d) { g.innerHTML = ""; this._syncActionButtons(); this._renderPatrolPanel(null); return; }
    // Draw mode (polygon): open polyline through the placed points + a dashed
    // close-preview from last->first + a vertex dot per point (first one larger
    // & distinct, the close-target hint). NO bbox / resize / rotate / delete.
    if (d.drawing) {
      const pts = d.pts || [];
      const dparts = [];
      if (pts.length >= 2) {
        const poly = pts.map((q) => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(" ");
        dparts.push(`<polyline class="drawline" points="${poly}"/>`);
        // Dashed close-preview edge (last -> first).
        const a = pts[pts.length - 1];
        const b = pts[0];
        dparts.push(
          `<line class="closehint" x1="${a[0].toFixed(1)}" y1="${a[1].toFixed(1)}" ` +
          `x2="${b[0].toFixed(1)}" y2="${b[1].toFixed(1)}"/>`
        );
      }
      pts.forEach((p, i) => {
        const r = i === 0 ? HANDLE_R + 1 : HANDLE_R - 2;
        const cls = i === 0 ? "vtx0" : "vtx";
        dparts.push(
          `<circle class="${cls}" cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="${r}"/>`
        );
      });
      g.innerHTML = dparts.join("");
      this._syncActionButtons();
      this._renderPatrolPanel(null);
      return;
    }
    const parts = [];
    // Point model (maintenance, o=224): a draggable marker + a delete handle.
    // No resize/rotate/vertex — the marker body itself is the move target
    // (data-role="move" on the <g>), drag = edit-in-place.
    if (d.model === "point") {
      const c = d.pts[0];
      // Patrol draft = teal accent marker; maintenance = orange. Both are the
      // bright "selected" variant (vs the muted non-selected obj markers).
      const markerCls = d.category === "patrol" ? "marker marker-patrol" : "marker";
      parts.push(this._markerSvg(c, markerCls, null, null, ` data-role="move"`));
      const dx = c[0] + DEL_OFF;
      const dy = c[1] - DEL_OFF;
      parts.push(
        `<g class="del" data-role="del">` +
        `<circle data-role="del" cx="${dx.toFixed(1)}" cy="${dy.toFixed(1)}" r="${HANDLE_R + 2}"/>` +
        `<text data-role="del" x="${dx.toFixed(1)}" y="${(dy + 4).toFixed(1)}" ` +
        `text-anchor="middle" font-size="14" font-family="system-ui">×</text>` +
        `</g>`
      );
      g.innerHTML = parts.join("");
      this._syncActionButtons();
      this._renderPatrolPanel(d);
      return;
    }
    // Decorative selection: the shape is drawn in the background, so show ONLY a
    // dashed bbox outline + a delete handle (no resize/rotate/vertex/endpoint
    // handles — decorative shapes are create+delete, not reshaped in place).
    if (d.model === "decorative") {
      const bb = this._bboxOf(d);
      parts.push(
        `<rect class="bbox" x="${bb.x.toFixed(1)}" y="${bb.y.toFixed(1)}" ` +
        `width="${bb.w.toFixed(1)}" height="${bb.h.toFixed(1)}"/>`
      );
      const dx = bb.x + bb.w + DEL_OFF;
      const dy = bb.y - DEL_OFF;
      parts.push(
        `<g class="del" data-role="del">` +
        `<circle data-role="del" cx="${dx.toFixed(1)}" cy="${dy.toFixed(1)}" r="${HANDLE_R + 2}"/>` +
        `<text data-role="del" x="${dx.toFixed(1)}" y="${(dy + 4).toFixed(1)}" ` +
        `text-anchor="middle" font-size="14" font-family="system-ui">×</text>` +
        `</g>`
      );
      g.innerHTML = parts.join("");
      this._syncActionButtons();
      this._renderPatrolPanel(null);
      return;
    }
    // Shape body + resize/endpoint handles, per manipulation model.
    if (d.model === "circle") {
      const c = d.pts[0];
      parts.push(
        `<circle class="draft" cx="${c[0].toFixed(1)}" cy="${c[1].toFixed(1)}" ` +
        `r="${(d.radius || 0).toFixed(1)}"/>`
      );
    } else if (d.model === "line") {
      const [a, b] = d.pts;
      parts.push(
        `<line class="draft" x1="${a[0].toFixed(1)}" y1="${a[1].toFixed(1)}" ` +
        `x2="${b[0].toFixed(1)}" y2="${b[1].toFixed(1)}"/>`
      );
    } else if (d.model === "edge") {
      // curved mow shape: WYSIWYG proxy is the oriented box.
      const box = orientedEdgeBox(d.pts[0], d.pts[1]);
      const dd = box.map((q) => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(" ");
      parts.push(`<polygon class="draft" points="${dd}"/>`);
    } else {
      // corners: draw the stored corners DIRECTLY (preserves rotation).
      const dd = d.pts.map((q) => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(" ");
      parts.push(`<polygon class="draft" points="${dd}"/>`);
    }
    // Bounding box (handle/rotate placement only).
    const bb = this._bboxOf(d);
    parts.push(
      `<rect class="bbox" x="${bb.x.toFixed(1)}" y="${bb.y.toFixed(1)}" ` +
      `width="${bb.w.toFixed(1)}" height="${bb.h.toFixed(1)}"/>`
    );
    // Resize / endpoint handles.
    if (d.model === "line") {
      d.pts.forEach((p, i) =>
        parts.push(this._handle(p[0], p[1], "endpoint", i))
      );
    } else if (d.model === "circle") {
      parts.push(this._handle(d.pts[1][0], d.pts[1][1], "resize", 0));
    } else if (d.model === "edge") {
      orientedEdgeBox(d.pts[0], d.pts[1]).forEach((p, i) =>
        parts.push(this._handle(p[0], p[1], "resize", i))
      );
    } else {
      // corners: a handle at each stored corner.
      d.pts.forEach((p, i) =>
        parts.push(this._handle(p[0], p[1], "resize", i))
      );
    }
    // Rotate handle (above bbox top-center) — SKIP for circle (rotation-invariant).
    const rcx = bb.x + bb.w / 2;
    const rcy = bb.y - ROTATE_OFF;
    if (d.model !== "circle") {
      parts.push(
        `<line class="bbox" x1="${rcx.toFixed(1)}" y1="${bb.y.toFixed(1)}" ` +
        `x2="${rcx.toFixed(1)}" y2="${rcy.toFixed(1)}"/>`
      );
      parts.push(
        `<circle class="rot" data-role="rotate" cx="${rcx.toFixed(1)}" ` +
        `cy="${rcy.toFixed(1)}" r="${HANDLE_R}"/>`
      );
    }
    // Delete X (bbox top-right).
    const dx = bb.x + bb.w + DEL_OFF;
    const dy = bb.y - DEL_OFF;
    parts.push(
      `<g class="del" data-role="del">` +
      `<circle data-role="del" cx="${dx.toFixed(1)}" cy="${dy.toFixed(1)}" r="${HANDLE_R + 2}"/>` +
      `<text data-role="del" x="${dx.toFixed(1)}" y="${(dy + 4).toFixed(1)}" ` +
      `text-anchor="middle" font-size="14" font-family="system-ui">×</text>` +
      `</g>`
    );
    g.innerHTML = parts.join("");
    this._syncActionButtons();
    this._renderPatrolPanel(null);
  }

  // Render the inline patrol-config panel (cycles + auto-capture) below the map
  // when a committed patrol point is selected (id >= 0). Hidden otherwise.
  // Reads cycles/auto_capture from `d` (the draft — which carries the optimistic
  // local values after each service call). Writes via set_patrol_point_config.
  _renderPatrolPanel(d) {
    const panel = this.shadowRoot && this.shadowRoot.getElementById("patrol-panel");
    if (!panel) return;
    // Show only for a committed (id >= 0) patrol draft; hide for everything else.
    const show = d && d.category === "patrol" && d.objectId != null && d.objectId >= 0;
    if (!show) {
      panel.className = "";
      panel.innerHTML = "";
      return;
    }
    const cycles = d.cycles ?? 1;
    const autoCap = !!d.auto_capture;
    panel.className = "visible";
    panel.innerHTML =
      `<label>Cycles:</label>` +
      `<div class="pcyc">` +
      [1, 2, 3].map((n) =>
        `<button data-cyc="${n}"${n === cycles ? ' class="on"' : ""}>${n}</button>`
      ).join("") +
      `</div>` +
      `<label style="margin-left:8px">Auto-capture:</label>` +
      `<input type="checkbox" id="patrolAuto"${autoCap ? " checked" : ""}>`;
    // Cycles buttons.
    for (const btn of panel.querySelectorAll("button[data-cyc]")) {
      btn.addEventListener("click", () => {
        const n = Number(btn.dataset.cyc);
        this._onPatrolConfigChange({ cycles: n });
      });
    }
    // Auto-capture toggle.
    const autoChk = panel.querySelector("#patrolAuto");
    if (autoChk) {
      autoChk.addEventListener("change", () => {
        this._onPatrolConfigChange({ auto_capture: autoChk.checked });
      });
    }
  }

  // Handle a patrol-config control change: call the service, update the draft
  // optimistically, re-render the panel.
  _onPatrolConfigChange(change) {
    const d = this._draft;
    if (!d || d.category !== "patrol" || d.objectId == null || !this._hass) return;
    // Build the object descriptor patrolConfigServiceData needs (id + current values).
    const obj = { id: d.objectId, kind: "patrol", cycles: d.cycles ?? 1, auto_capture: !!d.auto_capture };
    const data = patrolConfigServiceData(this._editMapId, obj, change);
    // Optimistic local update BEFORE the async call so the panel reflects the
    // change instantly (mirrors how _onSubmit updates _overrides before re-render).
    d.cycles = data.cycles;
    d.auto_capture = data.auto_capture;
    this._renderPatrolPanel(d);
    // Fire the service call async (no busy-spinner — the panel itself already
    // reflects the new state; a service error just logs to the console).
    this._hass.callService("dreame_a2_mower", "set_patrol_point_config", data)
      .catch((err) => {
        // eslint-disable-next-line no-console
        console.error("dreame-map-editor: set_patrol_point_config failed", err);
      });
  }

  _handle(x, y, role, idx) {
    return (
      `<circle class="handle" data-role="${role}" data-idx="${idx}" ` +
      `cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${HANDLE_R}"/>`
    );
  }

  // Single-point marker (o=224 maintenance): a filled circle + a small white
  // crosshair. `cls` is the group class; data-id/data-kind make the whole <g>
  // the select/click target. `extra` is appended to the group's attrs (e.g.
  // data-role="move" on the draft so the body is drag-to-move).
  _markerSvg(c, cls, id, kind, extra = "") {
    const x = c[0].toFixed(1);
    const y = c[1].toFixed(1);
    const idAttr = id != null ? ` data-id="${id}"` : "";
    const kindAttr = kind != null ? ` data-kind="${kind}"` : "";
    const r = HANDLE_R + 2;
    return (
      `<g class="${cls}"${idAttr}${kindAttr}${extra}>` +
      `<circle${idAttr}${kindAttr}${extra} cx="${x}" cy="${y}" r="${r}"/>` +
      `<line x1="${(c[0] - r).toFixed(1)}" y1="${y}" x2="${(c[0] + r).toFixed(1)}" y2="${y}"/>` +
      `<line x1="${x}" y1="${(c[1] - r).toFixed(1)}" x2="${x}" y2="${(c[1] + r).toFixed(1)}"/>` +
      `</g>`
    );
  }

  // Axis-aligned bbox of a list of pixel points {x,y,w,h}. Pure helper used for
  // the decorative hit-area rect (and reused by _bboxOf for the draft corners).
  _pixBbox(pix) {
    let minx = Infinity;
    let miny = Infinity;
    let maxx = -Infinity;
    let maxy = -Infinity;
    for (const [x, y] of pix) {
      if (x < minx) minx = x;
      if (y < miny) miny = y;
      if (x > maxx) maxx = x;
      if (y > maxy) maxy = y;
    }
    return { x: minx, y: miny, w: maxx - minx, h: maxy - miny };
  }

  // Pixel-space bbox of the current draft (for handle/rotate placement only).
  _bboxOf(d) {
    let pts = d.pts;
    if (d.model === "circle") {
      const [cx, cy] = d.pts[0];
      const r = d.radius || 0;
      pts = [[cx - r, cy - r], [cx + r, cy + r]];
    } else if (d.model === "edge") {
      pts = orientedEdgeBox(d.pts[0], d.pts[1]);
    }
    // corners / line: d.pts are the actual rendered corners/endpoints.
    let minx = Infinity;
    let miny = Infinity;
    let maxx = -Infinity;
    let maxy = -Infinity;
    for (const [x, y] of pts) {
      if (x < minx) minx = x;
      if (y < miny) miny = y;
      if (x > maxx) maxx = x;
      if (y > maxy) maxy = y;
    }
    return { x: minx, y: miny, w: maxx - minx, h: maxy - miny };
  }

  getCardSize() { return 6; }
  static getStubConfig() { return { entity: "camera.dreame_a2_mower_map" }; }
}

// ---- Task 6 manual-verification expectations ----
// In HA, with this card pointed at camera.dreame_a2_mower_map:
//  - Picking a tool then clicking the map drops that shape; clicking an existing
//    overlay selects it (it switches to the blue draft with handles).
//  - The 4 corner handles drag the bbox corners (rect tools) / scale uniformly
//    (polygon tools); the circle's single rim handle resizes it; a line shows 2
//    endpoint handles.
//  - The rotate handle (top stalk) visually rotates the shape rigidly about its
//    centroid; non-rect shapes scale uniformly (aspect preserved).
//  - Dragging the body moves the whole shape; the X clears a new draft.
//
// ---- Task 7 manual-verification expectations ----
//  - Draw a no-go (rect/circle/line/polygon) + Create -> the zone appears over
//    the map after the next camera refresh (create_no_go_zone, object_id -1).
//  - Select an existing no-go/ignore, resize/rotate/move it + Save -> it updates
//    in place (same object_id, edit-in-place).
//  - Draw an ignore polygon + Create -> appears (create_ignore_obstacle).
//  - Draw a mow-shape + Create -> appears (create_mow_shape; create-only — the
//    submit label never flips to "Save" for mow shapes because they are not in
//    editable_objects, so there is no selectable existing mow object).
//  - The X / Delete on a SELECTED existing object removes it (delete_map_object,
//    category 0 nogo / 4 ignore / 1 spot / 3 maintenance / 2 patrol). The map_id
//    used is the toolbar selector value.
//  - Patrol points (o=223): the Patrol ⊕ tool drops a marker; Create saves via
//    create_patrol_point (flat x, y, heading 0); selecting an existing patrol
//    point shows the bright teal marker (distinct from the muted non-selected
//    obj-patrol markers), and exactly ONE point is selected at a time.

if (!customElements.get("dreame-map-editor-card")) {
  customElements.define("dreame-map-editor-card", DreameMapEditorCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "dreame-map-editor-card",
    name: "Dreame Mower Map Editor",
    description: "Interactive map editor: draw / resize / delete no-go, ignore and mow shapes.",
  });
}

// Card version banner — lets the user confirm which build loaded in the
// browser console (the cards "cache hard"; a stale cache shows the old version).
const CARD_VERSION = "1.0.30a9";
console.info(
  `%c dreame-map-editor-card v${CARD_VERSION} `,
  "color:#fff;background:#2b8a3e;border-radius:3px;padding:1px 4px"
);
