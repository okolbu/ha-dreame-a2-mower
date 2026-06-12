// Interactive map-editor card: base <image> in an SVG viewBox plus draggable
// SVG overlays for the map's no-go / ignore / mow-shape edit objects.
//
// Reads camera.dreame_a2_mower_map .attributes:
//   map_projection, entity_picture, editable_objects, map_id, available_map_ids
// and writes via the dreame_a2_mower create_no_go_zone / create_ignore_obstacle
// / create_mow_shape / delete_map_object services.
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
  resizeUniform,
  circleFromCenterEdge,
  shapeToPoints,
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

const HANDLE_R = 7;       // resize-handle radius (px, viewBox units)
const ROTATE_OFF = 36;    // rotate-handle offset above the bbox top (px)
const DEL_OFF = 18;       // delete-X offset (px)
const DEFAULT_PX = 60;    // default half-extent of a freshly dropped shape

// Toolbar tool catalogue. `geom` selects the manipulation model:
//   bbox    -> 2 opposite corners rendered as a 4-corner rect (rect resize)
//   circle  -> center + edge point (single rim handle)
//   line    -> 2 endpoints (2 endpoint handles)
//   polygon -> N corners (uniform resize)
// `save` is { category, shape } passed to shapeToPoints at save time (Task 7).
const TOOLS = [
  { id: "nogo_rect", label: "No-go ▭", geom: "bbox", save: { category: "nogo", shape: "polygon" } },
  { id: "nogo_circle", label: "No-go ◯", geom: "circle", save: { category: "nogo", shape: "circle" } },
  { id: "nogo_line", label: "No-go ╱", geom: "line", save: { category: "nogo", shape: "line" } },
  { id: "nogo_poly", label: "No-go ⬠", geom: "polygon", save: { category: "nogo", shape: "polygon" } },
  { id: "ignore_poly", label: "Ignore ⬠", geom: "polygon", save: { category: "ignore", shape: "polygon" } },
  { id: "mow_square", label: "Mow ▢", geom: "bbox", save: { category: "mow", shape: "square" } },
  { id: "mow_circle", label: "Mow ◯", geom: "bbox", save: { category: "mow", shape: "circle" } },
  { id: "mow_heart", label: "Mow ♥", geom: "bbox", save: { category: "mow", shape: "heart" } },
  { id: "mow_triangle", label: "Mow △", geom: "bbox", save: { category: "mow", shape: "triangle" } },
  { id: "mow_teardrop", label: "Mow Teardrop", geom: "bbox", save: { category: "mow", shape: "teardrop" } },
  { id: "mow_mushroom", label: "Mow Mushroom", geom: "bbox", save: { category: "mow", shape: "mushroom" } },
  { id: "mow_cloud", label: "Mow Cloud", geom: "bbox", save: { category: "mow", shape: "cloud" } },
  { id: "mow_rainbow", label: "Mow Rainbow", geom: "bbox", save: { category: "mow", shape: "rainbow" } },
];

