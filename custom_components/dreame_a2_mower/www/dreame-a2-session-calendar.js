// Dreame A2 Mower — Session Calendar Card (one-tap replay).
//
// A month grid of archived sessions where tapping a session drives the replay
// picker directly. Replaces the HACS `atomic-calendar-revive` card on the
// Sessions tab, which needed two surfaces and two clicks: neither it (its
// tap_action fires the same call for every event — no per-event
// `{{event.summary}}` substitution) nor the HA-native `type: calendar`
// (hard-coded more-info popup) can do one-tap. Both confirmed 2026-05-13.
//
// Usage (Lovelace YAML):
//   - type: custom:dreame-a2-session-calendar
//     # entity: calendar.dreame_a2_mower_sessions          (default)
//     # select_entity: select.dreame_a2_mower_session_replay (default)
//
// How the one-tap works: calendar.py:_event_from_entry formats each event's
// `summary` with domain/session/replay.py:format_session_label — the SAME
// function the replay select builds its options from. So the summary is
// byte-identical to a select option and can be passed straight to
// select.select_option. tests/integration/test_calendar.py pins that match.

import { defineCard, renderMissingEntity } from "./_dreame-card-core.js";

const DAY_MS = 86400000;
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
// Tag → chip colour. Mirrors the label tags emitted by format_session_label.
const TAG_COLORS = {
  "[Mowing]": "#2b8a3e",
  "[Patrol]": "#1971c2",
  "[To Point]": "#e8590c",
  "[Manual]": "#6741d9",
};

function _esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]
  ));
}

function _dayKey(y, m, d) {
  const p = (n) => String(n).padStart(2, "0");
  return `${y}-${p(m + 1)}-${p(d)}`;
}

// The label's own date — NOT the event's UTC start. format_session_label
// renders the session START in local time, and that is what both the picker and
// the Dreame app show; bucketing by the UTC start would file a late-evening
// session under tomorrow in any TZ east of UTC.
//
// Every session type shares the shape `[Tag] [Map N] YYYY-MM-DD HH:MM …`, and
// an unparseable timestamp renders as "??" (format_session_label's fallback) —
// return null for those rather than invent a day.
export function labelDate(summary) {
  if (!summary) return null;
  const m = /\b(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}\b/.exec(String(summary));
  return m ? m[1] : null;
}

// A Monday-start month grid, always a whole number of 7-day rows. Out-of-month
// cells are included (rendered greyed) so the grid stays rectangular.
export function buildMonthMatrix(year, monthIndex) {
  const first = new Date(year, monthIndex, 1);
  // getDay(): 0=Sun..6=Sat → Monday-start offset.
  const lead = (first.getDay() + 6) % 7;
  const start = new Date(year, monthIndex, 1 - lead);
  const weeks = [];
  let cursor = start.getTime();
  // Loop until the cursor has passed the month AND the row is complete, so a
  // month that starts on Monday doesn't get a blank leading row.
  for (let w = 0; w < 6; w++) {
    const row = [];
    for (let d = 0; d < 7; d++) {
      const dt = new Date(cursor);
      row.push({
        key: _dayKey(dt.getFullYear(), dt.getMonth(), dt.getDate()),
        day: dt.getDate(),
        inMonth: dt.getMonth() === monthIndex && dt.getFullYear() === year,
      });
      cursor += DAY_MS;
    }
    weeks.push(row);
    const next = new Date(cursor);
    if (next.getMonth() !== monthIndex || next.getFullYear() !== year) break;
  }
  return weeks;
}

// Bucket events under the day their LABEL names. Events whose label has no
// parseable date are dropped rather than filed under a wrong day.
export function groupByDay(events) {
  const out = {};
  if (!Array.isArray(events)) return out;
  for (const ev of events) {
    const key = labelDate(ev && ev.summary);
    if (!key) continue;
    (out[key] = out[key] || []).push(ev);
  }
  return out;
}

