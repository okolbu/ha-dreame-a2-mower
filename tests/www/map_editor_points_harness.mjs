// Spot + maintenance-point render/save harness for dreame-map-editor-card.js.
//
// Spots (o=214, kind "spot", 4 points_m) render as <polygon class="obj obj-spot">.
// Maintenance points (o=224, kind "maintenance", point_m [x,y]) render as a
// MARKER (<g class="obj obj-maint"> with a circle + crosshair), NOT a polygon
// line. A NEW point-model draft (the maintenance create tool) saves via the
// create_maintenance_point service with flat (x, y) + heading 0.
//
// Per feedback_frontend_card_verification: `node --check` only catches syntax;
// this runs the REAL render + submit functions against a minimal DOM stub.

globalThis.HTMLElement = class {};
let CardClass = null;
globalThis.customElements = {
  get: () => false,
  define: (_name, cls) => { CardClass = cls; },
};
globalThis.document = { createElement: () => ({ addEventListener() {}, appendChild() {} }) };
globalThis.window = {};

await import("../../custom_components/dreame_a2_mower/www/dreame-map-editor-card.js");
if (!CardClass) throw new Error("failed to capture DreameMapEditorCard class");

const proj = {
  bx1_mm: 1000, by1_mm: -2000, bx2_mm: 21000, by2_mm: 19000,
  pixel_size_mm: 50, width_px: 400, height_px: 420,
};

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
card._editMapId = 0;
// Neuter DOM-touching UI helpers (no toolbar/buttons in this stub).
card._setBusy = () => {};
card._setMsg = () => {};
card._syncActionButtons = () => {};

// Capture service calls.
const calls = [];
card._hass = {
  callService: async (domain, service, data) => { calls.push({ domain, service, data }); },
};

// Synthetic editable_objects: a spot (4 corners) + a maintenance point.
const spot = {
  id: 201, kind: "spot", op: 214, type: 1, shape_type: null,
  points_m: [[5.0, 5.0], [9.0, 5.0], [9.0, 8.0], [5.0, 8.0]], radius: 0,
};
const maint = {
  id: 301, kind: "maintenance", op: 224, type: 3,
  point_m: [3.0, -1.0],
};
const objs = [spot, maint];
card._objs = objs;

// 1) _renderObjects markup.
card._renderObjects(objs);
const objectsHtml = gObjects.innerHTML;

// 2) Build a draft from the existing maintenance point -> point model.
const maintDraft = card._draftFromObject(maint);
// 3) Build a draft from the existing spot -> corners/rect model.
const spotDraft = card._draftFromObject(spot);

// 4) Render the maintenance-point draft -> marker + delete handle (no resize).
card._draft = maintDraft;
card._renderDraft();
const maintDraftHtml = gDraft.innerHTML;

// 5) A FRESH point-model create draft saves via create_maintenance_point.
const maintTool = { save: { category: "maintenance", shape: "point" }, model: "point" };
const newDraft = card._makeDraft(maintTool, [120, 130]);
card._draft = newDraft;
await card._onSubmit();
const maintCreateCall = calls.find((c) => c.service === "create_maintenance_point");

// 6) A fresh spot-rect create draft saves via create_spot (4 corners).
calls.length = 0;
card._draft = null;
card._provisional = [];
const spotTool = { save: { category: "spot", shape: "rect" }, model: "corners", resize: "rect" };
const newSpot = card._makeDraft(spotTool, [200, 210]);
card._draft = newSpot;
await card._onSubmit();
const spotCreateCall = calls.find((c) => c.service === "create_spot");

// 7) Delete categories for an existing spot + maintenance.
calls.length = 0;
await card._deleteExisting(spotDraft);
await card._deleteExisting(maintDraft);
const deleteCalls = calls.filter((c) => c.service === "delete_map_object").map((c) => c.data.category);

process.stdout.write(JSON.stringify({
  objectsHtml,
  maintDraft: {
    model: maintDraft.model,
    objectId: maintDraft.objectId,
    kind: maintDraft.kind,
    category: maintDraft.category,
    nPts: (maintDraft.pts || []).length,
  },
  spotDraft: {
    model: spotDraft.model,
    objectId: spotDraft.objectId,
    kind: spotDraft.kind,
    category: spotDraft.category,
    nPts: (spotDraft.pts || []).length,
  },
  maintDraftHtml,
  maintCreateCall,
  spotCreateCall,
  deleteCalls,
}));
