// Device-messages card harness — exercises the PURE list/photo logic that
// `node --check` can't see (feedback_frontend_card_verification: node --check
// only catches syntax). The card's DOM wiring is covered by
// card_core_harness.mjs (guarded define + missing-entity path); this file pins
// the two pure functions the card is built on.
//
// Asserts:
//   (a) flattenPhotos indexes every photo across messages ONCE, in render
//       order, so a thumbnail's data-idx resolves to the right photo.
//   (b) renderMessagesHtml escapes untrusted message text (titles/bodies come
//       from the cloud), renders one <img> per photo, and says WHY when empty.

import assert from "node:assert";

// Minimal globals so the module-level `class extends HTMLElement` + defineCard
// evaluate on import. The card's DOM behaviour is card_core_harness.mjs's job;
// here these only make the import succeed so the pure exports are reachable.
globalThis.HTMLElement = class {};
globalThis.customElements = { get: () => undefined, define() {} };
globalThis.window = { customCards: [] };

const CARD =
  "../../custom_components/dreame_a2_mower/www/dreame-a2-device-messages-card.js";
const { flattenPhotos, renderMessagesHtml, renderKey } = await import(CARD);

// --- fixtures: the sensor's items[] shape --------------------------------
// msg: {title, body?, date (ISO), unread?, photos?[]}
// photo: {id, ts, category, detections, url, thumb_url}
//   (domain/media/gallery.py:signed_photo_thumb + link_message_snapshot_photos)

const PHOTO_A = {
  id: "a.jpg", ts: 100, category: "ai_human",
  detections: [{ cls: "person", conf: 0.9 }],
  url: "/u/a.jpg", thumb_url: "/t/a.jpg",
};
const PHOTO_B = {
  id: "b.jpg", ts: 200, category: "ai_animal", detections: [],
  url: "/u/b.jpg", thumb_url: "/t/b.jpg",
};
const PHOTO_C = {
  id: "c.jpg", ts: 300, category: "obstacle", detections: [],
  url: "/u/c.jpg", thumb_url: "/t/c.jpg",
};

const ITEMS = [
  { title: "Person detected", date: "2026-07-16T10:00:00Z", unread: true,
    photos: [PHOTO_A, PHOTO_B] },
  { title: "Docked", body: "Charging", date: "2026-07-16T09:00:00Z" },
  { title: "Obstacle", date: "2026-07-16T08:00:00Z", photos: [PHOTO_C] },
];

// --- (a) flattenPhotos ----------------------------------------------------

const flat = flattenPhotos(ITEMS);
assert.strictEqual(flat.length, 3, "one entry per photo across all messages");
assert.deepStrictEqual(
  flat.map((f) => f.photo.id),
  ["a.jpg", "b.jpg", "c.jpg"],
  "photos flatten in message render order",
);
// The photo-less message must not consume an index — otherwise every
// data-idx after it points at the wrong photo.
assert.deepStrictEqual(flat.map((f) => f.msgIdx), [0, 0, 2], "msgIdx tracks the owning message");
assert.strictEqual(flat[0].caption, "Person detected", "caption comes from the owning message title");

assert.deepStrictEqual(flattenPhotos([]), [], "no messages → no photos");
assert.deepStrictEqual(flattenPhotos(null), [], "null items tolerated");
assert.deepStrictEqual(
  flattenPhotos([{ title: "x", photos: "not-an-array" }]),
  [],
  "non-array photos tolerated (never throws on a bad payload)",
);

// --- (b) renderMessagesHtml ----------------------------------------------

const html = renderMessagesHtml(ITEMS);
const imgCount = (html.match(/<img/g) || []).length;
assert.strictEqual(imgCount, 3, "one <img> per photo");
assert.ok(html.includes('data-idx="0"'), "thumbs carry a data-idx");
assert.ok(html.includes('data-idx="2"'), "the last photo's idx is the FLAT index, not a per-message one");
assert.ok(html.includes("/t/a.jpg"), "thumb uses thumb_url");
assert.ok(html.includes("Charging"), "body rendered");

// Untrusted text: titles/bodies come from the cloud message store. The
// property is that no injected text survives as a LIVE tag — an escaped
// `onerror=` sitting inside &lt;…&gt; is inert text, so assert on the
// tag-opening `<`, not on the payload substring.
const nasty = renderMessagesHtml([
  { title: '<img src=x onerror="alert(1)">', body: "<script>bad()</script>", date: "" },
]);
assert.ok(!nasty.includes("<img src=x"), "title cannot open a live tag");
assert.ok(!nasty.includes("<script>"), "body cannot open a live tag");
assert.ok(nasty.includes("&lt;script&gt;"), "escaped body still readable");
// The only <img> tags present are the card's own thumbs — this message has none.
assert.strictEqual((nasty.match(/<img/g) || []).length, 0, "no <img> from an injected title");

