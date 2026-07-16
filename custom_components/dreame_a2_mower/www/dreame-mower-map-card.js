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
  gapBreakIndices,
  trailPathD,
  buildMowerIconSvg,
  rssiToRgb,
  wifiOverlayKey,
} from "./_dreame-map-core.js";
import {
  defineCard,
  renderMissingEntity,
  checkMapSchema,
} from "./_dreame-card-core.js";

const ICON_PX = 32;
const GLIDE_MS = 5000;   // glide duration ~ the observed s1p4 cadence (~5s)
// Backfill points more than this far apart in time straddle a gap the
// integration didn't see (HA restart / downtime). The trail breaks there
// instead of drawing a phantom line across it. Well above the ~5s cadence.
const SEED_GAP_SECONDS = 30;
const WIFI_LS_KEY = "dreame-mower-wifi-overlay-on";

class DreameMowerMapCard extends HTMLElement {
  setConfig(cfg) {
    if (!cfg || !cfg.entity) throw new Error("entity is required");
    this._cfg = cfg;
    this._seq = -1;
    this._trail = [];
    this._breaks = new Set();   // indices that start a new subpath (gap pen-ups)
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
    if (!ent) {
      this._showPlaceholder(renderMissingEntity(this._cfg.entity));
      return;
    }
    const a = ent.attributes || {};
    checkMapSchema("dreame-mower-map-card", a);
    if (!a.map_projection || !a.entity_picture) {
      // Entity exists but hasn't published map geometry yet (fresh install /
      // mower never ran). Show a "waiting" placeholder instead of a blank card
      // (T6-20) — but only until the SVG is built, then never clobber it.
      this._showPlaceholder(renderMissingEntity(this._cfg.entity, { waiting: true }));
      return;
    }
    this._placeholder = null;
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
  // Render a missing/waiting placeholder (T6-20), but never over a live map:
  // once the SVG exists, a transient attribute drop keeps the last frame.
  _showPlaceholder(html) {
    if (this.shadowRoot && this.shadowRoot.getElementById("svg")) return;
    if (this._placeholder === html) return; // avoid per-tick DOM churn
    this._placeholder = html;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = html;
  }
  _ensureSvg(a) {
    const p = a.map_projection;
    if (this.shadowRoot && this.shadowRoot.getElementById("svg")) {
      // Already built — but the active map may have CHANGED. The viewBox and
      // base <image> box are pinned to the map that was active when the SVG was
      // first built; if we don't re-frame them here, a switch to a map with
      // different width_px/height_px leaves overlay/trail pixel coords (computed
      // from the NEW projection) being interpreted in the OLD map's viewBox.
      // Visible as the WiFi tiles landing in a small corner (switch to a larger
      // map) or overflowing off the image (switch to a smaller map).
      this._applyFrame(p);
      return;
    }
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const iconUrl = this._cfg.icon_url || "/dreame_a2_mower/mower-icon.png";
    // The wifi <g> sits BETWEEN the base image and the trail: it paints OVER
    // the opaque lawn PNG (so cells are visible) but UNDER the trail + mower
    // icon (so they're never occluded). Its <g opacity> makes the lawn show
    // through. The position-animation loop only touches #trail and #mower, so
    // the overlay never interferes with live painting.
    this.shadowRoot.innerHTML =
      `<style>:host{display:block}.wrap{position:relative}` +
      `svg{width:100%;height:auto;display:block}` +
      `.trail{fill:none;stroke:rgba(178,223,138,0.6);stroke-width:3;` +
      `stroke-linejoin:round;stroke-linecap:round}` +
      `#wifiToggle{position:absolute;top:8px;right:8px;z-index:2;` +
      `font:12px/1 system-ui,sans-serif;padding:4px 8px;border-radius:6px;` +
      `border:1px solid rgba(0,0,0,.3);background:rgba(255,255,255,.85);` +
      `cursor:pointer;display:none}` +
      `#wifiToggle.on{background:rgb(120,200,120)}</style>` +
      `<div class="wrap">` +
      `<svg id="svg" viewBox="0 0 ${p.width_px} ${p.height_px}">` +
      `<image id="base" href="${a.entity_picture}" x="0" y="0" ` +
      `width="${p.width_px}" height="${p.height_px}"/>` +
      `<g id="wifi" opacity="${this._wifiOpacity}"></g>` +
      `<path id="trail" class="trail" d=""/>` +
      buildMowerIconSvg(iconUrl, ICON_PX) +
      `</svg>` +
      `<button id="wifiToggle" type="button">WiFi</button>` +
      `</div>`;
    const btn = this.shadowRoot.getElementById("wifiToggle");
    btn.addEventListener("click", () => this._toggleWifi());
  }
  _applyFrame(p) {
    // Sync the SVG viewBox + base <image> box to the CURRENT projection. No-op
    // unless the active map's pixel dimensions changed (e.g. a map switch).
    const svg = this.shadowRoot && this.shadowRoot.getElementById("svg");
    if (!svg) return;
    const vb = `0 0 ${p.width_px} ${p.height_px}`;
    if (svg.getAttribute("viewBox") === vb) return;
    svg.setAttribute("viewBox", vb);
    const base = this.shadowRoot.getElementById("base");
    if (base) {
      base.setAttribute("width", p.width_px);
      base.setAttribute("height", p.height_px);
    }
    // The previously-rendered overlay + trail are in the OLD pixel frame and are
    // now mis-scaled. Force a WiFi re-render (next _syncWifi) and re-seed the
    // trail from the snapshot in the new frame (idle icon re-places itself each
    // update from last_known_point, so it self-corrects).
    this._wifiKey = null;
    this._trail = [];
    this._breaks = new Set();
    this._redrawTrail();
    this._seq = -1;
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
      // Clear any previously-rendered overlay so a stale map's RSSI rects don't
      // linger when the active map has no (cached) heatmap yet.
      const g = this.shadowRoot.getElementById("wifi");
      if (g) g.innerHTML = "";
      this._wifiKey = null;
      return;
    }
    if (btn) btn.style.display = "block";
    // Key on map identity + projection + geometry — NOT geometry alone — so a
    // map switch always re-renders (different maps can share heatmap geometry,
    // and the rects must follow the active map's projection). See wifiOverlayKey.
    const key = wifiOverlayKey(overlay, a.map_id, a.map_projection);
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
    // Break the polyline across downtime gaps so they render empty, not bridged.
    this._breaks = gapBreakIndices(snap, SEED_GAP_SECONDS);
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
    path.setAttribute("d", trailPathD(this._trail, this._breaks));
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
// release.sh rewrites this one line per card; keep the exact `const CARD_VERSION
// = "..."` shape. defineCard logs the once-per-tag console banner.
const CARD_VERSION = "2.1.0";
defineCard("dreame-mower-map-card", DreameMowerMapCard, {
  name: "Dreame Mower Live Map",
  description: "Animated live map: base + trail + directional mower icon + WiFi overlay.",
  version: CARD_VERSION,
});
