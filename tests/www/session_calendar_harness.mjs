// Session-calendar card harness — the pure grid/label logic.
//
// The card's value is one-tap replay: tapping a session on the month grid must
// select EXACTLY the option the replay picker offers. These tests pin the two
// ways that can silently break: date bucketing (an event landing on the wrong
// day cell) and label matching (a tap that fires select_option with a label the
// select doesn't have, which raises in HA).

import assert from "node:assert";

globalThis.HTMLElement = class {};
globalThis.customElements = { get: () => undefined, define() {} };
globalThis.window = { customCards: [] };

const CARD =
  "../../custom_components/dreame_a2_mower/www/dreame-a2-session-calendar.js";
const { buildMonthMatrix, labelDate, groupByDay, replayableSet } = await import(CARD);

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

console.log("OK");
