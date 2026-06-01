// Live map card: SVG base <image> + client-accumulated trail + directional
// mower icon, animated between ~5s position messages. Reads the published
// stream (map_projection, point_seq, latest_point, track_snapshot,
// background_mode) from camera.dreame_a2_mower_map. Replaces the
// picture-entity / live-image-card for the live map.
//
// Load as a Lovelace resource (type: module):
//   url: /dreame_a2_mower/dreame-mower-map-card.js
import { projectPoint, iconRotation, buildMowerIconSvg } from "./_dreame-map-core.js";

const ICON_PX = 32;
const GLIDE_MS = 5000;   // glide duration ~ the observed s1p4 cadence (~5s)

class DreameMowerMapCard extends HTMLElement {
  setConfig(cfg) {
    if (!cfg || !cfg.entity) throw new Error("entity is required");
    this._cfg = cfg;
    this._seq = -1;
    this._trail = [];
    this._iconAt = null;
    this._iconAngle = 0;
    this._anim = null;
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
    this.shadowRoot.innerHTML =
      `<style>:host{display:block} svg{width:100%;height:auto}` +
      `.trail{fill:none;stroke:rgb(178,223,138);stroke-width:3;` +
      `stroke-linejoin:round;stroke-linecap:round}</style>` +
      `<svg id="svg" viewBox="0 0 ${p.width_px} ${p.height_px}">` +
      `<image id="base" href="${a.entity_picture}" x="0" y="0" ` +
      `width="${p.width_px}" height="${p.height_px}"/>` +
      `<path id="trail" class="trail" d=""/>` +
      buildMowerIconSvg(iconUrl, ICON_PX) +
      `</svg>`;
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
    description: "Animated live map: base + trail + directional mower icon.",
  });
}
