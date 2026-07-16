// Card-hygiene harness (R-54 / P5.2). Exercises the LOGIC that `node --check`
// can't: the shared _dreame-card-core.js contract + each card's missing-entity
// path. Cards render in a browser (customElements + real DOM); this runs the
// pure control-flow against a minimal DOM stub, per
// feedback_frontend_card_verification ("node --check only catches syntax").
//
// Asserts:
//   (a) defineCard is GUARDED — a second define of the same tag is a no-op that
//       returns false and does NOT throw (whereas the raw customElements.define
//       WOULD throw, proving the guard is load-bearing — T6-8).
//   (b) renderMissingEntity returns a non-empty placeholder naming the entity
//       (T6-20).
//   (c) no entity-path card throws when handed a hass with no dreame entities,
//       and each renders a non-empty missing/waiting placeholder into its shadow
//       root (T6-20) — no more silent blank cards.
//
// NOTE: the LiDAR card is WebGL/canvas-driven and cannot instantiate in node;
// it is import-checked (so its module-level defineCard runs + is guard-tested)
// but not instantiated. Its visual render stays a P5.5 live eyeball.

import assert from "node:assert";

// ---- minimal DOM stub -----------------------------------------------------

function makeEl() {
  const el = {
    textContent: "",
    innerHTML: "",
    value: "",
    disabled: false,
    style: {},
    dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    addEventListener() {},
    removeEventListener() {},
    appendChild() {},
    removeChild() {},
    setAttribute() {},
    getAttribute: () => null,
    querySelector: () => makeEl(),
    querySelectorAll: () => [],
    remove() {},
    get parentNode() {
      return null;
    },
  };
  return el;
}

function makeShadowRoot() {
  return {
    innerHTML: "",
    getElementById: () => null,
    querySelector: () => makeEl(),
    querySelectorAll: () => [],
    appendChild() {},
  };
}

globalThis.HTMLElement = class {
  attachShadow() {
    this.shadowRoot = makeShadowRoot();
    return this.shadowRoot;
  }
};

globalThis.document = {
  createElement: () => makeEl(),
  addEventListener() {},
  removeEventListener() {},
  body: { appendChild() {} },
  documentElement: { appendChild() {} },
};

const _defined = {};
globalThis.customElements = {
  get: (n) => _defined[n],
  define: (n, cls) => {
    // Model the real browser: a duplicate define throws.
    if (_defined[n]) throw new Error(`'${n}' has already been defined`);
    _defined[n] = cls;
  },
};

const _ls = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.window = { customCards: [], localStorage: _ls };
globalThis.localStorage = _ls;
globalThis.performance = { now: () => 0 };
globalThis.console = console;

// ---- imports (each card runs its module-level defineCard here) -------------

const CORE = "../../custom_components/dreame_a2_mower/www/_dreame-card-core.js";
const { defineCard, renderMissingEntity, fingerprint, shouldRender } = await import(CORE);

await import("../../custom_components/dreame_a2_mower/www/dreame-mower-map-card.js");
await import("../../custom_components/dreame_a2_mower/www/dreame-map-editor-card.js");
await import("../../custom_components/dreame_a2_mower/www/dreame-a2-photo-gallery-card.js");
await import("../../custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js");
await import("../../custom_components/dreame_a2_mower/www/dreame-a2-schedule-card.js");
await import("../../custom_components/dreame_a2_mower/www/dreame-multi-select-card.js");
await import("../../custom_components/dreame_a2_mower/www/dreame-a2-device-messages-card.js");
await import("../../custom_components/dreame_a2_mower/www/dreame-a2-session-calendar.js");
await import("../../custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js");

const TAGS = [
  "dreame-mower-map-card",
  "dreame-map-editor-card",
  "dreame-a2-photo-gallery-card",
  "dreame-mower-replay-card",
  "dreame-a2-schedule-card",
  "dreame-multi-select-card",
  "dreame-a2-device-messages-card",
  "dreame-a2-session-calendar",
  "dreame-a2-lidar-card",
];

// ---- (a) guarded define ---------------------------------------------------

