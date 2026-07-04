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
const { defineCard, renderMissingEntity } = await import(CORE);

await import("../../custom_components/dreame_a2_mower/www/dreame-mower-map-card.js");
await import("../../custom_components/dreame_a2_mower/www/dreame-map-editor-card.js");
await import("../../custom_components/dreame_a2_mower/www/dreame-a2-photo-gallery-card.js");
await import("../../custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js");
await import("../../custom_components/dreame_a2_mower/www/dreame-a2-schedule-card.js");
await import("../../custom_components/dreame_a2_mower/www/dreame-multi-select-card.js");
await import("../../custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js");

const TAGS = [
  "dreame-mower-map-card",
  "dreame-map-editor-card",
  "dreame-a2-photo-gallery-card",
  "dreame-mower-replay-card",
  "dreame-a2-schedule-card",
  "dreame-multi-select-card",
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

console.log("OK");
