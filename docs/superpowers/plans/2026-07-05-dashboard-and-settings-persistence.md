# v2 Dashboard Polish + Device-Wide Settings Persistence — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move LiDAR/WiFi into their own dashboard tab, re-add the session-replay metadata card, and persist device-wide CFG settings so the Settings/DnD tab survives restarts and the mower being offline.

**Architecture:** Parts 1 & 2 edit the pure JS dashboard strategy (`www/dreame-a2-strategy.js`), proven by the existing Node harness (`tests/www/strategy_harness.mjs`). Part 3 widens the existing `LastKnown` snapshot (`state/last_known.py`) — a self-contained value object persisted via its own HA `Store`, already wired to save after each refresh and seed `coordinator.data` before the first cloud fetch. Part 4 records the wire finding in `inventory.yaml`.

**Tech Stack:** Python 3.13 (HA custom integration), vanilla ES-module JS (Lovelace strategy, no build step), pytest, Node for the strategy harness.

## Global Constraints

- Test env: use `/data/claude/homeassistant/.venv-vanilla` (Python 3.13) — system `python3` is broken (`reference_test_env_setup`). Baseline before changes: 1591 passed / 4 skipped.
- Config only, NEVER telemetry: Part 3 persists device-wide CFG *settings* fields — do not add battery/position/state/live fields.
- `LastKnown` MUST stay separate from `MowerState`/`FLAT_FIELDS`: adding fields there must NOT change `MowerState.to_flat_dict()`/`FLAT_FIELDS`/`asdict(snapshot())` (would break the corpus-replay golden digest). Only `state/last_known.py` changes in Part 3.
- Strategy JS is verified by executing the render fn in Node, never `node --check` alone (`feedback_frontend_card_verification`). Cards cache hard in the browser — irrelevant to the harness but note for live deploy.
- Per-map naming, control-honesty, and inventory rules from `CLAUDE.md` are unchanged by this work; no new entities are added, so no `state_machine_audit_expectations.yaml` / entity-inventory rows are needed.
- Dashboard deploy (live): the strategy JS ships via HACS in `www/`; the strategy dashboard regenerates client-side — no dashboard YAML SCP needed. Hard-refresh the browser to bust the card cache.

---

## File Structure

- `custom_components/dreame_a2_mower/www/dreame-a2-strategy.js` — add `coverageView()` + `replayMetaCard()`; edit `sessionsView()` + the view list. (Parts 1 & 2)
- `tests/www/strategy_harness.mjs` — add assertions for the Coverage tab + metadata card. (Parts 1 & 2)
- `custom_components/dreame_a2_mower/state/last_known.py` — extend `_STATE_FIELDS` + the `LastKnown` dataclass. (Part 3)
- `tests/test_last_known.py` — add capture/round-trip/seed tests for the new fields. (Part 3)
- `custom_components/dreame_a2_mower/inventory.yaml` — record the device-off sweep finding. (Part 4)

---

## Task 1: LiDAR + WiFi → their own "Coverage & Signal" tab

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-a2-strategy.js` (`sessionsView` ~698–767; view list ~904–915)
- Test: `tests/www/strategy_harness.mjs`

**Interfaces:**
- Consumes: `ctx.resolve(key)`, `headerCard(emoji,title,note)`, `entitiesCard(ctx,title,rows)`, `DOMAIN` — all already in the file.
- Produces: `function coverageView(ctx)` returning a Lovelace view `{title:"Coverage & Signal", path:"coverage", type:"panel", icon:"mdi:radar", cards:[...]}` or `null` when no archives resolve.

- [ ] **Step 1: Write the failing test.** In `tests/www/strategy_harness.mjs`, inside `run()`, after the existing `cfg1` block (after the `atomic-calendar`/native-calendar asserts, ~line with `'"type":"calendar"'`), add:

```js
  // --- Part 1: LiDAR + WiFi live on their own Coverage tab, not Sessions. ---
  const covView1 = cfg1.views.find((v) => v.path === "coverage");
  assert(covView1, "coverage: no 'Coverage & Signal' view");
  assert(covView1.title === "Coverage & Signal", "coverage: wrong view title");
  assert(jsonHas(covView1, "custom:dreame-a2-lidar-card"), "coverage: LiDAR card missing from Coverage view");
  assert(jsonHas(covView1, "WiFi Coverage"), "coverage: WiFi block missing from Coverage view");
  const sessView1 = cfg1.views.find((v) => v.path === "sessions");
  assert(sessView1, "sessions: view missing");
  assert(!jsonHas(sessView1, "custom:dreame-a2-lidar-card"), "sessions: LiDAR card still present after move");
  assert(!jsonHas(sessView1, "WiFi Coverage"), "sessions: WiFi block still present after move");
