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
  metersToPixel,
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

class DreameMapEditorCard extends HTMLElement {
  setConfig(cfg) {
    if (!cfg || !cfg.entity) throw new Error("entity is required");
    this._cfg = cfg;
    this._objKey = null; // identity of the last-rendered editable_objects set
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
    this._syncObjects(a);
  }

  _ensureSvg(a) {
    if (this.shadowRoot && this.shadowRoot.getElementById("svg")) return;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const p = a.map_projection;
    this.shadowRoot.innerHTML =
      `<style>:host{display:block}.wrap{position:relative}` +
      `svg{width:100%;height:auto;display:block;touch-action:none}` +
      `.obj{cursor:pointer}` +
      `.obj-nogo{stroke:${NOGO_STROKE};fill:${NOGO_FILL};stroke-width:2}` +
      `.obj-ignore{stroke:${IGNORE_STROKE};fill:${IGNORE_FILL};stroke-width:2}` +
      `</style>` +
      `<div class="wrap">` +
      `<svg id="svg" viewBox="0 0 ${p.width_px} ${p.height_px}">` +
      `<image id="base" href="${a.entity_picture}" x="0" y="0" ` +
      `width="${p.width_px}" height="${p.height_px}"/>` +
      `<g id="objects"></g>` +
      `</svg>` +
      `</div>`;
  }

  // Re-render the existing-object overlays only when the published set changes.
  _syncObjects(a) {
    const objs = Array.isArray(a.editable_objects) ? a.editable_objects : [];
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
    const parts = [];
    for (const o of objs) {
      const pts = Array.isArray(o.points_m) ? o.points_m : [];
      const pix = pts.map((m) => metersToPixel(m[0], m[1], this._proj));
      const cls = o.kind === "ignore" ? "obj obj-ignore" : "obj obj-nogo";
      if (pix.length >= 2) {
        const d = pix.map((q) => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(" ");
        parts.push(`<polygon class="${cls}" points="${d}" data-id="${o.id}"/>`);
      } else if (pix.length === 1 && o.radius) {
        // Circle no-go: center point + radius (meters). Project the center and a
        // rim point to get the on-screen radius without doing math in the card.
        const c = pix[0];
        const rim = metersToPixel(o.points_m[0][0] + o.radius, o.points_m[0][1], this._proj);
        const rpx = Math.hypot(rim[0] - c[0], rim[1] - c[1]);
        parts.push(
          `<circle class="${cls}" cx="${c[0].toFixed(1)}" cy="${c[1].toFixed(1)}" ` +
          `r="${rpx.toFixed(1)}" data-id="${o.id}"/>`
        );
      }
    }
    g.innerHTML = parts.join("");
  }

  getCardSize() { return 6; }
  static getStubConfig() { return { entity: "camera.dreame_a2_mower_map" }; }
}

if (!customElements.get("dreame-map-editor-card")) {
  customElements.define("dreame-map-editor-card", DreameMapEditorCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "dreame-map-editor-card",
    name: "Dreame Mower Map Editor",
    description: "Interactive map editor: draw / resize / delete no-go, ignore and mow shapes.",
  });
}