// The set of summaries the replay select will actually accept.
//
// Load-bearing: the select caps at the 50 most recent sessions
// (entities/select/global_.py:_max_options) while the calendar carries every
// archived session. Calling select_option with a label outside the options
// raises in HA, so an older session must render as non-tappable rather than as
// a button that errors.
export function replayableSet(options) {
  return new Set(Array.isArray(options) ? options : []);
}

function chipColor(summary) {
  for (const [tag, color] of Object.entries(TAG_COLORS)) {
    if (String(summary || "").startsWith(tag)) return color;
  }
  return "var(--primary-color)";
}

// The compact chip text: the time + tag, since the day is already the cell.
function chipText(summary) {
  const s = String(summary || "");
  const time = /\b\d{4}-\d{2}-\d{2}\s+(\d{2}:\d{2})\b/.exec(s);
  const tag = /^\[([^\]]+)\]/.exec(s);
  return `${time ? time[1] : ""} ${tag ? tag[1] : ""}`.trim();
}

const STYLE = `
  <style>
    .wrap { padding: 8px 12px 12px; }
    .hdr {
      display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
    }
    .hdr .title { font-weight: 600; flex: 1; }
    .hdr button {
      background: var(--card-background-color); color: var(--primary-text-color);
      border: 1px solid var(--divider-color); border-radius: 4px;
      padding: 2px 10px; font-size: 15px; cursor: pointer;
    }
    .grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; }
    .wd {
      text-align: center; font-size: 0.72em; padding: 2px 0;
      color: var(--secondary-text-color);
    }
    .cell {
      min-height: 52px; border: 1px solid var(--divider-color);
      border-radius: 4px; padding: 2px; overflow: hidden;
    }
    .cell.out { opacity: 0.35; }
    .cell.today { border-color: var(--primary-color); border-width: 2px; }
    .dnum { font-size: 0.72em; color: var(--secondary-text-color); }
    .chip {
      display: block; width: 100%; margin-top: 2px; padding: 1px 3px;
      border: none; border-radius: 3px; color: #fff;
      font-size: 0.68em; text-align: left; cursor: pointer;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .chip[disabled] { cursor: not-allowed; opacity: 0.45; }
    .empty { padding: 8px 0; color: var(--secondary-text-color); font-size: 0.9em; }
  </style>`;

class DreameA2SessionCalendarCard extends HTMLElement {
  setConfig(cfg) {
    cfg = cfg || {};
    this._cfg = {
      entity: cfg.entity || "calendar.dreame_a2_mower_sessions",
      // P4.5 renamed the picker to select.dreame_a2_mower_session_replay (the
      // unique_id key "work_log" is unchanged) — the old ..._work_log id in
      // docs/TODO.md is stale.
      select_entity: cfg.select_entity || "select.dreame_a2_mower_session_replay",
      title: cfg.title || "Sessions",
    };
    const now = new Date();
    this._year = now.getFullYear();
    this._month = now.getMonth();
    this._events = [];
    this._fetchKey = null;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    if (!hass || !hass.states[this._cfg.entity]) {
      if (this._missingShown !== this._cfg.entity) {
        this._missingShown = this._cfg.entity;
        this.shadowRoot.innerHTML = renderMissingEntity(this._cfg.entity);
      }
      return;
    }
    this._missingShown = null;
    if (first) this._fetch();
    else this._render();
  }

  // Calendar events are NOT in the entity state — they're fetched per window.
  // Re-fetched only on a month change; `set hass` fires far too often to hit
  // the API on every state update.
  async _fetch() {
    const key = `${this._year}-${this._month}`;
    if (key === this._fetchKey) return;
    this._fetchKey = key;
    const start = new Date(this._year, this._month, 1);
    const end = new Date(this._year, this._month + 1, 1);
    try {
      const path =
        `calendars/${this._cfg.entity}` +
        `?start=${encodeURIComponent(start.toISOString())}` +
        `&end=${encodeURIComponent(end.toISOString())}`;
      this._events = (await this._hass.callApi("GET", path)) || [];
    } catch (e) {
      this._events = [];
      this._error = e && e.message ? e.message : String(e);
    }
    this._render();
  }