```

- [ ] **Step 2: Run the harness to verify it fails.**

Run: `node tests/www/strategy_harness.mjs`
Expected: FAIL with `ASSERT FAILED: coverage: no 'Coverage & Signal' view`.

- [ ] **Step 3: Implement the move.** In `www/dreame-a2-strategy.js`, DELETE the two blocks from `sessionsView` (the `// LiDAR archive.` block and the `// WiFi coverage.` block, currently lines ~733–764) so `sessionsView` ends right after the `if (picked) { cards.push(sessionChartsRow(...)); }` block and returns as before. Then add a new function immediately after `sessionsView`:

```js
function coverageView(ctx) {
  const cards = [];

  // LiDAR archive.
  const lidarSel = ctx.resolve("lidar_archive");
  const lidarCount = ctx.resolve("lidar_archive_count");
  if (lidarSel || lidarCount) {
    cards.push(headerCard("📡", "LiDAR", "archived 3-D point clouds"));
    const lrow = [];
    const arch = entitiesCard(ctx, "Archive", [
      { key: "lidar_archive_count", name: "Total scans" },
      { key: "lidar_archive", name: "Selected scan" },
    ]);
    if (arch) lrow.push(arch);
    if (lidarSel)
      lrow.push({ type: "custom:dreame-a2-lidar-card", url: `/api/${DOMAIN}/lidar/selected.pcd`, picker_entity: lidarSel });
    if (lrow.length) cards.push({ type: "horizontal-stack", cards: lrow });
  }

  // WiFi coverage.
  const wifiCam = ctx.resolve("wifi_selected");
  const wifiSel = ctx.resolve("wifi_archive");
  if (wifiCam || wifiSel) {
    cards.push(headerCard("📶", "WiFi Coverage", "signal strength measured during mowing"));
    const wrow = [];
    const wctrl = entitiesCard(ctx, "Viewer controls", [
      { key: "wifi_archive", name: "Heatmap" },
      { key: "wifi_heatmap_flip_x", name: "Flip X" },
      { key: "wifi_heatmap_flip_y", name: "Flip Y" },
    ]);
    if (wctrl) wrow.push(wctrl);
    if (wifiCam)
      wrow.push({ type: "picture-entity", entity: wifiCam, name: "WiFi heatmap", camera_view: "auto", show_state: false });
    if (wrow.length) cards.push({ type: "horizontal-stack", cards: wrow });
  }

  if (!cards.length) return null; // self-hide when no archives exist
  return { title: "Coverage & Signal", path: "coverage", type: "panel", icon: "mdi:radar", cards: [{ type: "vertical-stack", cards: cards.filter(Boolean) }] };
}
```

Then in the view list (the `views.push(...)` sequence ~904–913), add after `views.push(sessionsView(ctx, opts));`:

```js
  const cov = coverageView(ctx);
  if (cov) views.push(cov);
```

- [ ] **Step 4: Run the harness to verify it passes.**

Run: `node tests/www/strategy_harness.mjs`
Expected: `OK — strategy harness: N views (1-map), …` (view count is one higher than before), exit 0.

- [ ] **Step 5: Commit.**

```bash
git add custom_components/dreame_a2_mower/www/dreame-a2-strategy.js tests/www/strategy_harness.mjs
git commit -m "feat(dashboard): LiDAR + WiFi move to own Coverage & Signal tab

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Session-replay metadata card

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-a2-strategy.js` (`sessionsView` `right` column, ~719–721)
- Test: `tests/www/strategy_harness.mjs`

**Interfaces:**
- Consumes: `ctx.resolve("picked_session")` (already computed as `picked` at ~line 719), `markdown(content, title)`.
- Produces: `function replayMetaCard(picked)` returning a `markdown` card whose content templates read `sensor.picked_session` attributes; the card is pushed into the `right` column only when `picked` resolves.

