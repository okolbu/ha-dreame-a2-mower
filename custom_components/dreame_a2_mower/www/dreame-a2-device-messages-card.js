// Dreame A2 Mower — Device Messages Card.
//
// The device-message history with per-message snapshot thumbnails that open
// the shared in-card lightbox + AI-detection overlay. Replaces the strategy's
// markdown card for `sensor.dreame_a2_mower_device_messages`: markdown is
// HA-sanitized, so it can render neither the lightbox nor the overlay (a
// thumbnail there is at best a link that dumps the raw image in a new tab).
//
// Usage (Lovelace YAML):
//   - type: custom:dreame-a2-device-messages-card
//     # entity: sensor.dreame_a2_mower_device_messages   (default)
//
// Item shapes (newest-first) — see the `items` attribute of
// DreameA2DeviceMessagesSensor:
//   msg:   {title, body?, date (ISO 8601), unread?, photos?: [photo, ...]}
//   photo: {id, ts, category, detections:[{cls,conf,...}], url, thumb_url}
//          (domain/media/gallery.py: signed_photo_thumb —  already signed, so
//           the URL goes straight into <img src> with no auth header)
// Only snapshot messages carry `photos` (link_message_snapshot_photos matches
// them by timestamp window); every other message renders text-only.

import { defineCard, renderMissingEntity, openLightbox } from "./_dreame-card-core.js";

function _esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]
  ));
}

// ISO 8601 → a compact local "YYYY-MM-DD HH:MM". Falls back to the raw string
// for anything unparseable — a message with a weird date still shows its date
// rather than "Invalid Date".
function _fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso);
  const p = (n) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
    `${p(d.getHours())}:${p(d.getMinutes())}`
  );
}

// Flatten every message's photos into one list, in render order, so a
// thumbnail's `data-idx` is a single flat index into it. Messages without
// photos must NOT consume an index — hence a flat list rather than a
// (msg, photo) coordinate pair, which is what made the old per-message
// numbering fragile.
//
// Returns [{msgIdx, photo, caption}] and never throws on a malformed payload:
// the sensor attr is cloud-derived, and a card that throws in `set hass` takes
// the whole view down with it.
export function flattenPhotos(items) {
  const out = [];
  if (!Array.isArray(items)) return out;
  items.forEach((msg, msgIdx) => {
    const photos = msg && Array.isArray(msg.photos) ? msg.photos : [];
    for (const photo of photos) {
      if (photo) out.push({ msgIdx, photo, caption: (msg && msg.title) || "" });
    }
  });
  return out;
}

// A cheap fingerprint of what's actually rendered, so `set hass` (which fires
// on EVERY state update) re-renders only on a real change and doesn't reset the
// user's scroll position.
//
// The photo count is load-bearing: snapshot photos are linked onto an EXISTING
// message after the fact (link_message_snapshot_photos runs on each merge,
// matching against the hourly OSS gallery sync), which changes neither the
// message count nor the newest id. Keying on those alone would leave the
// thumbnails invisible until an unrelated new message arrived.
export function renderKey(items) {
  const list = Array.isArray(items) ? items : [];
  const newest = list[0] || {};
  return `${list.length}:${newest.id || newest.date || ""}:${flattenPhotos(list).length}`;
}

// Pure items[] → HTML. Every interpolated field is cloud-authored text, so it
// all goes through _esc — including thumb_url, which lands in an attribute.
export function renderMessagesHtml(items) {
  const list = Array.isArray(items) ? items : [];
  if (!list.length) {
    return '<div class="empty">No messages yet — the mower hasn\'t sent one since setup.</div>';
  }
  const flat = flattenPhotos(list);
  let idx = 0; // walks the SAME order flattenPhotos produces
  const rows = list.map((msg) => {
    const m = msg || {};
    const photos = Array.isArray(m.photos) ? m.photos.filter(Boolean) : [];
    const thumbs = photos.length
      ? '<div class="photos">' +
        photos
          .map((p) => {
            const i = idx++;
            return (
              `<img class="thumb" src="${_esc(p.thumb_url || p.url)}" ` +
              `data-idx="${i}" loading="lazy" ` +
              `alt="${_esc(p.category || "photo")}" title="${_esc(p.category || "photo")}"/>`
            );
          })
          .join("") +
        "</div>"
      : "";
    const date = _fmtDate(m.date);
    return (
      '<div class="msg">' +
      `<div class="head"><span class="dot">${m.unread ? "🔵" : "⚪"}</span>` +
      `<span class="title">${_esc(m.title)}</span>` +
      (date ? `<span class="date">${_esc(date)}</span>` : "") +
      "</div>" +
      (m.body ? `<div class="body">${_esc(m.body)}</div>` : "") +
      thumbs +
      "</div>"
    );
  });
  // Defensive: the two walks must agree, or a click opens the wrong photo.
  if (idx !== flat.length) {
    // eslint-disable-next-line no-console
    console.warn(`[dreame-a2-device-messages-card] photo index drift: ${idx} vs ${flat.length}`);
  }
  return rows.join("");
}

