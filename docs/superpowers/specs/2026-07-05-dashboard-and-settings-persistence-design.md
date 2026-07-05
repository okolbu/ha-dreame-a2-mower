# Design: v2 dashboard polish + device-wide settings persistence

**Date:** 2026-07-05
**Status:** approved (brainstorm) — ready for implementation plan

## Problem

Three issues surfaced after the v2.0.0 rewrite, while the mower is away for repairs (device off; cloud account reachable):

1. The **LiDAR** and **WiFi coverage** cards live inside the *Sessions* tab of the strategy-generated Mower dashboard, but they are archive browsers that are not session-scoped — they belong in their own tab.
2. The **session-replay metadata card** (session stats shown alongside the replay animation) that existed on the pre-v2 dashboard was not reproduced in the v2 strategy.
3. The **Settings / Do-Not-Disturb** dashboard controls render as `unavailable` / `unknown`, i.e. blank.

## Background — how the Mower dashboard is built

The Mower dashboard is a **strategy dashboard**: its stored YAML is literally
`strategy: {type: custom:dreame-a2-mower}`. Every tab and card is generated in
JS by `custom_components/dreame_a2_mower/www/dreame-a2-strategy.js` from the live
entity/device registry. There is no hand-edited dashboard YAML. Parts 1 and 2
are edits to that one strategy file; Part 3 is Python in the integration.

## Root-cause evidence (device-off API sweep, 2026-07-05)

A read-only sweep of every cloud family with the device off (`[api-sweep@2026-07-05 device-off]`) established the data-source split cleanly:

- **Routed-action family** (`action` siid=2/aiid=50, relayed to the device): `fetch_cfg`, `fetch_dev`, `fetch_mihis`, `fetch_dock`, `fetch_net`, `fetch_remote` — **all return `None`** after a uniform ~8 s relay timeout. This path is genuinely **device-live**; it goes dark when the mower is off.
- **Cloud-batch family** (`get_batch_device_datas([])`, cloud cache): per-map `settings` (all maps/zones), `schedule`, `ai_human_enabled`, `maps_by_id`, `mow_paths`, `forbidden_node_types`, `ota_status`, `props`, `cruise_config` — **all answer instantly** from cloud cache. Survives the device being off.

Cross-checked against live HA entity states: every `map_*` per-map switch/select/number holds a real value right now; every device-wide CFG-backed switch is `unavailable`, and every CFG-backed time/number/select is `unknown`.

**Conclusion:** the Settings/DnD tab is fed exclusively by **CFG**, which is a device-routed call. With the device off, CFG returns nothing, so those entities have no value. Per-map settings, schedule, and AI-human come from the cloud batch and already survive offline — they need no persistence.

### Why `unavailable` (switches) vs `unknown` (time/number/select)

`cloud_is_fresh` is `True` right now (the batch fetch succeeds → `_consecutive_cloud_failures = 0`), so `_FreshnessAvailableMixin.available` (`_availability.py:151`) does **not** gate these entities off. The blank is purely a missing value:

- Switches route through the control-honesty layer and go `unavailable` when `is_on` is `None` (a control holding no value).
- time/number/select stay `available` and render `unknown` for a `None` value.

Either way, **seeding a real CFG value on boot resolves both** — `is_on`/`native_value` become non-`None`, and freshness is already `True`.

### Why DnD is blank now but `dock_compass_bearing` survived

Both are device-routed. The `LastKnown` restore pipeline works (proven by `dock_compass_bearing = 91.0` surviving), but its field list covers dock pose and only ~9 CFG fields — and CFG answers only when the mower is awake (relay-gated; returns `None` when docked-idle). So DnD/volume/etc. were likely never captured into the snapshot in a recent awake window. The fix is to widen coverage; the honest limit is that a value persists only after CFG answers successfully at least once while online — "durable after the next healthy online session," not "conjured while at the repair shop."

## Design

### Part 1 — LiDAR & WiFi own tab (`dreame-a2-strategy.js`)

Extract the LiDAR-archive block (currently `dreame-a2-strategy.js:733–747`) and the WiFi-coverage block (`:749–764`) out of `sessionsView()` into a new builder:

```
function coverageView(ctx) { … }   // returns { title: "Coverage & Signal", path: "coverage",
                                    //           type: "panel", icon: "mdi:radar", cards: [...] }
```

Register it in the view list (`:904–915`) with `views.push(coverageView(ctx))`, placed **after** `sessionsView(ctx, opts)`. `sessionsView` keeps calendar / replay / charts / totals only. Preserve the existing `ctx.resolve(...)` existence guards so the tab (and each card) self-hides when the archives are absent. Pure structural move — no card-content changes.

### Part 2 — Session-replay metadata card (`dreame-a2-strategy.js`)