- [ ] **Step 1: Write the failing test.** In `tests/www/strategy_harness.mjs`, after the Part-1 asserts added in Task 1, add:

```js
  // --- Part 2: session-replay metadata card appears beside the replay card. ---
  assert(jsonHas(sessView1, "area_mowed_m2"), "sessions: replay metadata card missing (no area_mowed_m2 template)");
  assert(jsonHas(sessView1, "Session details"), "sessions: metadata card title missing");
  // Absent when no session is picked.
  const hassNoPick = makeHass(1, { disabledKeys: ["ota_state", "ota_progress", "picked_session"] });
  const cfgNoPick = await generateDashboard({}, hassNoPick);
  const sessNoPick = cfgNoPick.views.find((v) => v.path === "sessions");
  assert(!jsonHas(sessNoPick, "area_mowed_m2"), "sessions: metadata card present without a picked session");
```

- [ ] **Step 2: Run the harness to verify it fails.**

Run: `node tests/www/strategy_harness.mjs`
Expected: FAIL with `ASSERT FAILED: sessions: replay metadata card missing (no area_mowed_m2 template)`.

- [ ] **Step 3: Implement the card.** In `www/dreame-a2-strategy.js`, add this helper directly above `sessionsView`:

```js
// Session-replay metadata summary. Reads sensor.picked_session attributes
// (built by domain/session/replay.py:build_picked_session_summary). Type-aware:
// mow-stat attributes are null for non-mow sessions, so those rows are guarded.
function replayMetaCard(picked) {
  const e = `'${picked}'`;
  const content =
    `### {{ state_attr(${e}, 'label') or 'Session details' }}\n\n` +
    `| | |\n|---|---|\n` +
    `| **Type** | {{ state_attr(${e}, 'session_type') }} |\n` +
    `| **Outcome** | {{ state_attr(${e}, 'result_label') or state_attr(${e}, 'outcome') or '—' }} |\n` +
    `| **Started** | {{ state_attr(${e}, 'started_at') }} |\n` +
    `| **Duration** | {{ state_attr(${e}, 'duration_min') }} min mowing · {{ state_attr(${e}, 'elapsed_min') }} min elapsed |\n` +
    `{% set area = state_attr(${e}, 'area_mowed_m2') %}` +
    `{% if area is not none %}| **Area mowed** | {{ '%.1f'|format(area) }} m²` +
    `{% set cov = state_attr(${e}, 'coverage_pct') %}{% if cov is not none %} ({{ '%.0f'|format(cov) }}%){% endif %} |\n` +
    `{% set rate = state_attr(${e}, 'm2_per_min') %}{% if rate is not none %}| **Rate** | {{ '%.1f'|format(rate) }} m²/min |\n{% endif %}` +
    `{% endif %}` +
    `{% set used = state_attr(${e}, 'charge_used_pct') %}{% if used is not none %}| **Battery used** | {{ used }}% |\n{% endif %}` +
    `{% set rc = state_attr(${e}, 'recharge_count') %}{% if rc %}| **Recharges** | {{ rc }} |\n{% endif %}`;
  return markdown(content, "Session details");
}
```

Then in `sessionsView`, change the `right` column build (currently `if (picked) right.push({ type: "custom:dreame-mower-replay-card", entity: picked });`) to also push the metadata card:

```js
  const picked = ctx.resolve("picked_session");
  const right = [];
  if (picked) {
    right.push(replayMetaCard(picked));
    right.push({ type: "custom:dreame-mower-replay-card", entity: picked });
  }
```

- [ ] **Step 4: Run the harness to verify it passes.**

Run: `node tests/www/strategy_harness.mjs`
Expected: `OK — strategy harness: …`, exit 0.

- [ ] **Step 5: Commit.**

```bash
git add custom_components/dreame_a2_mower/www/dreame-a2-strategy.js tests/www/strategy_harness.mjs
git commit -m "feat(dashboard): re-add session-replay metadata card beside the replay

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Persist all device-wide CFG settings via LastKnown

**Files:**
- Modify: `custom_components/dreame_a2_mower/state/last_known.py` (`_STATE_FIELDS` ~34–69; `LastKnown` dataclass fields ~77–104)
- Test: `tests/test_last_known.py`

