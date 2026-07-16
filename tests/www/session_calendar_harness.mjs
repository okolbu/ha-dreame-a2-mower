// Session-calendar card harness — the pure grid/label logic.
//
// The card's value is one-tap replay: tapping a session on the month grid must
// select EXACTLY the option the replay picker offers. These tests pin the two
// ways that can silently break: date bucketing (an event landing on the wrong
// day cell) and label matching (a tap that fires select_option with a label the
// select doesn't have, which raises in HA).

import assert from "node:assert";

function _shadow() {
  return {
    innerHTML: "",
    getElementById: () => ({ set onclick(_v) {} }),
    querySelectorAll: () => [],
  };
}
globalThis.HTMLElement = class {
  attachShadow() {
    this.shadowRoot = _shadow();
    return this.shadowRoot;
  }
};
const _defined = {};
globalThis.customElements = { get: (n) => _defined[n], define: (n, c) => { _defined[n] = c; } };
globalThis.window = { customCards: [] };

const CARD =
  "../../custom_components/dreame_a2_mower/www/dreame-a2-session-calendar.js";
const { buildMonthMatrix, labelDate, groupByDay, replayableSet, calendarKey } = await import(CARD);

// --- labelDate ------------------------------------------------------------
// Labels come from domain/session/replay.py:format_session_label. The shape is
// `[Tag] [Map N] YYYY-MM-DD HH:MM …` for every session type; the tag and the
// tail vary, the timestamp position does not.

assert.strictEqual(
  labelDate("[Mowing] [Map 1] 2026-07-16 10:30 — 120.5 m² / 45min"),
  "2026-07-16",
  "mow label",
);
assert.strictEqual(
  labelDate("[Patrol] [Map 2] 2026-07-04 08:05 — Edge / 12min"),
  "2026-07-04",
  "patrol label",
);
assert.strictEqual(
  labelDate("[To Point] [Map ?] 2026-01-02 23:59 (blocked)"),
  "2026-01-02",
  "to-point label with unknown map + outcome suffix",
);
assert.strictEqual(labelDate("[Manual] [Map 1] 2026-12-31 00:00"), "2026-12-31", "manual label");
// format_session_label falls back to "??" when the timestamp is unparseable.
assert.strictEqual(labelDate("[Mowing] [Map 1] ?? — 1.0 m² / 1min"), null, "?? timestamp -> null");
assert.strictEqual(labelDate(""), null, "empty -> null");
assert.strictEqual(labelDate(null), null, "null -> null");

// --- buildMonthMatrix -----------------------------------------------------
// Weeks start Monday. Cells outside the month are still rendered (greyed) so
// the grid is always a rectangle.

const july2026 = buildMonthMatrix(2026, 6); // monthIndex 6 = July
assert.ok(july2026.length >= 4 && july2026.length <= 6, "a month spans 4-6 week rows");
for (const week of july2026) assert.strictEqual(week.length, 7, "every row has 7 days");
const flat = july2026.flat();
const inMonth = flat.filter((d) => d.inMonth);
assert.strictEqual(inMonth.length, 31, "July has 31 in-month days");
assert.strictEqual(inMonth[0].key, "2026-07-01", "first in-month day");
assert.strictEqual(inMonth[30].key, "2026-07-31", "last in-month day");
// 2026-07-01 is a Wednesday -> Monday-start grid puts it in column 2.
assert.strictEqual(july2026[0][2].key, "2026-07-01", "month starts in the right column");
assert.strictEqual(july2026[0][0].inMonth, false, "leading cells are out-of-month");

// February in a leap year — the classic off-by-one.
const feb2028 = buildMonthMatrix(2028, 1);
assert.strictEqual(feb2028.flat().filter((d) => d.inMonth).length, 29, "Feb 2028 has 29 days");
const feb2027 = buildMonthMatrix(2027, 1);
assert.strictEqual(feb2027.flat().filter((d) => d.inMonth).length, 28, "Feb 2027 has 28 days");
// Year boundary: December must not bleed into the wrong year.
const dec2026 = buildMonthMatrix(2026, 11);
assert.strictEqual(
  dec2026.flat().filter((d) => d.inMonth).slice(-1)[0].key,
  "2026-12-31",
  "December ends on the 31st",
);

// --- groupByDay -----------------------------------------------------------

const EVENTS = [
  { summary: "[Mowing] [Map 1] 2026-07-16 10:30 — 120.5 m² / 45min" },
  { summary: "[Patrol] [Map 1] 2026-07-16 18:00 — Edge / 12min" },
  { summary: "[Mowing] [Map 1] 2026-07-02 09:00 — 90.0 m² / 30min" },
];
const byDay = groupByDay(EVENTS);
assert.strictEqual(byDay["2026-07-16"].length, 2, "two sessions on the 16th");
assert.strictEqual(byDay["2026-07-02"].length, 1, "one session on the 2nd");
assert.deepStrictEqual(Object.keys(byDay).sort(), ["2026-07-02", "2026-07-16"]);
// The grid buckets by the LABEL's date, not the event's UTC start: the label is
// what the picker and the Dreame app both show, so a session must appear under
// the day its label names (they diverge either side of midnight in a non-UTC TZ).
assert.deepStrictEqual(groupByDay([]), {}, "no events -> empty");
assert.deepStrictEqual(groupByDay(null), {}, "null tolerated");
assert.deepStrictEqual(
  groupByDay([{ summary: "[Mowing] [Map 1] ?? — 1 m² / 1min" }]),
  {},
  "an unparseable label is dropped, not bucketed under a bogus day",
);