for (const tag of TAGS) {
  assert.ok(customElements.get(tag), `${tag} registered on import`);
  // Raw re-define WOULD throw — proves the guard is load-bearing.
  assert.throws(
    () => customElements.define(tag, class {}),
    /already been defined/,
    `raw re-define of ${tag} should throw`,
  );
  // defineCard swallows it (guard): returns false, no throw.
  let ret;
  assert.doesNotThrow(() => {
    ret = defineCard(tag, class {}, { name: "x", version: "9.9.9" });
  }, `defineCard(${tag}) must not throw on double-register`);
  assert.strictEqual(ret, false, `defineCard(${tag}) returns false when already defined`);
}

// ---- (b) renderMissingEntity ---------------------------------------------

const missing = renderMissingEntity("sensor.dreame_a2_mower_nope");
assert.ok(missing && missing.length > 0, "renderMissingEntity non-empty");
assert.ok(missing.includes("sensor.dreame_a2_mower_nope"), "names the entity");
assert.ok(missing.includes("ha-card"), "wraps in ha-card");
const waiting = renderMissingEntity("camera.x", { waiting: true });
assert.ok(waiting.includes("Waiting"), "waiting variant reads 'Waiting'");
// Empty / undefined entity id must not blow up.
assert.ok(renderMissingEntity().length > 0, "renderMissingEntity() with no id still renders");

// ---- (c) no card throws on a hass with no dreame entities -----------------

const EMPTY_HASS = { states: {}, callService() {}, auth: { data: {} } };

async function instantiate(tag, setup) {
  const cls = customElements.get(tag);
  const card = new cls();
  setup(card);
  assert.doesNotThrow(() => {
    card.hass = EMPTY_HASS;
  }, `${tag} threw on empty-hass set`);
  return card;
}

const map = await instantiate("dreame-mower-map-card", (c) =>
  c.setConfig({ entity: "camera.dreame_a2_mower_map" }),
);
assert.ok(
  map.shadowRoot && map.shadowRoot.innerHTML.includes("ha-card"),
  "map card renders a placeholder (not blank)",
);

const editor = await instantiate("dreame-map-editor-card", (c) =>
  c.setConfig({ entity: "camera.dreame_a2_mower_map" }),
);
assert.ok(
  editor.shadowRoot && editor.shadowRoot.innerHTML.includes("ha-card"),
  "editor card renders a placeholder (not blank)",
);

const gallery = await instantiate("dreame-a2-photo-gallery-card", (c) => c.setConfig({}));
assert.ok(
  gallery.shadowRoot && gallery.shadowRoot.innerHTML.includes("ha-card"),
  "gallery card renders a placeholder (not blank)",
);

const replay = await instantiate("dreame-mower-replay-card", (c) =>
  c.setConfig({ entity: "sensor.dreame_a2_mower_picked_session" }),
);
assert.ok(
  replay.shadowRoot && replay.shadowRoot.innerHTML.includes("ha-card"),
  "replay card renders a placeholder (not blank)",
);

const messages = await instantiate("dreame-a2-device-messages-card", (c) => c.setConfig({}));
assert.ok(
  messages.shadowRoot && messages.shadowRoot.innerHTML.includes("ha-card"),
  "device-messages card renders a placeholder (not blank)",
);

const sesscal = await instantiate("dreame-a2-session-calendar", (c) => c.setConfig({}));
assert.ok(
  sesscal.shadowRoot && sesscal.shadowRoot.innerHTML.includes("ha-card"),
  "session-calendar card renders a placeholder (not blank)",
);

const schedule = await instantiate("dreame-a2-schedule-card", (c) => c.setConfig({}));
assert.ok(
  schedule.shadowRoot && schedule.shadowRoot.innerHTML.includes("ha-card"),
  "schedule card renders a placeholder (not blank)",
);

// Multi-select renders its (empty) list scaffold rather than a missing-entity
// placeholder, but the contract is the same: no throw, non-empty shadow DOM.
const multi = await instantiate("dreame-multi-select-card", (c) =>
  c.setConfig({ entity: "sensor.x", service: "dreame_a2_mower.start_edge_patrol" }),
);
assert.ok(
  multi.shadowRoot && multi.shadowRoot.innerHTML.length > 0,
  "multi-select renders into shadow DOM (T6-19)",
);
// T6-19: it must NOT touch light DOM (the card never assigns this.innerHTML;
// the stub leaves it undefined, a real browser leaves it "").
assert.ok(!multi.innerHTML, "multi-select does not write light DOM");