**Interfaces:**
- Consumes: `LastKnown.from_state(state, active_map_id, saved_unix)`, `.to_dict()`, `.from_dict()`, `.non_none_state_updates()` — unchanged signatures.
- Produces: the same `LastKnown`, now mirroring 38 additional CFG-backed MowerState fields.

The 38 fields to add (every config field written by `state/apply.py:cfg_to_state_updates` not already in `_STATE_FIELDS`; verified against the Settings-tab entity `value_fn`s; extends the spec's enumerated list with `auto_recharge_standby_enabled` / `ai_obstacle_photos_enabled` / `navigation_path_smart` per the spec's derivation rule):

| Field | Type | CFG source |
|---|---|---|
| `child_lock_enabled` | bool | CLS |
| `volume_pct` | int | VOL |
| `language_text_idx` | int | language |
| `language_voice_idx` | int | language |
| `language_code` | str | language |
| `low_speed_at_night_enabled` | bool | LOW |
| `low_speed_at_night_start_min` | int | LOW |
| `low_speed_at_night_end_min` | int | LOW |
| `auto_recharge_battery_pct` | int | BAT |
| `resume_battery_pct` | int | BAT |
| `led_period_enabled` | bool | LIT |
| `led_in_standby` | bool | LIT |
| `led_in_working` | bool | LIT |
| `led_in_charging` | bool | LIT |
| `led_in_error` | bool | LIT |
| `anti_theft_lift_alarm` | bool | ATA |
| `anti_theft_offmap_alarm` | bool | ATA |
| `anti_theft_realtime_location` | bool | ATA |
| `human_presence_alert_enabled` | bool | REC |
| `human_presence_alert_sensitivity` | int | REC |
| `human_presence_scenario_standby` | bool | REC |
| `human_presence_scenario_mowing` | bool | REC |
| `human_presence_scenario_recharge` | bool | REC |
| `human_presence_scenario_patrol` | bool | REC |
| `human_presence_alert_voice` | bool | REC |
| `human_presence_alert_push_interval_min` | int | REC |
| `msg_alert_anomaly` | bool | MSG_ALERT |
| `msg_alert_error` | bool | MSG_ALERT |
| `msg_alert_task` | bool | MSG_ALERT |
| `msg_alert_consumables` | bool | MSG_ALERT |
| `voice_regular_notification` | bool | VOICE |
| `voice_work_status` | bool | VOICE |
| `voice_special_status` | bool | VOICE |
| `voice_error_status` | bool | VOICE |
| `auto_recharge_standby_enabled` | bool | STUN |
| `ai_obstacle_photos_enabled` | bool | AOP |
| `navigation_path_smart` | bool | PROT |

- [ ] **Step 1: Write the failing test.** Append to `tests/test_last_known.py`:

```python
def test_last_known_captures_all_cfg_settings():
    """Every CFG-backed device-wide setting round-trips through LastKnown."""
    from custom_components.dreame_a2_mower.state.last_known import LastKnown, _STATE_FIELDS

    cfg_fields = {
        "child_lock_enabled": True, "volume_pct": 60,
        "language_text_idx": 1, "language_voice_idx": 2, "language_code": "text=1,voice=2",
        "low_speed_at_night_enabled": True, "low_speed_at_night_start_min": 1320, "low_speed_at_night_end_min": 360,
        "auto_recharge_battery_pct": 15, "resume_battery_pct": 80,
        "led_period_enabled": True, "led_in_standby": True, "led_in_working": False,
        "led_in_charging": True, "led_in_error": True,
        "anti_theft_lift_alarm": True, "anti_theft_offmap_alarm": False, "anti_theft_realtime_location": True,
        "human_presence_alert_enabled": True, "human_presence_alert_sensitivity": 2,
        "human_presence_scenario_standby": True, "human_presence_scenario_mowing": False,
        "human_presence_scenario_recharge": True, "human_presence_scenario_patrol": False,
        "human_presence_alert_voice": True, "human_presence_alert_push_interval_min": 30,
        "msg_alert_anomaly": True, "msg_alert_error": True, "msg_alert_task": False, "msg_alert_consumables": True,
        "voice_regular_notification": True, "voice_work_status": False,
        "voice_special_status": True, "voice_error_status": True,
        "auto_recharge_standby_enabled": True, "ai_obstacle_photos_enabled": False, "navigation_path_smart": True,
    }
    # Every field is a declared _STATE_FIELDS entry.
    for name in cfg_fields:
        assert name in _STATE_FIELDS, f"{name} missing from _STATE_FIELDS"

    class _FakeState:
        pass
    st = _FakeState()
    for k, v in cfg_fields.items():
        setattr(st, k, v)

    lk = LastKnown.from_state(st, active_map_id=0, saved_unix=123.0)
    round_tripped = LastKnown.from_dict(lk.to_dict())
    updates = round_tripped.non_none_state_updates()
    for k, v in cfg_fields.items():
        assert getattr(round_tripped, k) == v, f"{k} lost in round-trip"
        assert updates[k] == v, f"{k} not seeded via non_none_state_updates"
```