// A malicious thumb_url must not break out of the src attribute.
const nastyUrl = renderMessagesHtml([
  { title: "t", photos: [{ id: "x", thumb_url: '" onerror="alert(1)', url: "u", detections: [] }] },
]);
assert.ok(!/src="[^"]*"\s+onerror/.test(nastyUrl), "thumb_url cannot escape the src attribute");
assert.ok(nastyUrl.includes("&quot;"), "the injected quote is entity-escaped");

const empty = renderMessagesHtml([]);
assert.ok(empty.length > 0 && /no messages/i.test(empty), "empty list says why, never blank");

// A photo with no URL must not render an <img src="">. The persisted store now
// holds photo IDENTITY only (no signed URL), so a restored message can legitimately
// carry a URL-less photo for the instant before the re-link runs — and if the
// photo archive read fails, permanently. An empty src makes the browser re-request
// the PAGE url as an image: a guaranteed broken thumbnail.
const noUrl = renderMessagesHtml([
  { title: "Person detected", date: "2026-07-16T10:00:00Z",
    photos: [{ id: "a.jpg", ts: 1, category: "ai_human", detections: [] }] },
]);
assert.strictEqual((noUrl.match(/<img/g) || []).length, 0, "a URL-less photo renders no <img>");
assert.ok(/Person detected/.test(noUrl), "the message itself still renders");
// flattenPhotos must drop it too, or data-idx would point past the rendered thumbs.
assert.strictEqual(
  flattenPhotos([{ title: "x", photos: [{ id: "a.jpg" }, PHOTO_A] }]).length,
  1,
  "flattenPhotos drops URL-less photos so data-idx stays aligned with the <img>s",
);

// --- (c) renderKey: when must the card re-render? -------------------------
// `set hass` fires on every state update, so the card skips re-rendering when
// the key is unchanged. The trap: snapshot photos are linked to an EXISTING
// message later (link_message_snapshot_photos runs on each device-message
// merge, matching against the hourly OSS gallery sync). That changes neither
// the message count nor the newest id — so a count+id key would leave the
// thumbnails permanently invisible until an unrelated new message arrived.

const NO_PHOTOS = [{ id: "m1", title: "Person detected", date: "2026-07-16T10:00:00Z" }];
const LINKED_LATER = [
  { id: "m1", title: "Person detected", date: "2026-07-16T10:00:00Z", photos: [PHOTO_A] },
];
assert.notStrictEqual(
  renderKey(NO_PHOTOS),
  renderKey(LINKED_LATER),
  "photos linked onto an existing message MUST invalidate the key",
);
assert.strictEqual(renderKey(NO_PHOTOS), renderKey(NO_PHOTOS), "key is stable for identical items");

// A RE-SIGN must re-render. The backend re-mints signed photo URLs on every
// merge and on restore (HA's sign secret is per-process, so a restart
// invalidates the old ones — see domain/notifications.py:strip_signed_urls).
// Count and id are unchanged by a re-sign, so a key that ignored the URL would
// leave the browser rendering dead signatures -> 401 thumbnails, forever.
const SIGNED_OLD = [
  { id: "m1", title: "t", date: "2026-07-16T10:00:00Z",
    photos: [{ ...PHOTO_A, url: "/api/p/a.jpg?authSig=OLD", thumb_url: "/api/p/a.jpg?authSig=OLD" }] },
];
const SIGNED_NEW = [
  { id: "m1", title: "t", date: "2026-07-16T10:00:00Z",
    photos: [{ ...PHOTO_A, url: "/api/p/a.jpg?authSig=NEW", thumb_url: "/api/p/a.jpg?authSig=NEW" }] },
];
assert.notStrictEqual(
  renderKey(SIGNED_OLD),
  renderKey(SIGNED_NEW),
  "a re-signed photo URL MUST invalidate the key",
);
assert.notStrictEqual(
  renderKey(NO_PHOTOS),
  renderKey([{ id: "m2", title: "New", date: "2026-07-16T11:00:00Z" }, ...NO_PHOTOS]),
  "a new message invalidates the key",
);
assert.strictEqual(renderKey([]), renderKey([]), "empty list key is stable");

console.log("OK");
