// Dreame A2 Mower — Photo/Video Gallery Card.
//
// Thumbnail gallery of archived AI-detection / patrol / obstacle photos + videos,
// with filter tabs and a click-to-enlarge lightbox. Reads the
// `items` attribute of a sensor (default sensor.dreame_a2_mower_photo_gallery)
// produced by the integration's OSS gallery manifest — each item is already a
// signed URL, so the thumbnails/media go straight into <img>/<video> src with
// no auth header needed.
//
// Usage (Lovelace YAML):
//   - type: custom:dreame-a2-photo-gallery-card
//     # entity: sensor.dreame_a2_mower_photo_gallery   (default)
//
// Item shapes (newest-first):
//   photo: {type:"photo", id, ts, date,
//           category:"ai_human"|"ai_animal"|"ai_object"|"obstacle"|"patrol"|"manual",
//           detections:[{cls,conf,...}, ...], url, thumb_url}
//   video: {type:"video", id, ts, date, category:"video", duration:int(sec),
//           url, thumb_url}

import { defineCard, renderMissingEntity, openLightbox } from "./_dreame-card-core.js";

const CATEGORY_LABELS = {
  ai_human: "AI · Human",
  ai_animal: "AI · Animal",
  ai_object: "AI · Object",
  obstacle: "Obstacle",
  patrol: "Patrol",
  manual: "Manual",
};

class DreameA2PhotoGalleryCard extends HTMLElement {
  setConfig(cfg) {
    cfg = cfg || {};
    this._cfg = { entity: cfg.entity || "sensor.dreame_a2_mower_photo_gallery" };
    this._filter = "all";
    this._itemsKey = null;
    this._built = false;
  }

  set hass(hass) {
    this._hass = hass;
    // Distinguish "entity not found" (wrong id / fresh install) from an empty
    // gallery — otherwise a missing entity renders the same "No photos yet"
    // grid as a real-but-empty one (T6-20).
    if (!hass.states[this._cfg.entity]) {
      if (!this.shadowRoot) this.attachShadow({ mode: "open" });
      if (this._missingShown !== this._cfg.entity) {
        this._missingShown = this._cfg.entity;
        this._built = false;
        this.shadowRoot.innerHTML = renderMissingEntity(this._cfg.entity);
      }
      return;
    }
    this._missingShown = null;
    if (!this._built) this._build();
    const items = this._items();
    const key = items.length + ":" + (items[0] && items[0].id);
    if (key !== this._itemsKey) {
      this._itemsKey = key;
      this._renderTabs();
      this._renderGrid();
    }
  }

  // --- data ---------------------------------------------------------------

  _items() {
    const st = this._hass && this._hass.states[this._cfg.entity];
    const attr = st && st.attributes && st.attributes.items;
    return Array.isArray(attr) ? attr : [];
  }

  _categories() {
    // Distinct photo categories present, in a stable display order.
    const order = ["ai_human", "ai_animal", "ai_object", "obstacle", "patrol", "manual"];
    const present = new Set();
    for (const it of this._items()) {
      if (it.type === "photo" && it.category) present.add(it.category);
    }
    return order.filter((c) => present.has(c));
  }

  _hasVideos() {
    return this._items().some((it) => it.type === "video");
  }

  _filtered() {
    const f = this._filter;
    return this._items().filter((it) => {
      if (f === "all") return true;
      if (f === "videos") return it.type === "video";
      return it.type === "photo" && it.category === f;
    });
  }

  // --- shadow DOM scaffold ------------------------------------------------

  _build() {
    this.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = `
      :host { display: block; }
      ha-card { overflow: hidden; }
      .tabs {
        display: flex; flex-wrap: wrap; gap: 6px;
        padding: 12px 16px 4px;
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
      }
      .tab {
        appearance: none; border: none; cursor: pointer;
        padding: 6px 14px; border-radius: 16px; font-size: 13px;
        background: var(--secondary-background-color, #eee);
        color: var(--primary-text-color, #212121);
        line-height: 1.2;
      }
      .tab.active {
        background: var(--primary-color, #03a9f4);
        color: var(--text-primary-color, #fff);
      }
      .grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
        gap: 8px; padding: 12px 16px 16px;
      }
      .cell {
        position: relative; aspect-ratio: 1 / 1;
        border-radius: 8px; overflow: hidden; cursor: pointer;
        background: var(--secondary-background-color, #eee);
      }
      .cell img {
        width: 100%; height: 100%; object-fit: cover; display: block;
      }
      .cell .cap {
        position: absolute; left: 0; right: 0; bottom: 0;
        padding: 4px 6px; font-size: 11px; line-height: 1.25;
        color: #fff; background: rgba(0,0,0,0.55);
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
      }
      .cell .play {
        position: absolute; top: 50%; left: 50%;
        transform: translate(-50%, -50%);
        width: 40px; height: 40px; border-radius: 50%;
        background: rgba(0,0,0,0.5); color: #fff;
        display: flex; align-items: center; justify-content: center;
        font-size: 18px; pointer-events: none;
      }
      .empty {
        padding: 40px 16px; text-align: center;
        color: var(--secondary-text-color, #727272); font-size: 14px;
      }
      /* The click-to-enlarge lightbox is the shared openLightbox() from
         _dreame-card-core.js (T6-17) — it mounts on document.body with inline
         styles, so no lightbox CSS lives here. */
    `;
    const card = document.createElement("ha-card");
    this._tabsEl = document.createElement("div");
    this._tabsEl.className = "tabs";
    this._gridEl = document.createElement("div");
    this._gridEl.className = "grid";
    card.appendChild(this._tabsEl);
    card.appendChild(this._gridEl);
    this.shadowRoot.appendChild(style);
    this.shadowRoot.appendChild(card);
    this._built = true;
  }

