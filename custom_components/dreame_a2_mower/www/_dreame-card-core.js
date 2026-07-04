// Dreame A2 Mower — shared card scaffolding
//
// UI plumbing shared by the bundled Lovelace cards: guarded registration +
// version banner (T6-8), a consistent missing-entity placeholder (T6-20), one
// fullscreen media lightbox (T6-17), and the map-attr schema-version guard
// (T6-9). This is an underscore-prefixed shared ES module (like
// `_dreame-map-core.js`): it carries NO `const CARD_VERSION` banner of its own
// (release.sh skips `_*` files), and the pure map/projection math stays in
// `_dreame-map-core.js` — this file is DOM plumbing only.

import { attachDetectionOverlay } from "./_dreame-map-core.js";

// ---------------------------------------------------------------------------
// Registration + version banner
// ---------------------------------------------------------------------------

const _banners = new Set();

// Log the "which build actually loaded" console banner ONCE per tag. The cards
// cache hard in the browser (feedback_frontend_card_verification), so this is
// how a user confirms a stale cache. Guarded so a double module-load (the same
// card served under two resource URLs, e.g. `?v=` variants) doesn't spam it.
export function logCardVersion(tag, version) {
  if (!version || _banners.has(tag)) return;
  _banners.add(tag);
  // eslint-disable-next-line no-console
  console.info(
    `%c ${tag} v${version} `,
    "color:#fff;background:#2b8a3e;border-radius:3px;padding:1px 4px",
  );
}

// Guarded custom-element registration + customCards catalog entry + banner.
//
// T6-8: an unguarded `customElements.define(tag, cls)` throws a DOMException
// ("this name has already been used") when the module is evaluated twice — the
// live instance already serves cards under `?v=` query variants, and each
// distinct URL is a distinct module, so a stale duplicate resource entry would
// otherwise kill the second load. `if (!customElements.get(tag))` makes the
// second define a no-op. `meta = { name, description, version }`.
export function defineCard(tag, cls, meta = {}) {
  if (customElements.get(tag)) return false;
  customElements.define(tag, cls);
  if (typeof window !== "undefined") {
    window.customCards = window.customCards || [];
    if (!window.customCards.some((c) => c && c.type === tag)) {
      window.customCards.push({
        type: tag,
        name: meta.name || tag,
        description: meta.description || "",
      });
    }
  }
  logCardVersion(tag, meta.version);
  return true;
}

// ---------------------------------------------------------------------------
// Missing-entity / waiting-for-data placeholder (T6-20)
// ---------------------------------------------------------------------------

function _esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]
  ));
}

// A consistent placeholder for "the entity this card points at isn't there yet"
// — before this, some cards rendered a message and others rendered nothing
// (a blank card indistinguishable from "still loading" on a fresh install).
// Returns an HTML string for `shadowRoot.innerHTML =` (never empty), so a card
// with no data always says WHY. `opts.waiting=true` softens the wording for the
// "entity exists but hasn't published its attributes yet" case.
export function renderMissingEntity(entityId, opts = {}) {
  const id = _esc(entityId || "(entity: unset)");
  const title = opts.waiting ? "Waiting for data…" : "Entity not found";
  const detail = opts.waiting
    ? `<code>${id}</code> has no data yet — the integration hasn't published it, or the mower hasn't run since setup.`
    : `Set the card's <code>entity:</code> — <code>${id}</code> is not in this Home Assistant.`;
  return (
    `<ha-card><div style="padding:16px;font:14px/1.45 system-ui,sans-serif;` +
    `color:var(--secondary-text-color,#727272);">` +
    `<div style="font-weight:600;color:var(--primary-text-color,#212121);` +
    `margin-bottom:4px;">${_esc(opts.title || title)}</div>${detail}</div></ha-card>`
  );
}

// ---------------------------------------------------------------------------
// Fullscreen media lightbox (T6-17)
// ---------------------------------------------------------------------------