// --- replayableSet --------------------------------------------------------
// The replay select is CAPPED at the 50 most recent sessions
// (entities/select/global_.py:_max_options), but the calendar carries every
// archived session. Tapping an older one would call select_option with a label
// that isn't an option — HA raises. The card must know which are actionable.

const OPTIONS = [
  "[Mowing] [Map 1] 2026-07-16 10:30 — 120.5 m² / 45min",
  "[Patrol] [Map 1] 2026-07-16 18:00 — Edge / 12min",
];
const set = replayableSet(OPTIONS);
assert.ok(set.has(EVENTS[0].summary), "recent session is replayable");
assert.ok(!set.has(EVENTS[2].summary), "a session beyond the select's cap is NOT replayable");
assert.strictEqual(replayableSet(null).size, 0, "null options -> empty set (nothing tappable)");
// The placeholder is not a session and must never be tappable.
assert.ok(!replayableSet(["(no sessions)"]).has(EVENTS[0].summary));

// --- re-render guard ------------------------------------------------------
// HA sets `hass` on EVERY state change anywhere in the system. `_render()`
// rebuilds shadowRoot.innerHTML, destroying every chip button — so a re-render
// landing between mousedown and mouseup swallows the click (the element that
// received mousedown no longer exists, so no click event fires). Symptom: "it
// usually takes more than one click to start a session". The card must only
// re-render when something it DISPLAYS actually changed.

const EV = [{ summary: "[Mowing] [Map 1] 2026-07-16 10:30 — 120.5 m² / 45min" }];
const OPT = ["[Mowing] [Map 1] 2026-07-16 10:30 — 120.5 m² / 45min"];

assert.strictEqual(
  calendarKey(2026, 6, EV, OPT),
  calendarKey(2026, 6, EV, OPT),
  "identical state must produce an identical key (no re-render, no lost clicks)",
);
// A different hass object with equal content must NOT force a re-render.
assert.strictEqual(
  calendarKey(2026, 6, [{ ...EV[0] }], [...OPT]),
  calendarKey(2026, 6, EV, OPT),
  "key is by VALUE, not object identity — hass hands us a new object each tick",
);

// The things that MUST re-render:
assert.notStrictEqual(calendarKey(2026, 6, EV, OPT), calendarKey(2026, 7, EV, OPT), "month change");
assert.notStrictEqual(calendarKey(2026, 6, EV, OPT), calendarKey(2027, 6, EV, OPT), "year change");
assert.notStrictEqual(
  calendarKey(2026, 6, EV, OPT),
  calendarKey(2026, 6, [...EV, { summary: "[Patrol] [Map 1] 2026-07-17 08:00 — Edge / 5min" }], OPT),
  "a new session must appear",
);
// The options list drives which chips are tappable — a session ageing out of
// the picker's 50-session window must grey its chip out.
assert.notStrictEqual(
  calendarKey(2026, 6, EV, OPT),
  calendarKey(2026, 6, EV, []),
  "replayable-options change must re-render",
);
assert.strictEqual(calendarKey(2026, 6, [], []), calendarKey(2026, 6, [], []), "empty is stable");
assert.strictEqual(calendarKey(2026, 6, null, null), calendarKey(2026, 6, null, null), "null tolerated");


// --- the guard, wired: a repeat hass tick must not rebuild the DOM ----------
// This is the user-visible bug ("usually needs more than one click"): every
// innerHTML rebuild destroys the chip that is mid-press.

const Card = customElements.get("dreame-a2-session-calendar");
const card = new Card();
card.setConfig({});
const HASS = {
  states: {
    "calendar.dreame_a2_mower_sessions": { state: "off", attributes: {} },
    "select.dreame_a2_mower_session_replay": { state: "x", attributes: { options: OPT } },
  },
  callApi: async () => EV,
  callService() {},
};
card.hass = HASS;                       // first: triggers the month fetch
await new Promise((r) => setTimeout(r, 0)); // let _fetch resolve
const afterFirst = card.shadowRoot.innerHTML;
assert.ok(afterFirst.includes("ha-card"), "first hass renders the grid");

let renders = 0;
const realRender = card._render.bind(card);
card._render = () => { renders++; realRender(); };

// Ten unrelated state ticks — exactly what HA does all day.
for (let i = 0; i < 10; i++) card.hass = { ...HASS };
assert.strictEqual(renders, 0, `unchanged state re-rendered ${renders}x — this eats clicks`);

// A real change still re-renders.
card.hass = {
  ...HASS,
  states: {
    ...HASS.states,
    "select.dreame_a2_mower_session_replay": { state: "x", attributes: { options: [] } },
  },
};
assert.strictEqual(renders, 1, "an options change must re-render (chips grey out)");

console.log("OK");