Add a **markdown summary card** in `sessionsView`, in the `right` column beside the replay card (near `:719–721`), rendered only when `ctx.resolve("picked_session")` exists. It reads the already-exposed `sensor.picked_session` attributes (built by `domain/session/replay.py:build_picked_session_summary`): `area_mowed_m2`, `coverage_pct`, `m2_per_min`, `charge_used_pct`, `time_mowing_min`, `time_charging_min`, `time_other_min`, `session_type`, `outcome`, `target_ids`, plus the session date/label and duration.

Type-aware: for non-mow sessions the mow-stat attributes are `None`, so the markdown template must omit those rows (guard each with a null check) rather than print "0.0 m² / 0%". No backend change — the data is live on the sensor.

### Part 3 — Persist device-wide CFG settings across offline/restart (`state/last_known.py`)

Extend the existing `LastKnown` snapshot to cover the full set of **CFG-backed device-wide config** fields, reusing the already-wired pipeline: `_save_last_known` (debounced) → `_restore_last_known` seeds `coordinator.data` before the first cloud fetch (`domain/boot.py`). Two edits per field: add the name to `_STATE_FIELDS` and add a matching `<name>: <type> | None = None` line to the `LastKnown` dataclass (kept 1:1 by the module's own contract).

**Authoritative source rule:** persist every field written by `state/apply.py:cfg_to_state_updates` that is a config setting and is not already in `_STATE_FIELDS`. Telemetry is out of scope (config only). The implementation must also cross-check the Settings-tab entity descriptors (switch/time/number/select `value_fn`s) so no Settings control is left uncovered.

Fields to add (all confirmed CFG-written in `state/apply.py`; names are real MowerState flat fields):

- **Child lock:** `child_lock_enabled`
- **Volume:** `volume_pct`
- **Language/voice idx:** `language_text_idx`, `language_voice_idx`, `language_code`
- **Low-speed-at-night:** `low_speed_at_night_enabled`, `low_speed_at_night_start_min`, `low_speed_at_night_end_min`
- **Battery thresholds:** `auto_recharge_battery_pct`, `resume_battery_pct`
- **LED:** `led_period_enabled`, `led_in_standby`, `led_in_working`, `led_in_charging`, `led_in_error`
- **Anti-theft:** `anti_theft_lift_alarm`, `anti_theft_offmap_alarm`, `anti_theft_realtime_location`
- **Human presence:** `human_presence_alert_enabled`, `human_presence_alert_sensitivity`, `human_presence_scenario_standby`, `human_presence_scenario_mowing`, `human_presence_scenario_recharge`, `human_presence_scenario_patrol`, `human_presence_alert_voice`, `human_presence_alert_push_interval_min`
- **Notification messages:** `msg_alert_anomaly`, `msg_alert_error`, `msg_alert_task`, `msg_alert_consumables`
- **Voice prompts:** `voice_regular_notification`, `voice_work_status`, `voice_special_status`, `voice_error_status`

Already covered (no change): `rain_protection_enabled`, `rain_protection_resume_hours`, `frost_protection_enabled`, `dnd_enabled`, `dnd_start_min`, `dnd_end_min`, `custom_charging_enabled`, `charging_start_min`, `charging_end_min`.

**Correctness guardrails already present:** `cfg_to_state_updates` never nulls a field for an absent CFG key (a later failed CFG fetch keeps the in-memory value), and `LastKnown.non_none_state_updates()` never seeds a `None` over a real value on restore. So once a field is captured it stays captured.

### Out of scope (explicit)

- Alternative cloud read paths for CFG fields: none exists today (CFG is absent from the empty-batch), and we are not adding or hunting for one.
- Telemetry persistence (battery, position, live state) — config only.
- Per-map / schedule / AI-human persistence — already survive offline via the cloud batch.

## Testing

- **Part 1/2 (strategy JS):** run the strategy `generate()` in a node harness (per `feedback_frontend_card_verification` — execute the render fn, not just `node --check`); assert a `coverage` view exists with the LiDAR + WiFi cards, that `sessions` no longer contains them, and that the metadata markdown card appears only when `picked_session` resolves. Extend the existing strategy test if present.
- **Part 3 (Python):** unit test that `LastKnown.from_state` captures each new field, `to_dict`/`from_dict` round-trips it, and `non_none_state_updates` seeds it while skipping `None`. The corpus-replay golden digest must stay byte-identical (LastKnown is deliberately separate from `MowerState`/`FLAT_FIELDS`, so it does not touch the digest — verify it still does not).
- Full suite: `.venv-vanilla` per `reference_test_env_setup`.

## Fact-discipline task

Record the device-off sweep result into `inventory.yaml` (routed-action = device-live; empty-batch = cloud-cached), with evidence tag `[api-sweep@2026-07-05]`, per the repo's inventory rule. Cite the existing CFG/SETTINGS sections rather than restating decoded values.