const STYLE = `
  <style>
    .wrap { padding: 8px 12px 12px; }
    .msg {
      padding: 8px 0;
      border-bottom: 1px solid var(--divider-color, #e0e0e0);
    }
    .msg:last-child { border-bottom: none; }
    .head { display: flex; align-items: baseline; gap: 6px; }
    .dot { flex: 0 0 auto; font-size: 10px; }
    .title { font-weight: 600; color: var(--primary-text-color); }
    .date {
      margin-left: auto; flex: 0 0 auto;
      font-size: 0.8em; color: var(--secondary-text-color);
    }
    .body {
      margin: 2px 0 0 22px;
      color: var(--secondary-text-color); font-size: 0.9em;
    }
    .photos {
      display: flex; gap: 6px; margin: 6px 0 2px 22px;
      overflow-x: auto;
    }
    .photos .thumb {
      height: 64px; width: auto; flex: 0 0 auto;
      border-radius: 4px; cursor: pointer;
      border: 1px solid var(--divider-color);
      object-fit: cover;
    }
    .empty {
      padding: 8px 0; color: var(--secondary-text-color); font-size: 0.9em;
    }
  </style>`;

class DreameA2DeviceMessagesCard extends HTMLElement {
  setConfig(cfg) {
    cfg = cfg || {};
    this._cfg = {
      entity: cfg.entity || "sensor.dreame_a2_mower_device_messages",
      title: cfg.title || "Device messages",
    };
    this._key = null;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    // Distinguish "entity not found" from a real-but-empty list (T6-20) —
    // otherwise a wrong entity id looks identical to a quiet mower.
    if (!hass || !hass.states[this._cfg.entity]) {
      if (this._missingShown !== this._cfg.entity) {
        this._missingShown = this._cfg.entity;
        this._key = null;
        this.shadowRoot.innerHTML = renderMissingEntity(this._cfg.entity);
      }
      return;
    }
    this._missingShown = null;
    const items = this._items();
    const key = renderKey(items);
    if (key === this._key) return;
    this._key = key;
    this._render(items);
  }

  _items() {
    const st = this._hass && this._hass.states[this._cfg.entity];
    const attr = st && st.attributes && st.attributes.items;
    return Array.isArray(attr) ? attr : [];
  }

  _render(items) {
    this._flat = flattenPhotos(items);
    this.shadowRoot.innerHTML =
      `<ha-card header="${_esc(this._cfg.title)}">${STYLE}` +
      `<div class="wrap">${renderMessagesHtml(items)}</div></ha-card>`;
    this.shadowRoot.querySelectorAll(".photos .thumb").forEach((img) => {
      img.onclick = () => {
        const entry = (this._flat || [])[Number(img.getAttribute("data-idx"))];
        if (!entry) return;
        this._lightbox = openLightbox({
          url: entry.photo.url || entry.photo.thumb_url,
          detections: entry.photo.detections,
          caption: entry.caption,
          alt: entry.photo.category || "photo",
        });
      };
    });
  }

  disconnectedCallback() {
    // The lightbox mounts on document.body to escape shadow-root clipping, so
    // it outlives the card unless we close it here (e.g. on a view switch).
    if (this._lightbox) {
      this._lightbox.close();
      this._lightbox = null;
    }
  }

  getCardSize() {
    return 4;
  }

  static getStubConfig() {
    return { entity: "sensor.dreame_a2_mower_device_messages" };
  }
}

// release.sh rewrites this one line per card; keep the exact `const CARD_VERSION
// = "..."` shape. defineCard logs the once-per-tag console banner.
const CARD_VERSION = "2.0.6";
defineCard("dreame-a2-device-messages-card", DreameA2DeviceMessagesCard, {
  name: "Dreame Mower Device Messages",
  description:
    "Device-message history with snapshot thumbnails that open a lightbox with the AI-detection overlay.",
  version: CARD_VERSION,
});