- [ ] **Step 2: Run the test to verify it fails.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/test_last_known.py::test_last_known_captures_all_cfg_settings -v`
Expected: FAIL — `child_lock_enabled missing from _STATE_FIELDS`.

- [ ] **Step 3: Add the fields.** In `state/last_known.py`, extend `_STATE_FIELDS` — add a new grouped block before the closing `)` (after the existing `# device-wide read-only time-window / protection settings` group):

```python
    # device-wide CFG config settings (persist so the Settings/DnD tab survives
    # the device being offline — CFG is a device-routed call, dark when off).
    "child_lock_enabled",
    "volume_pct",
    "language_text_idx",
    "language_voice_idx",
    "language_code",
    "low_speed_at_night_enabled",
    "low_speed_at_night_start_min",
    "low_speed_at_night_end_min",
    "auto_recharge_battery_pct",
    "resume_battery_pct",
    "led_period_enabled",
    "led_in_standby",
    "led_in_working",
    "led_in_charging",
    "led_in_error",
    "anti_theft_lift_alarm",
    "anti_theft_offmap_alarm",
    "anti_theft_realtime_location",
    "human_presence_alert_enabled",
    "human_presence_alert_sensitivity",
    "human_presence_scenario_standby",
    "human_presence_scenario_mowing",
    "human_presence_scenario_recharge",
    "human_presence_scenario_patrol",
    "human_presence_alert_voice",
    "human_presence_alert_push_interval_min",
    "msg_alert_anomaly",
    "msg_alert_error",
    "msg_alert_task",
    "msg_alert_consumables",
    "voice_regular_notification",
    "voice_work_status",
    "voice_special_status",
    "voice_error_status",
    "auto_recharge_standby_enabled",
    "ai_obstacle_photos_enabled",
    "navigation_path_smart",
```

Then add the matching dataclass fields to `LastKnown` (before the `# --- meta ---` comment), keeping types per the table:

```python
    child_lock_enabled: bool | None = None
    volume_pct: int | None = None
    language_text_idx: int | None = None
    language_voice_idx: int | None = None
    language_code: str | None = None
    low_speed_at_night_enabled: bool | None = None
    low_speed_at_night_start_min: int | None = None
    low_speed_at_night_end_min: int | None = None
    auto_recharge_battery_pct: int | None = None
    resume_battery_pct: int | None = None
    led_period_enabled: bool | None = None
    led_in_standby: bool | None = None
    led_in_working: bool | None = None
    led_in_charging: bool | None = None
    led_in_error: bool | None = None
    anti_theft_lift_alarm: bool | None = None
    anti_theft_offmap_alarm: bool | None = None
    anti_theft_realtime_location: bool | None = None
    human_presence_alert_enabled: bool | None = None
    human_presence_alert_sensitivity: int | None = None
    human_presence_scenario_standby: bool | None = None
    human_presence_scenario_mowing: bool | None = None
    human_presence_scenario_recharge: bool | None = None
    human_presence_scenario_patrol: bool | None = None
    human_presence_alert_voice: bool | None = None
    human_presence_alert_push_interval_min: int | None = None
    msg_alert_anomaly: bool | None = None
    msg_alert_error: bool | None = None
    msg_alert_task: bool | None = None
    msg_alert_consumables: bool | None = None
    voice_regular_notification: bool | None = None
    voice_work_status: bool | None = None
    voice_special_status: bool | None = None
    voice_error_status: bool | None = None
    auto_recharge_standby_enabled: bool | None = None
    ai_obstacle_photos_enabled: bool | None = None
    navigation_path_smart: bool | None = None
```