// ---- (d) the shared re-render guard (T6-21) -------------------------------
// Three cards independently reinvented "should I re-render?", and two got it
// wrong in opposite directions: the session-calendar had NO guard and rebuilt
// its buttons on every hass tick (destroying the chip mid-click — "needs more
// than one click"), while the photo-gallery's guard was too NARROW (length+id)
// and never noticed a re-signed URL, leaving the browser on dead signatures.
// Both are the same question, so the primitive lives here now.

// fingerprint: by VALUE, because Lovelace hands every card a fresh `hass` each
// tick — identity would never match and would re-render forever.
assert.strictEqual(fingerprint("a", 1), fingerprint("a", 1), "same values -> same key");
assert.notStrictEqual(fingerprint("a", 1), fingerprint("a", 2), "different values -> different key");
assert.strictEqual(fingerprint(["a", "b"]), fingerprint(["a", "b"]), "arrays compare by value");
assert.strictEqual(fingerprint(null), fingerprint(null), "null tolerated");
assert.strictEqual(fingerprint(undefined), fingerprint(null), "null and undefined both read as absent");
// Ambiguity: these must NOT collide, or a card renders stale content.
assert.notStrictEqual(fingerprint(["a", "b"]), fingerprint(["ab"]), "no join ambiguity");
assert.notStrictEqual(fingerprint(["a"], ["b"]), fingerprint(["a", "b"]), "array boundaries are significant");
assert.notStrictEqual(fingerprint("1"), fingerprint(1), "type is significant (a string 1 is not the number 1)");

// shouldRender: true on change, false on repeat; stores the key on the owner.
const owner = {};
assert.strictEqual(shouldRender(owner, "k1"), true, "first call always renders");
assert.strictEqual(shouldRender(owner, "k1"), false, "repeat key must NOT re-render (this is what eats clicks)");
assert.strictEqual(shouldRender(owner, "k2"), true, "changed key renders");
assert.strictEqual(shouldRender(owner, "k2"), false, "and then settles");
// Two cards must not share state through the helper.
const o2 = {};
assert.strictEqual(shouldRender(o2, "k2"), true, "keys are per-owner, not global");
// Identity keys work too — that's the schedule card's pattern (an HA state
// object is replaced only when the entity actually changes).
const stateA = { s: 1 }, stateB = { s: 1 };
const o3 = {};
assert.strictEqual(shouldRender(o3, stateA), true);
assert.strictEqual(shouldRender(o3, stateA), false, "same state object -> no re-render");
assert.strictEqual(shouldRender(o3, stateB), true, "a new state object -> re-render");
// A falsy-but-real key must still be honoured (not treated as "no key yet").
const o4 = {};
assert.strictEqual(shouldRender(o4, ""), true, "empty-string key renders once");
assert.strictEqual(shouldRender(o4, ""), false, "...then settles");

// ---- (e) the gallery's key must notice a re-signed URL (T6-21) ------------
// Same bug class as the device-messages card, latent here: the gallery keyed on
// `length + items[0].id`, so an hourly re-sign / post-restart re-mint changed
// every URL while the key stayed identical — the card never re-rendered and the
// browser kept requesting signatures minted by a dead HA process (401). It
// looked fine only because a page loaded AFTER a restart gets fresh URLs.
const { galleryKey } = await import(
  "../../custom_components/dreame_a2_mower/www/dreame-a2-photo-gallery-card.js"
);
const G_OLD = [{ id: "a.jpg", url: "/p/a.jpg?authSig=OLD", thumb_url: "/t/a.jpg?authSig=OLD" }];
const G_NEW = [{ id: "a.jpg", url: "/p/a.jpg?authSig=NEW", thumb_url: "/t/a.jpg?authSig=NEW" }];
assert.strictEqual(galleryKey(G_OLD), galleryKey(G_OLD), "stable for identical items");
assert.notStrictEqual(
  galleryKey(G_OLD),
  galleryKey(G_NEW),
  "a re-signed gallery URL MUST invalidate the key (else the browser 401s forever)",
);
assert.notStrictEqual(galleryKey(G_OLD), galleryKey([]), "an emptied gallery re-renders");
assert.strictEqual(galleryKey([]), galleryKey([]), "empty is stable");
assert.strictEqual(galleryKey(null), galleryKey(null), "null tolerated");

console.log("OK");
