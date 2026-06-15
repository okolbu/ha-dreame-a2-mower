// Decorative-shape render harness for dreame-map-editor-card.js.
//
// The card draws a server-rendered decorative no-go shape (heart, shapeType 13)
// as a faint dashed bbox <rect class="obj-decorative"> hit-area — NOT a 2-point
// <polygon> ("phantom no-go line"). Standard zones (line shapeType 1, polygon
// shapeType 2) keep their normal <polygon> overlays. This harness executes the
// REAL _effectiveObjects + _renderObjects (+ _draftFromObject / _renderDraft for
// the decorative select->delete draft) against a minimal DOM stub and emits the
// produced SVG markup as JSON for the Python gate (test_map_editor_decorative).
//
// Per feedback_frontend_card_verification: `node --check` only catches syntax;
// this runs the render functions so a logic regression (line vs rect) is caught.

// ---- minimal DOM / custom-element stubs (the card extends HTMLElement and, at
// import time, calls customElements.get + console.info). None of the render
// methods we exercise touch a real DOM beyond shadowRoot.getElementById(...).innerHTML.
globalThis.HTMLElement = class {};
let CardClass = null;
globalThis.customElements = {
  get: () => false, // make the card's `if (!get(...))` guard run define()
  define: (_name, cls) => { CardClass = cls; },
};
globalThis.document = { createElement: () => ({ addEventListener() {}, appendChild() {} }) };
globalThis.window = {};

await import("../../custom_components/dreame_a2_mower/www/dreame-map-editor-card.js");
if (!CardClass) throw new Error("failed to capture DreameMapEditorCard class");

// Projection (matches the parity harness shape).
const proj = {
  bx1_mm: 1000, by1_mm: -2000, bx2_mm: 21000, by2_mm: 19000,
  pixel_size_mm: 50, width_px: 400, height_px: 420,
};

// A fake <g> element: we only read/write innerHTML.
function fakeG() { return { innerHTML: "" }; }

const card = new CardClass();
const gObjects = fakeG();
const gDraft = fakeG();
card.shadowRoot = {
  getElementById: (id) => (id === "objects" ? gObjects : id === "draft" ? gDraft : null),
  querySelectorAll: () => [],
};
card._proj = proj;
card._overrides = {};
card._provisional = [];
card._draft = null;

// Synthetic editable_objects: a heart (decorative, shapeType 13, 2 bbox pts),
// a real no-go line (shapeType 1, 2 pts), a no-go polygon (shapeType 2, 4 pts).
const heart = {
  id: 101, kind: "heart", shape_type: 13,
  points_m: [[5.0, 5.0], [9.0, 8.0]], radius: 0,
};
const line = {
  id: 102, kind: "nogo", shape_type: 1,
  points_m: [[2.0, 2.0], [4.0, 6.0]], radius: 0,
};
const poly = {
  id: 103, kind: "nogo", shape_type: 2,
  points_m: [[10.0, 10.0], [12.0, 10.0], [12.0, 13.0], [10.0, 13.0]], radius: 0,
};
const objs = [heart, line, poly];
card._objs = objs;

// 1) shape_type survives _effectiveObjects.
const eff = card._effectiveObjects(objs);
const effShapeTypes = eff.map((o) => o.shape_type);

// 2) _renderObjects markup.
card._renderObjects(objs);
const objectsHtml = gObjects.innerHTML;

// 3) Select the heart -> decorative delete-only draft + its render.
const heartDraft = card._draftFromObject(heart);
card._draft = heartDraft;
card._renderDraft();
const draftHtml = gDraft.innerHTML;

process.stdout.write(JSON.stringify({
  effShapeTypes,
  objectsHtml,
  heartDraft: {
    model: heartDraft.model,
    objectId: heartDraft.objectId,
    kind: heartDraft.kind,
    category: heartDraft.category,
    nPts: (heartDraft.pts || []).length,
  },
  draftHtml,
}));