  // --- rendering ----------------------------------------------------------

  _renderTabs() {
    this._tabsEl.textContent = "";
    const tabs = [{ id: "all", label: "All" }];
    for (const c of this._categories()) {
      tabs.push({ id: c, label: CATEGORY_LABELS[c] || this._titleCase(c) });
    }
    if (this._hasVideos()) tabs.push({ id: "videos", label: "Videos" });

    // If the active filter no longer exists in the data, fall back to All.
    if (!tabs.some((t) => t.id === this._filter)) this._filter = "all";

    for (const t of tabs) {
      const btn = document.createElement("button");
      btn.className = "tab" + (t.id === this._filter ? " active" : "");
      btn.textContent = t.label;
      btn.addEventListener("click", () => {
        if (this._filter === t.id) return;
        this._filter = t.id;
        this._renderTabs();
        this._renderGrid();
      });
      this._tabsEl.appendChild(btn);
    }
  }

  _renderGrid() {
    this._gridEl.textContent = "";
    const items = this._filtered();
    if (items.length === 0) {
      this._gridEl.style.display = "block";
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent =
        this._filter === "videos"
          ? "No videos yet."
          : "No photos archived yet.";
      this._gridEl.appendChild(empty);
      return;
    }
    this._gridEl.style.display = "grid";
    for (const item of items) {
      this._gridEl.appendChild(this._cell(item));
    }
  }

  _cell(item) {
    const cell = document.createElement("div");
    cell.className = "cell";

    const img = document.createElement("img");
    img.loading = "lazy";
    if (item.thumb_url) img.setAttribute("src", item.thumb_url);
    img.alt = item.category || item.type || "";
    cell.appendChild(img);

    if (item.type === "video") {
      const play = document.createElement("div");
      play.className = "play";
      play.textContent = "▶"; // ▶
      cell.appendChild(play);
    }

    const cap = document.createElement("div");
    cap.className = "cap";
    cap.textContent = this._captionText(item);
    cell.appendChild(cap);

    cell.addEventListener("click", () => this._openLightbox(item));
    return cell;
  }

  // Build the short caption shown on a grid cell and in the lightbox.
  _captionText(item) {
    let txt = item.date || "";
    if (item.type === "video") {
      if (item.duration) txt += " · " + this._fmtDuration(item.duration);
    } else if (Array.isArray(item.detections) && item.detections.length) {
      const d = item.detections[0];
      if (d && d.cls != null) {
        const conf = Math.round((d.conf || 0) * 100);
        txt += " · " + d.cls + " " + conf + "%";
      }
    }
    return txt;
  }

  _fmtDuration(sec) {
    sec = Math.max(0, Math.round(Number(sec) || 0));
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return m + ":" + String(s).padStart(2, "0");
  }

  _titleCase(s) {
    s = String(s);
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // --- lightbox -----------------------------------------------------------

  _openLightbox(item) {
    if (this._lbHandle) this._lbHandle.close(); // ensure only one
    this._lbHandle = openLightbox({
      url: item.url,
      video: item.type === "video",
      detections: item.detections,
      caption: this._captionText(item),
      alt: item.category || "photo",
    });
  }

  disconnectedCallback() {
    if (this._lbHandle) {
      this._lbHandle.close();
      this._lbHandle = null;
    }
  }

  getCardSize() {
    return 8;
  }

  static getStubConfig() {
    return { entity: "sensor.dreame_a2_mower_photo_gallery" };
  }
}

// release.sh rewrites this one line per card; keep the exact `const CARD_VERSION
// = "..."` shape. defineCard logs the once-per-tag console banner.
const CARD_VERSION = "1.0.32a1";
defineCard("dreame-a2-photo-gallery-card", DreameA2PhotoGalleryCard, {
  name: "Dreame Mower Photo Gallery",
  description:
    "Thumbnail gallery of archived AI-detection / patrol / obstacle photos + videos, click to enlarge.",
  version: CARD_VERSION,
});
