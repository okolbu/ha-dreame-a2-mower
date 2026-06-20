// Schedule-card modal-persistence harness for dreame-a2-schedule-card.js.
//
// Bug: `set hass` re-renders the whole shadow DOM on EVERY hass update
// (Lovelace reassigns `hass` to every card on any entity change). While the
// add/edit modal is open that blew away its live DOM — the <input type=time>
// value, the day-toggle `.on` state + `mask` accumulator, and focus — so time
// edits wouldn't stick and the day/Cancel buttons felt "deselected right away".
//
// The fix: while a modal is open, keep the latest state for the eventual save
// but DO NOT re-render. This harness drives the real `set hass` setter and
// asserts _render is not invoked while the modal is open.
//
// Per feedback_frontend_card_verification: `node --check` only catches syntax;
// this runs the REAL setter logic against a minimal stub.

const stubEl = () => ({
  addEventListener() {},
  classList: { contains: () => false, add() {}, remove() {} },
  dataset: {},
});
globalThis.HTMLElement = class {
  attachShadow() {
    // Minimal DOM stub: _render wires listeners on queried nodes, so
    // querySelector must return an element and querySelectorAll an iterable.
    this.shadowRoot = {
      innerHTML: "",
      querySelector: () => stubEl(),
      querySelectorAll: () => [],
    };
    return this.shadowRoot;
  }
};
let CardClass = null;
globalThis.customElements = {
  get: () => false,
  define: (_name, cls) => { CardClass = cls; },
};
globalThis.window = {};
globalThis.console = console;

await import("../../custom_components/dreame_a2_mower/www/dreame-a2-schedule-card.js");
if (!CardClass) throw new Error("failed to capture DreameA2ScheduleCard class");

const SENSOR = "sensor.dreame_a2_mower_schedule_count";

function makeState() {
  // A fresh object reference each call models HA handing the card a new state.
  return {
    attributes: {
      slots: [
        { slot_id: 0, name: "Spr & Sum Schedule", enabled: true, plans: [] },
        { slot_id: 1, name: "Aut & Win Schedule", enabled: false, plans: [] },
      ],
    },
  };
}
function makeHass(state) {
  return {
    states: { [SENSOR]: state, "lawn_mower.dreame_a2_mower": { state: "docked" } },
    callService: async () => {},
  };
}

const card = new CardClass();
card.setConfig({});

// Count real renders by wrapping (don't replace — we still want the modal HTML
// produced once so _modal is set when we open it).
let renderCount = 0;
const realRender = card._render.bind(card);
card._render = (s) => { renderCount += 1; realRender(s); };

// 1) First hass: no modal -> initial render.
const stateA = makeState();
card.hass = makeHass(stateA);
const afterFirst = renderCount;

// 2) Open the add modal (a user action -> one render).
card._openAddModal();
const afterOpen = renderCount;
const modalOpen = !!card._modal;

// 3) A hass update arrives with the SAME state object (e.g. some OTHER entity
//    changed; this sensor did not). Modal must survive: NO re-render.
card.hass = makeHass(stateA);
const afterSameRef = renderCount;

// 4) A hass update with a NEW state object (this sensor genuinely changed).
//    Still must NOT re-render while the modal is open, but the card must keep
//    the latest state for the eventual save.
const stateB = makeState();
card.hass = makeHass(stateB);
const afterNewRef = renderCount;
const stateRefIsFresh = card._stateRef === stateB;
const modalStillOpen = !!card._modal;

// 5) Close the modal; hass updates resume re-rendering.
card._modal = null;
const stateC = makeState();
card.hass = makeHass(stateC);
const afterClose = renderCount;

process.stdout.write(JSON.stringify({
  afterFirst,
  afterOpen,
  modalOpen,
  afterSameRef,
  afterNewRef,
  stateRefIsFresh,
  modalStillOpen,
  afterClose,
}));