- [ ] **Step 4: Run the new test + the full last_known suites to verify green.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/test_last_known.py tests/integration/test_offline_last_known_surface.py tests/integration/test_last_known_persist.py -v`
Expected: all PASS, including the new `test_last_known_captures_all_cfg_settings`.

- [ ] **Step 5: Verify the corpus-replay golden digest is untouched.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_map_render_golden.py -q` and, if present, the corpus digest test: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q -k "corpus or digest"`
Expected: PASS (LastKnown is separate from `MowerState`/`FLAT_FIELDS`, so the digest cannot change).

- [ ] **Step 6: Commit.**

```bash
git add custom_components/dreame_a2_mower/state/last_known.py tests/test_last_known.py
git commit -m "feat(offline): persist all device-wide CFG settings in LastKnown

Widens the last-known snapshot to every CFG-backed config field so the
Settings/DnD tab survives restarts and the mower being offline. CFG is a
device-routed call (dark when the mower is off); per-map/schedule/AI-human
already survive via the cloud batch and are unchanged.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Record the device-off sweep finding in inventory

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory.yaml` (CFG and the batch/SETTINGS sections)

**Interfaces:** none (documentation of a wire fact).

- [ ] **Step 1: Locate the relevant sections.**

Run: `grep -nE "^  (CFG|SETTINGS|batch|routed)" custom_components/dreame_a2_mower/inventory.yaml | head`
Expected: prints the anchor line(s) for the CFG / SETTINGS / batch sections.

- [ ] **Step 2: Append a verification record** under the CFG section's `verifications:` list (and the empty-batch/SETTINGS section's, if separate), following the `CLAUDE.md` schema. Do NOT restate decoded values — cite the section. Example shape:

```yaml
    verifications:
      - date: "2026-07-05"
        status: verified
        claim: "Device-off sweep: routed-action family (CFG/DEV/MIHIS/DOCK/NET/REMOTE) returns None after ~8s relay timeout (device-live); empty-batch get_batch_device_datas([]) answers from cloud cache (per-map SETTINGS/schedule/ai_human survive offline)."
        evidence: "api-sweep@2026-07-05 device-off"
```

Also set `status.last_seen: "2026-07-05"` on the CFG entry.

- [ ] **Step 3: Validate the inventory schema.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only`
Expected: exits 0 (no schema errors). If it reports drift in `_DECODED_VALUES`/`_UNIT_VOCAB`, that means an unrelated pre-existing issue — only fix if the change is yours.

- [ ] **Step 4: Regenerate the canonical doc** (it is NOT auto-generated in CI):

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py`
Expected: regenerates `docs/research/inventory/generated/g2408-canonical.md`; `git diff --stat` shows only the CFG/SETTINGS verification lines (do not commit unrelated wire-census count churn).

- [ ] **Step 5: Commit.**

```bash
git add custom_components/dreame_a2_mower/inventory.yaml docs/research/inventory/generated/g2408-canonical.md
git commit -m "docs(inventory): record device-off API sweep (routed=device-live, batch=cloud-cache)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final verification (after all tasks)

- [ ] **Full suite green:**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q`
Expected: 1592+ passed / 4 skipped (one more than the 1591 baseline — the new `test_last_known_captures_all_cfg_settings`).

- [ ] **Strategy harness green:**

Run: `node tests/www/strategy_harness.mjs`
Expected: `OK — strategy harness: …`, exit 0.

- [ ] **Live-deploy sanity (optional, when convenient):** ship via `tools/release/release.sh`, hard-refresh the browser, confirm the new **Coverage & Signal** tab renders and the **Session details** card appears when a session is picked. The Settings/DnD tab will only repopulate once the mower is back online long enough for one successful CFG fetch (then it persists) — expected while it is at the repair shop.

## Self-review notes

- **Spec coverage:** Part 1 → Task 1; Part 2 → Task 2; Part 3 → Task 3 (field list complete + 3 fields beyond the spec's enumeration, justified by the spec's own derivation rule); fact-discipline task → Task 4. Out-of-scope items (alt read paths, telemetry, per-map persistence) are respected — no task touches them.
- **Placeholder scan:** every code/step block is concrete; no TBD/TODO.
- **Type consistency:** `coverageView`/`replayMetaCard`/`LastKnown` names and the 38 field names are identical across the test, the field tuple, and the dataclass.