  _options() {
    const st = this._hass && this._hass.states[this._cfg.select_entity];
    return (st && st.attributes && st.attributes.options) || [];
  }

  _render() {
    const byDay = groupByDay(this._events);
    const replayable = replayableSet(this._options());
    const todayKey = (() => {
      const n = new Date();
      return _dayKey(n.getFullYear(), n.getMonth(), n.getDate());
    })();

    const weeks = buildMonthMatrix(this._year, this._month);
    let idx = 0;
    this._chipMap = [];
    const cells = weeks
      .map((week) =>
        week
          .map((d) => {
            const evs = byDay[d.key] || [];
            const chips = evs
              .map((ev) => {
                const ok = replayable.has(ev.summary);
                const i = idx++;
                this._chipMap.push(ev);
                const title = ok
                  ? ev.summary
                  : `${ev.summary}\n(not in the replay picker — older than its ${
                      this._options().length
                    }-session window)`;
                return (
                  `<button class="chip" data-idx="${i}" ${ok ? "" : "disabled"} ` +
                  `style="background:${ok ? chipColor(ev.summary) : "var(--disabled-text-color,#999)"}" ` +
                  `title="${_esc(title)}">${_esc(chipText(ev.summary))}</button>`
                );
              })
              .join("");
            const cls =
              "cell" + (d.inMonth ? "" : " out") + (d.key === todayKey ? " today" : "");
            return `<div class="${cls}"><div class="dnum">${d.day}</div>${chips}</div>`;
          })
          .join(""),
      )
      .join("");

    const body = this._error
      ? `<div class="empty">Could not load sessions: ${_esc(this._error)}</div>`
      : `<div class="grid">${WEEKDAYS.map((w) => `<div class="wd">${w}</div>`).join("")}${cells}</div>` +
        (idx === 0 ? '<div class="empty">No sessions this month.</div>' : "");

    this.shadowRoot.innerHTML =
      `<ha-card>${STYLE}<div class="wrap">` +
      `<div class="hdr"><button id="prev" title="Previous month">‹</button>` +
      `<span class="title">${_esc(MONTHS[this._month])} ${this._year}</span>` +
      `<button id="today" title="Jump to this month">Today</button>` +
      `<button id="next" title="Next month">›</button></div>` +
      `${body}</div></ha-card>`;

    const go = (dy, dm) => {
      const d = new Date(this._year, this._month + dm, 1);
      this._year = d.getFullYear();
      this._month = d.getMonth();
      this._fetch();
    };
    this.shadowRoot.getElementById("prev").onclick = () => go(0, -1);
    this.shadowRoot.getElementById("next").onclick = () => go(0, 1);
    this.shadowRoot.getElementById("today").onclick = () => {
      const n = new Date();
      this._year = n.getFullYear();
      this._month = n.getMonth();
      this._fetch();
    };
    this.shadowRoot.querySelectorAll(".chip").forEach((btn) => {
      btn.onclick = () => {
        const ev = (this._chipMap || [])[Number(btn.getAttribute("data-idx"))];
        if (!ev) return;
        // The summary IS a select option, byte-for-byte — same formatter on
        // both sides (calendar.py:_event_from_entry / the select's options).
        this._hass.callService("select", "select_option", {
          entity_id: this._cfg.select_entity,
          option: ev.summary,
        });
      };
    });
  }

  getCardSize() {
    return 6;
  }

  static getStubConfig() {
    return { entity: "calendar.dreame_a2_mower_sessions" };
  }
}

// release.sh rewrites this one line per card; keep the exact `const CARD_VERSION
// = "..."` shape. defineCard logs the once-per-tag console banner.
const CARD_VERSION = "2.1.0";
defineCard("dreame-a2-session-calendar", DreameA2SessionCalendarCard, {
  name: "Dreame Mower Session Calendar",
  description: "Month grid of archived sessions; tap one to load it in the replay camera.",
  version: CARD_VERSION,
});