class DreameMapEditorCard extends HTMLElement {
  setConfig(cfg) {
    if (!cfg || !cfg.entity) throw new Error("entity is required");
    this._cfg = cfg;
    this._objKey = null; // identity of the last-rendered editable_objects set
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
    if (!a.map_projection || !a.entity_picture) return;
    this._proj = a.map_projection;
    this._ensureSvg(a);
    const img = this.shadowRoot.getElementById("base");
    if (img && img.getAttribute("href") !== a.entity_picture) {
      img.setAttribute("href", a.entity_picture);
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
      `.bar button{font:12px/1 system-ui,sans-serif;padding:4px 8px;border-radius:6px;` +
      `border:1px solid rgba(0,0,0,.3);background:rgba(255,255,255,.9);cursor:pointer}` +
      `.bar button.on{background:rgb(120,170,230);color:#fff}` +
      `.bar select{font:12px/1 system-ui,sans-serif;padding:3px 6px;border-radius:6px}` +
      `.bar .sp{flex:1}` +
      `.wrap{position:relative}` +
      `svg{width:100%;height:auto;display:block;touch-action:none}` +
      `.obj{cursor:pointer}` +
      `.obj-nogo{stroke:${NOGO_STROKE};fill:${NOGO_FILL};stroke-width:2}` +
      `.obj-ignore{stroke:${IGNORE_STROKE};fill:${IGNORE_FILL};stroke-width:2}` +
      `.draft{stroke:#1565c0;stroke-width:2;fill:rgba(21,101,192,0.15)}` +
      `.bbox{stroke:#1565c0;stroke-width:1;stroke-dasharray:4 3;fill:none;pointer-events:none}` +
      `.handle{fill:#fff;stroke:#1565c0;stroke-width:2;cursor:pointer}` +
      `.rot{fill:#1565c0;cursor:grab}` +
      `.del{fill:#d32f2f;cursor:pointer}` +
      `.del text{fill:#fff}` +
      `</style>` +
      `<div class="bar" id="bar"></div>` +
      `<div class="wrap">` +
      `<svg id="svg" viewBox="0 0 ${p.width_px} ${p.height_px}">` +
      `<image id="base" href="${a.entity_picture}" x="0" y="0" ` +
      `width="${p.width_px}" height="${p.height_px}"/>` +
      `<g id="objects"></g>` +
      `<g id="draft"></g>` +
      `</svg>` +
      `</div>`;
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
  }

  // Refresh the submit/delete button labels + enabled state from the draft.
  _syncActionButtons() {
    const submit = this.shadowRoot && this.shadowRoot.getElementById("submitBtn");
    const del = this.shadowRoot && this.shadowRoot.getElementById("deleteBtn");
    const editing = !!(this._draft && this._draft.objectId != null);
    if (submit) {
      submit.disabled = !this._draft;
      // mow-shapes are create-only (no edit-in-place path).
      submit.textContent = editing ? "Save" : "Create";
    }
    if (del) del.disabled = !editing;
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
    for (const b of this.shadowRoot.querySelectorAll(".bar button[data-tool]")) {
      b.classList.toggle("on", !!this._tool && b.dataset.tool === id);
    }
    this._renderDraft();
  }

  // ----- existing-object overlays (unselected) ----------------------------
  _syncObjects(a) {
    const objs = Array.isArray(a.editable_objects) ? a.editable_objects : [];
    this._objs = objs;
    const key = JSON.stringify(
      objs.map((o) => [o.id, o.op, o.type, o.kind, o.points_m, o.radius])
    );
    if (key === this._objKey) return;
    this._objKey = key;
    this._renderObjects(objs);
  }

  _renderObjects(objs) {
    const g = this.shadowRoot.getElementById("objects");
    if (!g) return;
    const selId = this._draft && this._draft.objectId != null ? this._draft.objectId : null;
    const parts = [];
    for (const o of objs) {
      if (o.id === selId) continue; // selected object is drawn as the draft
      const pts = Array.isArray(o.points_m) ? o.points_m : [];
      const pix = pts.map((m) => metersToPixel(m[0], m[1], this._proj));
      const cls = o.kind === "ignore" ? "obj obj-ignore" : "obj obj-nogo";
      if (pix.length >= 2) {
        const d = pix.map((q) => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(" ");
        parts.push(`<polygon class="${cls}" points="${d}" data-id="${o.id}"/>`);
      } else if (pix.length === 1 && o.radius) {
        const c = pix[0];
        const rim = metersToPixel(o.points_m[0][0] + o.radius, o.points_m[0][1], this._proj);
        const rpx = circleFromCenterEdge(c, rim).radius;
        parts.push(
          `<circle class="${cls}" cx="${c[0].toFixed(1)}" cy="${c[1].toFixed(1)}" ` +
          `r="${rpx.toFixed(1)}" data-id="${o.id}"/>`
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
      geom: tool.geom,
      objectId: null,
      pts: [],
      radius: 0,
    };
    if (tool.geom === "bbox") {
      // store the 2 opposite bbox corners; rendered as a rect
      draft.pts = [[cx - d, cy - d], [cx + d, cy + d]];
    } else if (tool.geom === "circle") {
      draft.pts = [[cx, cy], [cx + d, cy]]; // center, edge
      draft.radius = d;
    } else if (tool.geom === "line") {
      draft.pts = [[cx - d, cy], [cx + d, cy]];
    } else if (tool.geom === "polygon") {
      // default = axis-aligned square polygon (4 corners) the user can reshape
      draft.pts = rectCorners([cx - d, cy - d], [cx + d, cy + d]);
    }
    return draft;
  }

  // Build a draft from an existing editable_object (for select / edit-in-place).
  _draftFromObject(o) {
    const pix = (o.points_m || []).map((m) => metersToPixel(m[0], m[1], this._proj));
    const draft = {
      category: o.kind === "ignore" ? "ignore" : "nogo",
      shape: o.kind === "ignore" ? "polygon" : null,
      geom: null,
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
      draft.geom = "circle";
      draft.shape = "circle";
      draft.pts = [c, [c[0] + rpx, c[1]]];
      draft.radius = rpx;
    } else if (pix.length === 2) {
      draft.geom = "line";
      draft.shape = "line";
    } else {
      draft.geom = "polygon";
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
    const role = e.target && e.target.dataset ? e.target.dataset.role : null;
    // Handle controls on the active draft first.
    if (this._draft && role) {
      if (role === "del") { this._onDeleteHandle(); return; }
      e.target.setPointerCapture && e.target.setPointerCapture(e.pointerId);
      this._drag = { mode: role, idx: Number(e.target.dataset.idx), start: pos, refAngle: 0 };
      if (role === "rotate") this._drag.refAngle = pointerAngleAboutCentroid(this._draft.pts, pos);
      return;
    }
    // Click an existing overlay -> select it.
    const id = e.target && e.target.dataset ? e.target.dataset.id : null;
    if (id != null && id !== "") {
      const o = (this._objs || []).find((x) => String(x.id) === String(id));
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
    // A tool is armed -> drop a new shape centered at the click and start move.
    if (this._tool) {
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
      const ang = pointerAngleAboutCentroid(this._draft.pts, pos);
      this._draft.pts = rotatePointsAroundCentroid(this._draft.pts, ang - this._drag.refAngle);
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

  _applyResize(idx, pos) {
    const d = this._draft;
    if (d.geom === "bbox") {
      // Move the dragged corner; the diagonally-opposite corner is the anchor.
      const corners = rectCorners(d.pts[0], d.pts[1]);
      const opp = (idx + 2) % 4;
      d.pts = bboxAsTwo(rectCorners(corners[opp], pos));
    } else if (d.geom === "circle") {
      // Drag the rim handle; keep center fixed, recompute the rim radius via the
      // geom helper (no card-side distance math).
      d.pts[1] = pos;
      d.radius = circleFromCenterEdge(d.pts[0], pos).radius;
    } else {
      // polygon / line-as-polygon -> uniform scale about centroid
      d.pts = resizeUniform(d.pts, idx, pos);
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

  // ----- service dispatch (Task 7) ----------------------------------------
  // Convert one pixel point -> meters (cloud edit frame). The geom helpers are
  // frame-agnostic, so all wire-point math runs in the meter frame here.
  _pxToM(p) { return pixelToMeters(p[0], p[1], this._proj); }

  // Build the meter-frame `state` object that shapeToPoints consumes, keyed on
  // the SAVE shape (d.shape), from the current pixel draft. NO math here beyond
  // per-point px->m conversion and rectCorners structural plumbing.
  _meterState(d) {
    if (d.shape === "line") {
      return { a: this._pxToM(d.pts[0]), b: this._pxToM(d.pts[1]) };
    }
    if (d.shape === "circle" && d.category === "nogo") {
      return { center: this._pxToM(d.pts[0]), edge: this._pxToM(d.pts[1]) };
    }
    if (d.shape === "polygon") {
      // A bbox-geom polygon (the no-go rectangle tool) expands to 4 corners;
      // a true polygon draft passes its N corners straight through.
      const ptsPx = d.geom === "bbox" ? rectCorners(d.pts[0], d.pts[1]) : d.pts;
      return { points: ptsPx.map((p) => this._pxToM(p)) };
    }
    // mow shapes (square + curved) -> 2 opposite bbox corners
    return { p0: this._pxToM(d.pts[0]), p1: this._pxToM(d.pts[1]) };
  }

  async _onSubmit() {
    const d = this._draft;
    if (!d || !this._hass) return;
    const state = this._meterState(d);
    const { points, radius } = shapeToPoints(d.category, d.shape, state);
    const mapId = this._editMapId;
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
      }
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("dreame-map-editor: submit failed", err);
      return;
    }
    // Clear selection; the next camera refresh re-publishes editable_objects.
    this._draft = null;
    this._renderObjects(this._objs || []);
    this._renderDraft();
  }

  async _deleteExisting(d) {
    if (!this._hass || d.objectId == null) return;
    const category = d.category === "ignore" ? 4 : 0;
    try {
      await this._hass.callService("dreame_a2_mower", "delete_map_object", {
        map_id: this._editMapId,
        object_id: d.objectId,
        category,
      });
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("dreame-map-editor: delete failed", err);
      return;
    }
    this._draft = null;
    this._renderObjects(this._objs || []);
    this._renderDraft();
  }

  // ----- draft rendering ---------------------------------------------------
  _renderDraft() {
    const g = this.shadowRoot.getElementById("draft");
    if (!g) return;
    const d = this._draft;
    if (!d) { g.innerHTML = ""; this._syncActionButtons(); return; }
    const parts = [];
    // Shape body.
    if (d.geom === "circle") {
      const c = d.pts[0];
      parts.push(
        `<circle class="draft" cx="${c[0].toFixed(1)}" cy="${c[1].toFixed(1)}" ` +
        `r="${(d.radius || 0).toFixed(1)}"/>`
      );
    } else if (d.geom === "line") {
      const [a, b] = d.pts;
      parts.push(
        `<line class="draft" x1="${a[0].toFixed(1)}" y1="${a[1].toFixed(1)}" ` +
        `x2="${b[0].toFixed(1)}" y2="${b[1].toFixed(1)}"/>`
      );
    } else {
      const poly = d.geom === "bbox" ? rectCorners(d.pts[0], d.pts[1]) : d.pts;
      const dd = poly.map((q) => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(" ");
      parts.push(`<polygon class="draft" points="${dd}"/>`);
    }
    // Bounding box + handles.
    const bb = this._bboxOf(d);
    parts.push(
      `<rect class="bbox" x="${bb.x.toFixed(1)}" y="${bb.y.toFixed(1)}" ` +
      `width="${bb.w.toFixed(1)}" height="${bb.h.toFixed(1)}"/>`
    );
    // Resize / endpoint handles.
    if (d.geom === "line") {
      d.pts.forEach((p, i) =>
        parts.push(this._handle(p[0], p[1], "endpoint", i))
      );
    } else if (d.geom === "circle") {
      parts.push(this._handle(d.pts[1][0], d.pts[1][1], "resize", 0));
    } else if (d.geom === "bbox") {
      rectCorners(d.pts[0], d.pts[1]).forEach((p, i) =>
        parts.push(this._handle(p[0], p[1], "resize", i))
      );
    } else {
      d.pts.forEach((p, i) =>
        parts.push(this._handle(p[0], p[1], "resize", i))
      );
    }
    // Rotate handle (above bbox top-center) + delete X (bbox top-right).
    const rcx = bb.x + bb.w / 2;
    const rcy = bb.y - ROTATE_OFF;
    parts.push(
      `<line class="bbox" x1="${rcx.toFixed(1)}" y1="${bb.y.toFixed(1)}" ` +
      `x2="${rcx.toFixed(1)}" y2="${rcy.toFixed(1)}"/>`
    );
    parts.push(
      `<circle class="rot" data-role="rotate" cx="${rcx.toFixed(1)}" ` +
      `cy="${rcy.toFixed(1)}" r="${HANDLE_R}"/>`
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
  }

  _handle(x, y, role, idx) {
    return (
      `<circle class="handle" data-role="${role}" data-idx="${idx}" ` +
      `cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${HANDLE_R}"/>`
    );
  }

  // Pixel-space bbox of the current draft (for handle/rotate placement only).
  _bboxOf(d) {
    let pts = d.pts;
    if (d.geom === "circle") {
      const [cx, cy] = d.pts[0];
      const r = d.radius || 0;
      pts = [[cx - r, cy - r], [cx + r, cy + r]];
    } else if (d.geom === "bbox") {
      pts = rectCorners(d.pts[0], d.pts[1]);
    }
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

// Two opposite rect corners <-> the 2-point bbox draft representation.
// Reorders the 4 produced corners back to the [min,max]-ish pair the draft
// stores (corner[0], corner[2] are the diagonal). Pure index plumbing — no math.
function bboxAsTwo(corners) {
  return [corners[0], corners[2]];
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
//    category 0 nogo / 4 ignore). The map_id used is the toolbar selector value.

if (!customElements.get("dreame-map-editor-card")) {
  customElements.define("dreame-map-editor-card", DreameMapEditorCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "dreame-map-editor-card",
    name: "Dreame Mower Map Editor",
    description: "Interactive map editor: draw / resize / delete no-go, ignore and mow shapes.",
  });
}
