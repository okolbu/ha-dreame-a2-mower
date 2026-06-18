# g2408 fault/notification catalog → integration — program overview

**Date:** 2026-06-18 · **Status:** approved decomposition; phases spec'd individually

## Source & authority

`artifacts/g2408-plugin-extract/` — the Dreame RN plugin `dreame.vacuum.common`
(ext 1423, ver 534) for the g2408, resolved to localized text. **Treated as
wire-authoritative** (user directive + repo app-MITM rule): the iot fault
catalog is 71/72-confirmed against the wire, and the strings come from the app
code that drives our exact model. Provenance tag: `[apk:g2408-plugin-ext1423]`.

## The data (must all land in the integration)

`tables/g2408_faults_localized.json`: per **channel** (`iot` = s2p2 / MQTT
event_occured, 69 codes; `heartbeat` = s1p1, 45 codes), per **code**:
- `fault_name` enum (e.g. `FAULT_HUMAN_DETECTED`) — language-neutral, stable.
- **category** = the `fault_name` prefix: **FAULT / ALERT / INFO**. This is the
  authoritative classification and **supersedes the hand-rolled "text vs fault"
  heuristic**; it drives fault-state latching and notification/trigger handling.
- `messageType` severity: anomaly (异常) / malfunction (故障) / work-message
  (工作消息) / consumable (耗材消息).
- `can_suppress` 0/1.
- 21 languages × text fields {popup, alert, resident, detailTitle, detail}.
  Display string = first-non-empty(alert, popup, resident); detail = solution steps.

Languages: zh en de fr it es pt nl da sv fi pl nb ru tr lt cs lv sk hu ro.

## Phases (each its own spec → plan → ship)

- **P0 — Catalog foundation** *(spec'd now)*. A `tools/` generator transforms the
  artifact into a bundled, regeneratable JSON (`mower/data/fault_catalog.json`,
  both channels · 21 langs · all fields · category · severity · can_suppress) +
  a pure access module `mower/fault_catalog.py`. CI sync gate pins data↔generator.
  No entity changes — pure capability + tests. Everything below builds on it.
- **P1 — Localized error display.** Error sensor + `describe_error` → catalog text
  by `hass.config.language`; localized detail + language-neutral `fault_name`/
  `category` as attributes; retire hand-curated `ERROR_CODE_DESCRIPTIONS`
  (catalog-backed shim); adapt the confidence gate (catalog = authoritative).
- **P2 — Authoritative classification.** Regenerate `S2P2_EVENT_TYPES` slugs +
  `FAULT_CODES` from `fault_name`/category/severity. FAULT/ALERT/INFO becomes the
  source of truth for what latches as a fault vs surfaces as info/alert.
- **P3 — Notification handling by category.** Localize notification events +
  logbook from the catalog; the FAULT/ALERT/INFO category + severity drive event
  handling and **which codes warrant an HA device-trigger**.
- **P4 — Heartbeat (s1p1) channel.** Apply P1–P3 treatment to the 45 heartbeat
  codes where the state machine latches s1p1.

## Explicitly deferred (separate future work)
- The `FINDING-sim-storage-enhancements` cloud endpoints (`biz_4g_remain` richer
  4G-SIM data; `checkDevOssStorage` OSS quota sensor) — distinct from fault text.
- Multi-language for *other* UI/message strings (settings, entity names) — the
  RN bundle has 2836 strings; this program covers fault/notification only.

## Supersedes
The 2026-06-18 "authoritative-error-text" spec+plan (todo7 #2): the persist-cache
-over-time + curate-from-cloud approach is replaced by this static authoritative
catalog. The error-sensor-prefers-authoritative-text idea survives as P1 (sourced
from the catalog, not the runtime cache). Those two docs move to OLD/.