// One backdrop + ESC + close-button lightbox for a photo (with optional
// AI-detection overlay) or a video, replacing the near-identical copies in the
// replay + gallery cards. Mounts on document.body so `position:fixed` escapes
// any card shadow-root clipping. Returns a handle `{ close() }`; the caller
// keeps it to dismiss the box (e.g. from disconnectedCallback).
//
// item = { url, video?:bool, detections?:[], caption?:str, alt?:str }
export function openLightbox(item = {}) {
  const stop = (e) => e.stopPropagation();

  const lb = document.createElement("div");
  lb.className = "dreame-lightbox";
  lb.style.cssText =
    "position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.85);" +
    "display:flex;align-items:center;justify-content:center;flex-direction:column;";

  let videoEl = null;
  if (item.video) {
    videoEl = document.createElement("video");
    videoEl.setAttribute("controls", "");
    videoEl.setAttribute("autoplay", "");
    videoEl.setAttribute("playsinline", "");
    if (item.url) videoEl.setAttribute("src", item.url);
    videoEl.style.cssText = "max-width:92vw;max-height:86vh;display:block;";
    videoEl.addEventListener("click", stop);
    lb.appendChild(videoEl);
  } else {
    const wrap = document.createElement("div");
    wrap.style.cssText = "position:relative;display:inline-block;line-height:0;";
    wrap.addEventListener("click", stop);
    const img = document.createElement("img");
    if (item.url) img.setAttribute("src", item.url);
    img.alt = item.alt || item.caption || "photo";
    img.style.cssText = "max-width:92vw;max-height:86vh;display:block;";
    wrap.appendChild(img);
    attachDetectionOverlay(wrap, img, item.detections);
    lb.appendChild(wrap);
  }

  if (item.caption) {
    const cap = document.createElement("div");
    cap.textContent = item.caption;
    cap.style.cssText =
      "margin-top:12px;color:#eee;font:13px/1.4 system-ui,sans-serif;" +
      "max-width:92%;text-align:center;";
    cap.addEventListener("click", stop);
    lb.appendChild(cap);
  }

  const close = document.createElement("button");
  close.textContent = "×"; // ×
  close.setAttribute("aria-label", "Close");
  close.style.cssText =
    "position:absolute;top:12px;right:16px;width:40px;height:40px;border:none;" +
    "border-radius:50%;background:rgba(255,255,255,0.15);color:#fff;" +
    "font-size:24px;line-height:1;cursor:pointer;";
  lb.appendChild(close);

  let onKey = null;
  const doClose = () => {
    if (onKey) {
      document.removeEventListener("keydown", onKey);
      onKey = null;
    }
    if (videoEl) {
      try {
        videoEl.pause();
        videoEl.removeAttribute("src");
        videoEl.load();
      } catch (_) {
        /* ignore */
      }
    }
    if (lb.parentNode) lb.parentNode.removeChild(lb);
  };

  close.addEventListener("click", (e) => {
    stop(e);
    doClose();
  });
  // Backdrop click (anything not caught by media/caption) closes.
  lb.addEventListener("click", doClose);
  onKey = (e) => {
    if (e.key === "Escape") doClose();
  };
  document.addEventListener("keydown", onKey);

  const root =
    (typeof document !== "undefined" && (document.body || document.documentElement)) || null;
  if (root) root.appendChild(lb);
  return { close: doClose, el: lb };
}

// ---------------------------------------------------------------------------
// Map-attr schema-version guard (T6-9)
// ---------------------------------------------------------------------------

// The camera map entity stamps every attribute payload with `schema_version`
// (camera/map.py:MAP_ATTR_SCHEMA_VERSION). The cache-bust story is otherwise
// incoherent — a `?v=` bump on a card does NOT bust its ES-imported shared
// modules — so at minimum a card reads the version it was built against and
// warns ONCE when the running backend ships a different one, instead of
// silently mis-rendering an attr shape it doesn't understand. Keep this in
// lockstep with camera/map.py:MAP_ATTR_SCHEMA_VERSION.
export const EXPECTED_MAP_SCHEMA = 5;

const _schemaWarned = new Set();

// Returns the observed schema_version (or null). Logs a one-time console.warn
// per (tag, observed) when it differs from `expected`. Never throws — the card
// still renders best-effort; this only makes the mismatch visible.
export function checkMapSchema(tag, attrs, expected = EXPECTED_MAP_SCHEMA) {
  const got = attrs && attrs.schema_version;
  if (got == null || got === expected) return got == null ? null : got;
  const key = `${tag}:${got}`;
  if (!_schemaWarned.has(key)) {
    _schemaWarned.add(key);
    // eslint-disable-next-line no-console
    console.warn(
      `[${tag}] map attr schema_version=${got} but this card expects ` +
        `${expected} — a stale cached card or a newer integration. ` +
        `Hard-refresh the browser if the map looks wrong.`,
    );
  }
  return got;
}
