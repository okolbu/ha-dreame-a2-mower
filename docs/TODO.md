# Dreame A2 (`g2408`) — Open Work

Actionable items only. Each entry follows the shape:

```
### <One-line action title>

**Why:** brief reason this is open (1-3 sentences).
**Done when:** verifiable acceptance condition.
**Status:** {open, in-progress, blocked-by-X}
**Cross-refs:** journal topic, inventory row(s), spec/plan if any.
```

For resolved / closed items see `/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/DONE.md`.
For the protocol *blank-spots* (undecoded bits/bytes, uncertain slots, corpus
coverage + how to validate each) see `docs/research/knowledge-gaps.md`.
For shipped versions, resolved findings, and the RE journey see
`docs/research/g2408-research-journal.md`.
The old protocol-architecture overview (`docs/research/g2408-protocol.md`) is
ARCHIVED at
`/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/research/g2408-protocol.md`
(contained debunked claims); `custom_components/dreame_a2_mower/inventory.yaml`
and the generated canonical doc are now the wire SoT.
For per-slot detail see `docs/research/inventory/generated/g2408-canonical.md`.

---

## Open

### MITM re-capture backlog (from the 2026-06-16 inventory-purge sweep)

**Why:** the purge sweep (`OLD/ha-dreame-a2-mower-docs/inventory-history/2026-06-16-purge.md`
HANDOVER) surfaced wire facts that need a live app-MITM / probe capture to confirm or pin.
**Tasks (each = one capture). Closed items removed to `OLD/ha-dreame-a2-mower-docs/DONE.md`
(#2 s2p2=72, #5 s4 properties, #6 CRUISED — all closed 2026-06-16/17).**
1. **[s6p2 / PRE] device-side EXECUTION of accepted PRE writes**: verify a single-toggle PRE write
   changes observed mower behaviour. NOTE 2026-06-17: the now-closed #6 (CRUISED) showed integration
   routed-CFG writes DO apply — the apparent "accepted-but-no-effect" was `CRUISE.0` cache LAG, not a
   write failure — so PRE writes very likely apply too; this is now just a behavioural mow-and-observe
   confirmation, no longer a suspected blocker.
2. **[s2p2=20 / 33]** capture cloud-labelled fires to pin the real g2408 text (vs borrowed
   dreame-mower names). Scenario-dependent (need the faults to fire).
3. **[s2p55]** app-MITM during a real AI-obstacle detection to capture the photo list/URL backend call.
   Scenario-dependent (need a real person/animal/obstacle mid-mow).
**Already tracked separately (not duplicated here):** type-3 ephemeral obstacle photos (Photo/video
archive item) and the lazy patrol-photo upload (session_summary_download open-question).
**Status:** open — 3 of 6 closed (moved to DONE.md). The 3 remaining all need a specific live
condition (a behavioural mow, or a real fault / AI detection).
**Cross-refs:** `OLD/ha-dreame-a2-mower-docs/DONE.md` (closed items);
`OLD/ha-dreame-a2-mower-docs/inventory-history/2026-06-16-purge.md`; memory `dreame-mitm-toolkit`;
`inventory.yaml` §§ PRE / s2p2 / s2p55.

### Time-window photo→session match for AI-obstacle photos (follow-up to todo6 #3/#4)

**Why:** Session-replay thumbnails (todo6 #3 Part B) and notification photo-linking (todo6 #4) both
match **photo_list-only** / AI-detection-category-by-timestamp today. If a session's AI-obstacle photos
fall OUTSIDE `photo_list`, they won't appear on the replay screen. Deferred (user call 2026-06-16) until
we understand how those photo types appear relative to `photo_list`.
**Done when:** `session_photos_manifest` optionally unions archived photos whose capture ts ∈
[session.start, session.end] (it's structured for this), validated against a real session that produced
AI-obstacle photos.
**Status:** open (deferred — needs a session with out-of-photo_list AI-obstacle photos to validate).
**Cross-refs:** `coordinator/_lidar_oss.py:session_photos_manifest` / `link_message_snapshot_photos`.

### Custom device-messages card for photo popup + detection overlay (follow-up to todo6 #4)

**Why:** Device-message snapshot photos are surfaced via a **markdown** card, which HA sanitizes — so
those thumbnails open the full image in a **new browser tab**, without the click-to-enlarge lightbox +
AI-detection bbox/label overlay that the gallery and replay cards now have (shared
`_dreame-map-core.js:attachDetectionOverlay`). A small custom card reading
`sensor.dreame_a2_mower_device_messages.items` would unify the UX.
**Done when:** a bundled `www/` custom card renders the device-messages list with per-message photo
thumbnails that open the same in-card lightbox + overlay; the markdown card is replaced on the Info tab.
**Status:** DONE 2026-07-16 — `www/dreame-a2-device-messages-card.js`; the strategy's `messages`
manifest routes `device_messages` to it via a new `card:` field (the other two message sensors carry
no photos and stay markdown). Bundled from the strategy's `CARDS` import list.

**Premise correction (found while implementing):** the "Why" above is stale. The markdown card did
NOT render new-tab thumbnails — it rendered **no photos at all**. The P5 strategy rewrite
(`34531701`) replaced the hand-written dashboards with the registry-generated strategy, and the
message-photo markdown never came across; the surviving template interpolates only
title/date/body. So `link_message_snapshot_photos` has been attaching signed thumbnails to
`items[].photos` that nothing displayed. This card is the first surface to render them —
a new feature, not the UX upgrade the entry describes.
**Live-verify (NOT done — no snapshot message since the change):** open the Messages tab and confirm
a snapshot message shows thumbnails that open the lightbox with the bbox overlay. The photo path is
covered only by the pure-logic harness (`tests/www/device_messages_harness.mjs`); the fixtures encode
the `items[].photos` shape read from `domain/media/gallery.py:signed_photo_thumb`, not a live payload.
**Cross-refs:** `www/dreame-a2-photo-gallery-card.js` (lightbox+overlay pattern),
`www/_dreame-map-core.js:attachDetectionOverlay`; the strategy's Info-view
device-messages card (`www/dreame-a2-strategy.js`, `messages` manifest section);
`sensor.dreame_a2_mower_device_messages` (`items[].photos`).

### Dedicated faults/attention dashboard view (post-P5 feature idea, R-65/T6-23 — not built)

**Why:** the P5 dashboard strategy (`www/dreame-a2-strategy.js`) surfaces error/attention
state inline on Overview + Diagnostics, but there's no standalone view that lists active
faults, the error-tier persistent-notice history, and the fault catalog's tier/category for
each — which would give a single place to triage "what's wrong right now."
**Done when:** a new strategy view (e.g. "Faults") lists active + recent fault_catalog-derived
events (tier/category/severity) with a clear/dismiss action, wired the same way the strategy
resolves other manifest sections (registry-driven, no hardcoded entity_ids).
**Status:** open — idea only, deliberately deferred out of P5 scope.
**Cross-refs:** `mower/fault_catalog.py` (tier/category/severity SoT); `domain/faults.py`
(persistent-notice posting); `www/dreame-a2-strategy.js` (where the view would be added).

### Bundle `_CoreMixin.__init__` attrs into typed per-concern objects (Refactor Phase 3f attr-bundling — deferred as over-engineering)

**Why:** The refactor plan (`spec.md §4 Phase 3f`) proposed extracting `_CoreMixin.__init__`'s
~69 `self._foo` attrs into typed per-concern objects (`self.render`, `self.wifi`,
`self.session`, `self.rain`). A ground-truth scope 2026-06-15 (agent `a2a58b2`) found the
**full bundling is near-zero net readability gain + real silent-breakage risk** for this
single-user repo, so only the safe core shipped (Slice A: CLAUDE.md table regen + dead-seed
cleanup). The attr-bundling itself was **deferred** (user-confirmed 2026-06-15). Findings:
  - ~25 of the 63 private attrs are consumed by the **entity/camera/service layer**, many via
    **string `getattr(coordinator, "_foo")`** (e.g. `"_active_map_id"`, `"_wifi_archive_index"`,
    `"_picked_session_summary"`, `"_last_notification"`) — a move silently breaks these with NO
    test or type-checker failure. Any bundling MUST first enumerate + fix those sites and/or
    leave `@property` shims (which re-flatten the surface you just bundled → ~zero net gain).
  - The cross-mixin **spine** (`data`, `cloud_state`, `_active_map_id`, `live_map`,
    `state_machine`; 4–7 mixins each) **can't be bundled** — it's the coordinator's real
    contract — so even "full" bundling leaves the god-object coupling intact.
  - >50 test files build the coordinator via `object.__new__` + hand-seed init attrs by name
    (heaviest: `tests/integration/test_coordinator.py`, ~43 seeds). A bundling breaks them all.
  - **Prerequisite if ever done:** first land a shared `make_bare_coordinator()` test helper
    (the 3e code-quality reviewer's suggestion) so the ~50 `__new__` fixtures seed init state
    in ONE place — then an attr move is a one-file change. This safety-net is also worth doing
    standalone to kill the recurring "new init attr breaks ~8 fixtures" tax.
**Done when:** EITHER a cohesive subset (render-cache / wifi-archive) is bundled behind verified
`@property` shims with every entity-layer string-getattr site updated + the test-helper safety
net in place, OR this is explicitly closed as not-worth-it. Best folded into the eventual
real-3d (spec §5 single-ingestion-funnel) rather than done alone.
**Status:** deferred (over-engineering for the payoff; user-confirmed 2026-06-15).
**Cross-refs:** `/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/superpowers/refactor-2026-06-13/spec.md` §4 Phase 3f;
`coordinator/_core.py` `_CoreMixin.__init__`; `feedback_no_migration_overengineering`;
the Phase-3d dedup (step 1), now resolved/closed — see DONE.md "State-container dedup
(Phase 3d step 1)".

### Split residual `MowerState` into per-domain dataclasses (Refactor Phase 3d, step 2 — deferred)

**Why:** `MowerState` (`mower/state.py`) is a single flat `@dataclass(slots=True)`
of ~154 fields. The refactor design (`spec.md §4 Phase 3d`) proposed (step 1)
deduping the StateSnapshot↔MowerState overlap, then (step 2) splitting the
residual into per-domain dataclasses — `Settings` (~70 CFG fields), `Telemetry`,
`SessionRefs`, `Consumables`, `Diagnostics` — behind re-export shims.
**Both steps are deferred** as of 2026-06-14. Step 1 (the dedup) turned out NOT
to be a safe "delete dead duplicated fields behind shims" change — see the
sibling TODO "State-container dedup (Phase 3d step 1) is a data-flow
rearchitecture, not a shim-able dedup" — it is entangled with 3e + the
single-ingestion-funnel and was sequenced after 3e. Step 2 (this split) was
deferred by the user as the right *long-term* goal but a big lift now. The
motivation is **readability** and a **closer structural match to the upstream
cloud/CFG keys and values** (one dataclass per upstream concern makes the
field→wire-source mapping legible instead of a 154-field flat bag).

**Pros (from the Phase-3d scoping pass, agent `ace9efd0`):**
  - Readability: 140 flat fields → 5 named domains; the field→upstream-source
    mapping becomes self-documenting (esp. the ~70 `Settings`/CFG fields).
  - Better alignment with upstream keys/values — the stated reason to do it.
  - Each domain dataclass can carry its own provenance/freshness if ever needed.

**Cons / cost (why it was deferred, not dropped):**
  - High churn: ~172 `coordinator.data.<field>` access sites + ~84 test files
    import `MowerState` directly. A split needs either accessor shims
    (`state.settings.x` AND a back-compat `state.x` property) or a sweeping
    rename across all sites.
  - `dataclasses.replace(self.data, …)` is used pervasively as the single write
    funnel; nested dataclasses make `replace` two-level (replace the inner, then
    replace the outer) at every write site — a real ergonomic regression unless
    wrapped.
  - On-disk/serialization touch: `settings_snapshot` (`coordinator/_snapshot.py`)
    reads ~30 fields by string name; the archive/restore paths and
    `test_card_contract` construct `MowerState()` directly.
  - Contradicts `feedback_no_migration_overengineering` *for the mechanical
    benefit alone* — so only worth it for the readability/upstream-match payoff,
    which is the explicit goal here (do it as a readability investment, not a
    correctness fix).

**Suggested approach when picked up:** keep the flat `MowerState` name as the
public type; introduce the 5 domain dataclasses as *nested* fields OR as mixin
groupings, and provide `@property` pass-throughs for the highest-traffic fields
so the 172 access sites don't all churn at once. Drive it from
`entity-inventory.yaml` / the CFG key map so the domain assignment matches the
upstream source. Land it as its own gated branch with the public-API +
card-contract tests as the regression net.

**Done when:** `MowerState`'s fields are grouped into named per-domain
containers with each field's upstream source legible; all `coordinator.data`
readers + the 84 test imports resolve (via shims or a clean rename); full suite
green; no behavior change (dedup already shipped).
**Status:** deferred (long-term readability goal; user-confirmed 2026-06-14).
**Cross-refs:** `/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/superpowers/refactor-2026-06-13/spec.md` §4
Phase 3d; `mower/state.py`; `feedback_no_migration_overengineering` (the cost
caveat); the Phase-3d dedup spec/commit (step 1).

### Control honesty — residual follow-ups (core shipped 2026-06-04)

**Core DONE** (v1.0.22a4) and MOST follow-ups SHIPPED across v1.0.22a4–v1.0.23a6: the
provisional `device_write_unproven` flag; `o10` name + `actions.py` line-ref fixes;
`WRF`/`TIME`/`VER` diagnostic sensors; patrol trigger surfacing + correct typing + the
striped-background fix; the MQTT off-loop-render crash (`call_soon_threadsafe`); three
log-health sweeps; and the `_render_base` "never awaited" RuntimeWarning (confirmed a
side-effect of the fixed a3 raise — gone, no code change). See `DONE.md` "Make controllable
entities honest", `docs/research/control-honesty-audit-2026-06-03.md`, and the research
journal for the shipped detail. What ACTUALLY remains open:

1. **Finalize remaining uncertain classifications.** Reframed 2026-06-15 against inventory:
   the old WRP/LANG/AI_HUMAN "2026-05-09 r=-3 vs verified-live contradiction" is **resolved** —
   the `r=-3` was a wrong-envelope probe bug (`d:{value:[...]}` vs the bare `d:[...]`, debunked
   in inventory § PRE 2026-06-03), so the "no setter" reading was false. WRP
   (`select.rain_protection_resume_hours`) and LANG (`select.lcd_language` / `voice_language`)
   are now `control_mode: device_writable` (LANG typed write confirmed `[app-mitm:2026-06-09]`,
   wired in Phase A1). What remains:
   - **AI_HUMAN** — still `read_only_pending`, but NOT a wire unknown: it's a cloud
     chunked-batch boolean whose write path already exists in code
     (`coordinator/_writes.py:write_ai_human_enabled` → `write_chunked_key("AI_HUMAN", …)`) and
     is *deliberately* unexposed pending a feature decision. Action: decide whether to wire the
     switch; if yes, confirm the cloud write lands, then flip `CONTROL_MODES` + the entity-inventory
     row to `device_writable` (the sync test enforces both).
   - **Bucket B actions:** s5a2/3/4 (may 80001), op=200, op=10, op=12 — confirm they land
     (also clears the provisional flag on the shipped action buttons). Probe tooling:
     `tools/probes/probe_pre_write.py`.
2. **MISTA area fallback sensor — deferred (conditional).** Needs a dedicated cloud-fetch of the
   MISTA `cfg_individual` endpoint (not currently polled) and is mid-run-only (r=-1/-3 when idle,
   per `project_g2408_mista_decoded`). Build only if the s1p4 MQTT area stream proves unreliable.
3. **Patrol per-point cycles + auto-capture — surface effective values (no cloud read-source
   exists).** Reframed 2026-06-15 after an inventory audit: the gap is much narrower than
   "find the cloud source." Almost everything is already known — point id/coords/type/dwell
   (`cruisePoints` type=8: `{id,type:8,shapeType:5,path,time:60,etime:60}`, cloud-relayed), the
   auto-capture *mechanism* (`o=400 {on:1}` fires at patrol start, `[app-mitm:2026-06-09]`), the
   *photos* (`summary_photo_list` = 3 photos/point + `summary_photo_captured`), and the *effective*
   per-point cycle count + auto-capture are **reconstructable from telemetry** (cycles = count of
   in-place ~360° rotations in decoded s1p4 pose/heading; auto-capture = whether `photo_list`
   timestamps fall in the point's rotation window — both demonstrated on the 2026-06-03 2-cyc/ON
   vs 1-cyc/OFF run). The ONLY thing missing is the **authored per-point setting values** (the
   app's "Patrol Cycles 1/2/3" + per-point "Auto-Capture on/off" toggles) as a *directly-readable
   config*. **UPDATE 2026-06-16:** path (b) is effectively DONE — the authored write surface is now
   decoded (`CRUISED` CFG key `{idx, value:[-1, point_id, auto_capture(0/1), cycles(1/2/3)]}`,
   app-MITM; see DONE.md todo6 #6 + `inventory.yaml § CRUISED`). What's still missing is a CRUISED
   *read-back* (none captured), so surfacing the *displayed* value needs optimistic local state from
   our own writes OR the telemetry reconstruction (path a). The "find the authored source" question
   is therefore CLOSED (CRUISED) — see DONE.md "Surface authored patrol per-point cycles".
   **Done when:** OPTIONAL — if the patrol-points sensor is ever to show effective cycles/auto-capture,
   derive via path (a) reconstruction or mirror our own CRUISED writes; otherwise leave
   `cycles:null`/`auto_capture:null`. No protocol unknown remains — and the readback IS available:
   not via `m:g t:CRUISED` (that returns `r=-3`) but via the `CRUISE.0` device-data key
   (`{num:cycles, ap:auto_capture}` per point, `FINDING-cruise-config-readback-2026-06-16`). Surfacing
   it is tracked as the dedicated "Surface patrol per-point cycles … from CRUISE.0 device-data" item above.
   **Cross-refs:** `inventory.yaml § CRUISED` / `§ o107` / `§ o111`; DONE.md "Surface authored patrol
   per-point cycles" + todo6 #6; `reference_app_api_probe`.
4. **Patrol render/timing polish** (render-side, minor; overlaps "Patrol Logs" + "Surface
   dock-departure repositioning UX"):
   - replay doesn't VISUALISE the on-the-spot 360° spins — the local track DOES capture them
     (consecutive points at the same (x,y) with rotating heading) but they draw as a stationary
     dot; show heading/rotation at fixed points.
   - trail starts ~48s late (no dock→first-point leg; the mower reorients ~48s emitting no s1p4) —
     seed the trail with the dock position at session start.
   - live-map background stays green ~50-90s after the mower docks (follows session state through
     the dock-return + OSS-fetch finalize window) — could flip to the idle preview as soon as
     docked+charging.

**Cross-refs:** `control_honesty.py` (`CONTROL_MODES` single SoT); `entity-inventory.yaml`
(`control_mode` per row); `docs/research/wire-captures/{settings-surface-cloud-only,
cfg-write-regression}-2026-05-09.md`, `pre-write-r3-2026-06-03.md`; the Phase-3 app-RPC TODO
below; auto-memory `project_control_honesty_markers`, `feedback_no_migration_overengineering`.

### s2p2 fault-surfacing — per-tier surfacing (P3 follow-up)

**Why:** P2 (2026-06-18) replaced the hand-curated `FAULT_CODES={2,4,5,23,31,36}`
with the app-derived error tier from `fault_catalog.fault_tier`
`[apk:g2408-plugin-ext1423]`. The error latch is now `is_fault(code) ==
(fault_tier(code) == "error")`, covering 26 codes
`{0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,17,20,21,22,23,24,26,37,59,73}`. 31
(back-charge-failed) and 36 (task-start-failed) are in the **alert** tier and no
longer latch ERROR. The remaining open work is per-tier surfacing:
- **Attention / alert / info tiers** (P3): surface non-error tiers
  (attention = consumable; alert = transient; info = lifecycle) beyond the current
  binary fault/non-fault split.
- **24 vs 54 rename:** `24 "Battery low"` is vague vs `54 "Low battery — returning
  to station"`. Hypothesis: 24 = warning threshold, 54 = the return trigger.
  (Recorded as an `inventory.yaml § s2p2` open_question; needs a capture of both
  firing in one session, then rename 24.)
**Done when:** per-tier surfacing is wired up and 24 renamed against live evidence.
**Status:** open (P3 deferred)
**Cross-refs:** `inventory.yaml § s2p2`; `mower/fault_catalog.py`; `mower/error_codes.py`.

### Confirm the share-messages record shape (live capture)

**Why:** The "Messages/Info" feature shipped (see DONE.md "Probe message-record/list…") —
Device / Service / Sharing message lists are now sensors + a dashboard tab. The Device and
Service parsers are wire-verified; the **share-messages** record field names
(`protocol/message_record.py:normalize_share`) are parsed DEFENSIVELY and not yet confirmed
against a real `GET /dreame-messaging/user/share-messages?version=v1` response (the account
may have 0 shares).
**Done when:** a live capture confirms the share record fields (id/title/date/body/link/read);
`normalize_share` is tightened + a fixture-driven test added; `inventory.yaml`
§ message_record_and_messaging_endpoints gets a verification.
**Status:** open (low priority — confirmatory; parser already works defensively)
**Cross-refs:** `protocol/message_record.py:normalize_share`;
`cloud_client/_fetchers.py:fetch_share_messages`; `tests/protocol/test_message_record.py`;
the plan's Task 7 (`OLD/ha-dreame-a2-mower-docs/superpowers/plans/2026-06-15-messages-info-tab.md`).

### OTA_INFO field semantics

**Why:** v1.0.0a100 surfaces `cloud_state.ota_status` as
`(int, int)` — the test fixture observed `(2, 100)`. We assume
the first field is a status code and the second is a percent (0-100).
**UNBLOCKED 2026-06-16:** a real OTA (0550→0625) was observed and the
**status-code enum is now confirmed** — the apk OTAState lineage
`0 UNDEFINED / 1 IDLE / 2 UPGRADING / 3 UPGRADE_SUCCESS / 4 UPGRADE_FAILED`
(see `inventory.yaml § s1p2 ota_state`, observed `1→2→3→1` live; `s1p3` = download %).
So `(2, 100)` reads as (UPGRADING, 100 %).
**Remaining (small):** (a) map `ota_status[0]` through that enum so the sensor
returns the state string (or exposes both); (b) confirm the cloud `ota_status`
tuple actually mirrors the MQTT `s1p2`/`s1p3` pair (it was not separately captured
during the OTA — the live capture was via the s1p2/s1p3 pushes). The device-firmware
UpdateEntity + `ota_state`/`ota_progress` sensors (v1.0.28a7) already surface the
MQTT path; this item is just the legacy `cloud_state.ota_status` tuple's string mapping.
**Done when:** the `ota_status` sensor returns the OTAState string (or both via attrs),
and the cloud-tuple↔s1p2/s1p3 correspondence is confirmed or documented as assumed.
**Status:** DONE 2026-07-16 (part (a) shipped; part (b) documented-as-assumed, the
`Done when` clause's sanctioned close — NOT captured).
`protocol/properties_g2408.py` gained `OTAState` + `ota_state_label()` (mirroring
`charging_label()`); both `sensor.ota_status` (cloud tuple) and `sensor.ota_state`
(s1p2 diagnostic) now render the label, with the raw code preserved in
`sensor.ota_status`'s `code` attribute. `MowerState.ota_state` still holds the raw
int, so `update.py`'s `== 2` in-progress check is untouched.
**Still open (b) — to CONFIRM on the next OTA:** diff `sensor.ota_status`'s `code`
attribute against `sensor.ota_state` on the same tick. If they disagree, the cloud
tuple is a different lineage and the `ota_status` mapping must be reverted
(the diagnostic `ota_state` mapping is confirmed independently and would stand).
**Cross-refs:** `inventory.yaml § s1p2 ota_state` / `§ s1p3`; DONE.md "Firmware update flow";
spec "Out of scope" item 5.

### Add integration icon via home-assistant/brands PR

**Why:** The HA Integrations page shows a blank square or nothing next to the
Dreame A2 Mower entry. Icons must come from `home-assistant/brands`, not the
integration's own folder.
**Done when:** A PR is merged to `home-assistant/brands` adding
`custom_integrations/dreame_a2_mower/icon.png` + `icon@2x.png`; the icon
appears on the Integrations page and in HACS.
**Status:** open
**Cross-refs:** upstream `home-assistant/brands` repo; source image at `/data/claude/homeassistant/dreame-a2-icon-large.jpg`

---

### Surface dock-departure repositioning UX

**Why:** The Dreame app shows a 3-stage popup ("Exiting the station" /
"Repositioning..." → "Reorienting" / "Repositioning Successful" → the task
message, e.g. "Starting to mow" for a mow, "Heading to maintenance point" for
op=109) at every dock departure, BEFORE the first move. No MQTT property
carrying this exact relocate-state has been identified — three dock departures
on 2026-05-05 produced no `s2p65` or `s5p104..107` events; the popup driver is
off the sniffed wire (cloud-only, like the Reorient popup).

**Partially shipped (2026-05-31):** the *command-time awareness* half is done —
on any task-start echo (`s2p50` status:true, op ∈ {100,101,102,103,108,109})
the integration now sets the task-appropriate `current_activity`, leaves the
`AT_DOCK` location (→ `ON_LAWN`), and switches the live map out of the striped
pre-start preview into trail mode IMMEDIATELY, instead of lagging ~45s until
`s1p4` position telemetry resumes (the undock reorientation silence). Applies to
all session types. See `mower/state_machine.py:_apply_s2p50_task_envelope`
(`_TASK_START_OPS`), `map_render/main_view.py` (`_is_active_non_mow_session`),
`coordinator/_mqtt_handlers.py` (command-time `_render_main_view`). This removed
a false `IN_SESSION+MOWING+AT_DOCK → CHARGE_RESUME` reconcile at startup.

**Wire signals IDENTIFIED (2026-05-31, user-annotated capture — see inventory
s2p1 verification):** the popup steps DO map to wire events (the op echo is at
the END of reorientation, not command-time):
  1. "Exiting the station"     = `s2p1 6/13→1 (working)` + `charge→not_charging`
  2. "Repositioning"           = app timer ~2-3 s later (no distinct wire event;
     ~40 s reorient turn, s1p4 silent)
  3. "Repositioning successful" = first `s1p4` MOVE + `s1p50 SESSION_BOUNDARY_PING`
     + `s1p51 DOCK_POS_UPDATE_TRIGGER`
  4. task message ("Heading to point"/"Starting to mow") = `s2p50` op echo +
     `s2p56` task-active

**Reorientation is INFERABLE, no wire message (2026-05-31 return-leg capture):**
the app's "Reorienting/Repositioning" popup is an inferred state = the window
between `s2p1` transitioning to a MOVING state and the first actual `s1p4` MOVE.
GENERAL across undock and return:
  - undock: `s2p1 → working(1)`  → ~40 s silent → first move
  - return (Recharge at point): `s2p1 standby(2) → returning(5)` → ~26 s silent → first move
So a "Repositioning" sub-state can be derived as: `s2p1 ∈ {1 working, 5 returning}`
AND no `s1p4` MOVE since that transition — covers both legs with one rule, no
cloud popup needed. (The return leg already labels activity **Returning** from the
`s2p1=5` transition; only the icon waits for `s1p4`. The `s1p1` heartbeat that lands
in the same second as an `s2p1` change is the documented "s1p1 fires extra
heartbeats on state transitions" — carries no repositioning info.)

**Remaining:** (a) extend the command-time awareness to key on the moving-state
transition (`s2p1→working` undock / generally the start signal) so the integration
reflects "Exiting the station" ~42 s earlier than the op echo (deferred
"Repositioning phase" / Option B — now unblocked); (b) confirm `s2p1→working(1)`
doesn't false-fire without a following task (gate with `charge→not_charging` if it
does); (c) decide whether to surface a distinct "Repositioning" activity/sensor
derived from the inference rule above (covers undock + return).
**Done when:** step-1 awareness is wired (or a decision to keep op-echo-only is
recorded) + the working(1) gating caveat is confirmed.
**Status:** command-time (op-echo) awareness DONE (v1.0.20a7); signals identified;
step-1 ("Exiting") awareness + caveat confirmation OPEN
**Procedure:** [docs/research/g2408-capture-procedures.md#3-active-mowing-s5p10x-sequence-capture](g2408-capture-procedures.md#3-active-mowing-s5p10x-sequence-capture)
**Cross-refs:** 80001 failure context — see the ARCHIVED overview at
`/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/research/g2408-protocol.md §1`
(current SoT: `inventory.yaml`); probe-log correlation needed

---

### Alert-tier event surface (follow-up to lifecycle PR)

**Why:** The lifecycle-tier event surface (a91) reserved
`event.dreame_a2_mower_alert` with empty `event_types`. Populate it
with `emergency_stop`, `lifted`, `tilted`, `stuck`, `bumper_error`,
`obstacle_with_photo`, `battery_low`, `battery_temperature_low`, `error`.
Add `CONF_NOTIFY` option toggle. Migrate the existing bespoke
`_handle_emergency_stop_transition` banner to a framework-managed
persistent_notification gated by CONF_NOTIFY.
**Done when:** All listed event_types fire from the appropriate
detection sites; `_handle_emergency_stop_transition` is replaced;
docs/events.md gains the alert section; emergency_stop banner
behavior is unchanged from the user's perspective.
**Status:** open
**Cross-refs:** `/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/superpowers/specs/2026-05-07-event-surface-design.md` § "Out of scope"

---

### Lifecycle event-surface PR — review-flagged cleanups

**Why:** The final whole-branch review of v1.0.0a91 (the lifecycle event
surface) flagged five non-blocking follow-ups that should not be lost:

1. **conftest.py placement** — `tests/event/conftest.py` stubs only
   `homeassistant.components.event` while the root `tests/conftest.py`
   already stubs every other HA component in one place. Fold into the
   root conftest for consistency.
2. **Unused `_attr_translation_key`** — both event entities set
   `_attr_translation_key="lifecycle"` / `"alert"` but `translations/en.json`
   has no `entity.event.*` block. Either add the translation entries
   or drop the unused keys.
3. **`_make_coordinator_for_persist_tests` fixture incomplete** —
   `tests/integration/test_coordinator.py` has three coordinator-stub
   fixtures; two set `_lifecycle_event` / `_alert_event` / `_prev_in_dock`,
   the persist one only sets `_prev_in_dock`. Latent foot-gun if a
   future test extends the persist case to call fire-paths.
4. **`mowing_ended` may double-fire on cloud md5 dedup hit** —
   `_do_oss_fetch` fires `_fire_mowing_ended` even when the cloud reused
   the md5 (dedup hit). The session was already finalized once; firing
   again is questionable. Add a guard or accept and document.
5. **`reason` heuristic in `mowing_paused`** — only emits
   `"recharge_required"` when `battery_level <= 20`; nullable
   `battery_level` always resolves to `"unknown"`. The threshold 20 is
   a magic number. Pull into a const, handle None explicitly, and
   consider expanding the reason vocabulary alongside the alert-tier PR.
**Done when:** Each of the five items is either fixed or explicitly
closed with a "won't fix because X" note.
**Status:** open
**Cross-refs:** final review on commit `e32c8f4..51f6883`;
`/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/superpowers/plans/2026-05-07-event-surface-lifecycle.md`

---

### Novel-observation sensor floods on continuous-integer slots

**Why:** `sensor.dreame_a2_mower_novel_observations` accumulated 51 entries
before a reboot 2026-05-07 and 5 since. All observed entries are
`category: value` for slots without a `value_catalog` — e.g. `s3p1`
battery_level (every new percentage triggers), `s5p107` energy_index
(int 1..250), `s1p53` bluetooth_connected (True/False both fire on first
observation). The registry's first-time-seen-value path is correct as
a log signal but is noise on the user-visible sensor.
**Done when:** The sensor's `observations` attribute filters out
`category: value` entries for slots whose `_INVENTORY.value_catalogs`
entry is None. INFO-level logging of those novelty events stays so
contributor diagnostics aren't lost.
**Status:** open
**Cross-refs:** `coordinator/_property_apply.py` (`handle_property_push` novelty dispatch);
`observability/registry.py`

---

### `edgeMowingWalkMode` — identify the app-side setting

**Why:** The cloud SETTINGS field `edgeMowingWalkMode` is exposed as
`select.<map>_edge_walk_mode` (values `walk_0` / `walk_1`), but no
toggle in the Dreame app appears to correspond to it. Curiously the
JSON key order in `SETTINGS.0` roughly matches the order of toggles in
the app's Mowing Settings screen, and `edgeMowingWalkMode` sits
between `mowingHeight` and `edgeMowingAuto` — which is where the app
shows "Mowing Direction" (the Standard / Crisscross / Chequerboard
selector). That direction selector is already wired to the
`mowingDirectionMode` field (our `Mowing Pattern` select), so
`edgeMowingWalkMode` is plausibly something different — perhaps a
hidden/A-B flag, an edge-walk strategy parameter, or a deprecated
field.
**Done when:** Physical test: run an Edge mow on the same map twice,
once with `edgeMowingWalkMode=0` and once with `=1`, and observe
whether the mower's edge-tracing behaviour differs (path shape,
direction, lap count, speed). Either confirm a behavioural delta and
characterise it, or confirm no observable delta and document the
field as cosmetic/no-op so we can decide whether to keep the entity.
**Status:** open
**Cross-refs:** `select.py` § `DreameA2PerMapEdgeMowingWalkModeSelect`;
`docs/research/cloud-discovery/2026-05-08-empty-list-batch-dump.json`
(field values observed: entry0/map0=0, entry0/map1=0, entry1/map0=1,
entry1/map1=1 — both states known to be accepted by the cloud).

---

### Audit protocol docs for debunked-knowledge leakage (corpus-validate conflicting claims)

**Why:** The s2p2=28 incident (2026-05-30) exposed a recurring failure mode:
a wrong reading derived from a **single biased log** ("28 = off-dock relocate
marker, fires 14/14 on every undock" — computed only from `probe_log_20260520`,
which happens to cover the worn-blade window) got promoted to a `verified:`
inventory entry and leaked into `error_codes.py`, the mova cross-check doc, and
the notification-history doc. The correct reading (28 = wear%-gated blade-wear
push) co-existed alongside it. A new session leaning on the "latest entry" nearly
re-propagated the wrong one. Two systemic risks: (a) conflicting doc entries where
"latest wins" silently regresses correct older info; (b) findings asserted from one
run that don't hold across the corpus.
**Done when:**
1. Sweep `inventory.yaml` + `docs/research/` for claims marked `verified` whose
   evidence is a **single** probe log, and re-validate each against the full
   corpus (`probe_log_*.jsonl`, 9 logs / ~66 undocks). Downgrade any that don't
   replicate corpus-wide to `partial`/`presumed` with a corpus note.
2. For every code/field with two or more conflicting `semantic:` or verification
   readings, add an explicit "current best reading + which older readings are
   superseded and why" so a future session can't silently pick the wrong one.
3. Document the rule in CLAUDE.md § Fact discipline: a wire-pattern claim is not
   `verified` from one run — it needs corpus-wide consistency; if it doesn't hold
   across the corpus it can't be confirmed. (Tooling: `_corpus.py` is a starting
   point — consider promoting it into `tools/`.)
**Status:** open
**Cross-refs:** `inventory.yaml § s2p2` (2026-05-30 retraction) + `§ s1p1`
(2026-05-30 corpus verification); `mower/error_codes.py` code 28; memory
`feedback_corpus_validate_protocol_claims`.

---

### Replace guesswork multi-variable state inferences with fact-based signals

**Why:** Reviewed (2026-05-30) every combination-gated state/action in
`mower/state_machine.py` + the `coordinator/` session handler. Most combinations are
**fact-based and fine** — keep them:
- `_apply_charging`: charging=True → location=AT_DOCK (physical invariant). ✓
- `_apply_cloud_dock`: ignore a stale cloud AT_DOCK while IN_SESSION+ON_LAWN (the
  5-10 min cloud DOCK lag is observed). ✓
- `_apply_s2p1_task_state`: s2p1=6 → CHARGE_RESUME vs IDLE by mow_session (real
  distinction; collapses two facts into one activity enum but the logic is sound). ✓
- `_apply_s2p56_lifecycle`: stage=2 + CRUISING_TO_POINT → AT_POINT (good composition:
  generic stage field + task type → meaning; redundant-but-consistent with s2p2=75). ✓

The **guesswork** combinations (your hunch — inference, not protocol fact):
1. `_reconcile_mow_activity` (state_machine.py ~434): IN_SESSION + MOWING + AT_DOCK →
   CHARGE_RESUME, comment literally "pick CHARGE_RESUME since that's how the mower
   behaves". Should read the actual charging/s3p2 signal, not guess from a triple.
2. `_reconcile_mow_activity` (~409): IN_SESSION + CHARGE_RESUME + off-dock + area>0 →
   MOWING — a 4-condition self-heal inference for a dropped MQTT push.
3. `_mqtt_handlers` (~376): pause **reason** = `recharge_required` if `battery<=20`
   (magic number, "best-effort") — should read the real pause cause (s2p2 in the pause
   window), not infer from battery. (Already noted in the lifecycle-review TODO.)
These are RECOVERY heuristics (self-heal stuck state from missing signals — see the
state-machine-audit), so they're load-bearing; **don't rip them out blindly**, replace
each with the fact-based signal where one exists, otherwise label it explicitly as an
inference fallback.
**Done when:** items 1-3 either read a direct signal or are explicitly marked
"inference fallback (no direct signal)"; a quick pass over `coordinator/_session.py`
finalize gate + `live_map/finalize.py` decide() confirms no other guesswork combos.
**Status:** open
**Cross-refs:** `mower/state_machine.py § _reconcile_mow_activity`;
`coordinator/_mqtt_handlers.py` pause-reason; memory `project_state_machine_audit`;
DONE.md "Decouple the s2p2 71/31/33 state model".

---

### Audit for misleading authoritative-sounding names on unverified/wrong meanings

**Why:** A sibling to the debunked-knowledge audit, but specifically about *names*:
apk/vacuum-derived identifiers that read as fact while the meaning is unverified or
wrong. Confirmed instances this session: s2p2=28 (off-dock-marker → blade-wear),
s2p2=71 (positioning_failure → standby-return), s1p1 byte[14] (startup_state_machine
→ locomotion_state), CMS[3] (Link Module → unidentified). Standing risks:
- `s2p2=20` is correctly flagged "NOT battery" in inventory + probe_a2_mqtt.py, BUT old
  probe jsonl entries have the stale `BATTERY_LOW` label baked in at capture time — a
  reader scanning a 05-25 log sees a wrong label with no caveat.
- Vacuum-side s4p* names (cleaning_mode, pet_detective…) for slots g2408 never emits.
- Hypothesized names in `mode_enum` / `s2p1 value_catalog` / other surfaces that aren't
  covered by the error_codes CI gate (see below).
- Analyzer labels in `probe_a2_mqtt.py` — unverified names baked into log output.

**DONE (2026-06-01) — `mower/error_codes.py` + `inventory.yaml § state_codes`:**
The 20 vacuum/apk-lineage s2p2 names (37/38/39/40/41/44/45/46/49/57/58/59/61/62/
64/65/66/67/78/117) that were never observed on g2408 have been deleted from
`ERROR_CODE_DESCRIPTIONS` and `S2P2_EVENT_TYPES`. `inventory.yaml § state_codes` is
now fully reconciled — complete per-code confidence, confirmed rows for 1/2/9/23/
28/30/36/74/76, partial rows for 0/24/47, corrected 63/73. A CI gate
(`tests/inventory/test_error_codes_confidence_gate.py`) now enforces that every
s2p2 code described in `error_codes.py` must have a `state_codes` row with
`decoded: confirmed` or `partial`; a `hypothesized`/`unknown`/absent code must NOT
appear — see `CLAUDE.md § error_codes confidence gate` for the durable rule.

**Still open:** the same misleading-name pattern in `inventory.yaml § mode_enum` /
`s2p1 value_catalog`, vacuum-side s4p* slots, `probe_a2_mqtt.py` analyzer labels,
and the old-probe-log stale `BATTERY_LOW` caveat. The gate PATTERN (cross-check
code-surfaced names against `inventory.yaml decoded` status) can be extended to
those surfaces when they're next touched.

**Done when (remaining):** a sweep of `inventory.yaml` (mode_enum / other non-state_codes
surfaces) and `probe_a2_*.py` flags every authoritative-looking name whose meaning is
`hypothesized`/`unknown`/contradicted and either neutralizes it or annotates it inline.
**Also (housekeeping, bundle while touching the probe tools):** the probe scripts
write log files (`probe_log_*.jsonl`) into `/data/claude/homeassistant/` root, which
is cluttered with test/log/temp files. Update the probe tooling to write into a
subdirectory (e.g. `probe_logs/`), and consider the same for the throwaway analysis
scripts (`_corpus.py`, `_reorient.py`, `_s1p1.py`, `_win.py`, …). Keep paths the
analysis scripts read in sync.
**Status:** in-progress — `error_codes.py` + `state_codes` done (CI-gated); other surfaces remain open
**Cross-refs:** `inventory.yaml` § state_codes (s2p2_37..117 hypothesized names);
`mower/error_codes.py`; `probe_a2_mqtt.py` (+ log-path); `docs/research/mova-mower-a1-crosscheck-2026-05-25.md`;
`tests/inventory/test_error_codes_confidence_gate.py`; sibling: "Audit protocol docs
for debunked-knowledge leakage"; memory `feedback_corpus_validate_protocol_claims`.

---

### s2p1 mode enum vs apk table — reconcile remaining conflicts + s2p56 umbrella question

**Why:** Folded in from `things.txt`. The apk's product-agnostic mode table lists
`3: "Working"`, but the probe corpus shows s2p1=3 always co-incident with s2p56
status `[[1,4]]` — decoded as "Paused" in `inventory.yaml § s2p1` (5 observations,
2026-04-17 and 2026-04-22/28/29). Value 16 ("Battery Temp Hold") is also ours, not
in the apk table. The label side is mostly reconciled already; the open part is the
**s2p56-vs-s2p1 relationship** — s2p56 also carries a task value, so one may be an
umbrella state ("in a session but currently charging") over the other. Side note
worth keeping: this is the *only* enum table the app exposes that is product-type
agnostic; every other table is vacuum-worded.
**Done when:** the s2p1↔s2p56 relationship is documented (is s2p56 the
session-umbrella state and s2p1 the instantaneous activity, or vice-versa?), and any
remaining apk-vs-wire label conflicts are annotated in `inventory.yaml § s2p1` /
`§ s2p56`.
**Status:** open (low priority — labels largely resolved; see `inventory.yaml § s2p1`)
**Cross-refs:** `inventory.yaml § s2p1`, `§ s2p56`; was `things.txt`.

---

### `summary_map[boundary_layer].track` over-segmentation — identify the break trigger

**Why:** The cloud's session-summary track field over-segments the mow path: in a
48-min Map 2 sample (2026-05-09), 27 single-point / 43 two-point / 24 three-point
segments out of 150 sit ON the eventual continuous trail (not outliers). The user's
read is "they appear to show something significant" — could be a load-bearing signal
we discard (pen-up / blade-state change / phase boundary / AI-obstacle proximity /
cloud heartbeat).
**Done when:** the break trigger is identified (the five candidate triggers + s1p4
decode steps are catalogued in `inventory.yaml § summary_map_track.open_questions`),
and the segments are either surfaced as a signal or documented as cloud-noise. NB the
replay card already filters <2-point legs, so this is a protocol question, not a
display bug.
**Status:** open (low priority)
**Cross-refs:** `inventory.yaml § summary_map_track.open_questions`;
`protocol/session_summary.py`; `live_map/trail.py`; memory
`project_track_oversegmentation_todo`.

---

### Session calendar — one-tap replay card

**Why:** The Sessions tab uses the HACS `atomic-calendar-revive` card, so
replaying a session is two surfaces / two clicks (find it on the calendar →
match the label in the Replay picker dropdown → tap). One-tap-from-the-calendar
isn't possible with either the HA-native `type: calendar` (hard-coded more-info
popup) or atomic-calendar-revive (its `tap_action` fires the same call for every
event — no per-event `{{event.summary}}` substitution). Both confirmed
2026-05-13.
**Done when:** a bundled custom JS card
(`www/dreame-a2-session-calendar.js`, registered like the existing lidar/schedule
cards) renders a month grid from `calendar.dreame_a2_mower_sessions` and, on a
session tap, calls `select.select_option` on `select.dreame_a2_mower_work_log`
with the event summary — driving the existing replay camera. Drops the
atomic-calendar-revive dep. (~half-day; the work_log label match is pinned by
`tests/integration/test_calendar.py`.)
**Status:** open (low priority — UX nicety).
**Cross-refs:** `www/dreame-a2-lidar-card.js` (bundled-card pattern);
`calendar.py::_event_from_entry`; archived design
`OLD/ha-dreame-a2-mower-docs/research/session-calendar-todo.md`.

---

### Which stored dense LiDAR map does the Dreame app display?

**Why:** Split off from the resolved "Live dense 3D/LiDAR map surface" item (see DONE.md): we
already have the dense LiDAR point clouds (the `.0550.bin` 3dmap snapshots). Open question: when
several snapshots exist the app shows one specific dense map and it's unclear how it chooses.
Working hypothesis: the snapshot with the most points that isn't too old. Cosmetic — affects which
map the HA LiDAR camera should prefer, not availability.
**Done when:** the app's dense-map selection rule is identified, OR a sensible heuristic (e.g.
newest-with-most-points) is chosen for the HA LiDAR camera and documented.
**Status:** open (low priority)
**Cross-refs:** `coordinator/_lidar_oss.py`; `inventory.yaml` `s2.50 OBJ 3dmap`; DONE.md "Live dense
3D/LiDAR map surface".

---

### Photo/video archive — dashboard surfacing, the 3 photo sets, overlays, session-linking, boot backfill

**Why:** Folded in from `todo1.txt`. The OSS photo/video archive BACKEND shipped
(album-photos feature + person/patrol/obstacle categorisation, 1 h
`_refresh_oss_gallery` sync, quota/count sensors — see memory
`project_app_capture_phase1`). The open work is surfacing + completeness across the
**three distinct photo sets** the device produces:
  1. **Patrol photos** — long-term; shown in the app's archive (photo + video tabs).
  2. **AI Obstacle photos** — long-term; shown in the SAME app archive alongside
     patrol, with a class+confidence overlay.
  3. **Normal obstacle photos** — captured every time the mower works around an
     obstacle DURING a session. In the app these are ONLY reachable by tapping an
     obstacle icon in the LIVE session view; once the session ends the icons are no
     longer clickable, so there's no access. They are almost certainly still stored
     cloud-side and must be captured + retained too (this 3rd set may not yet be
     covered by the shipped categoriser).
**Sub-items (todo1.txt 1-4):**
  - **Dashboard surfacing** — ✅ DONE. `dreame-a2-photo-gallery-card.js` renders the
    gallery with per-category filter tabs (AI·Human/Animal/Object, Obstacle, Patrol,
    Manual) + a Videos tab + click-to-enlarge lightbox.
  - **Link photo sets to sessions** — ✅ DONE for the long-term patrol/AI sets
    (2026-06-16, todo6 #3 Part B): `session_photos_manifest` matches a session's
    `photo_list` and surfaces thumbnails on the replay screen. The EPHEMERAL 3rd set
    (below) is not linkable until it's captured.
  - **Boot backfill** — ✅ DONE. `_core.py` runs `_refresh_oss_gallery(max_pages=400)`
    at startup (full history) in addition to the hourly forward sync.
  - **Photo overlays** — ✅ DONE (2026-06-16): the gallery + replay lightboxes draw the
    JPEG-COM `detections` as a bounding box + `"79% - person"` label via the shared
    `_dreame-map-core.js:attachDetectionOverlay`. Date shows in the caption.
**What actually remains — the ephemeral "normal obstacle" 3rd set:** captured every time
the mower works around an obstacle during a session, reachable in the app ONLY by tapping a
live-session obstacle icon (icons die at session end). Its upload/fetch mechanism is UNKNOWN
(NOT the patrol lazy-upload path — see the obstacle-icon open question under the device-message
linking work) and it is NOT in the shipped categoriser/gallery. Until that mechanism is
captured it can't be archived, surfaced, or session-linked.
**Done when:** the 3rd (ephemeral obstacle) set's cloud mechanism is identified, then it is
captured + surfaced + session-linked like the other two — OR confirmed unreachable and documented.
**Status:** open — surfacing/overlays/backfill/long-term-linking all SHIPPED; only the 3rd
ephemeral obstacle-photo set (capture mechanism unknown) remains.
**Cross-refs:** the (resolved) "Probe for the AI-photo / obstacle-photo cloud
endpoint" item above; "Patrol Logs" T4 (Auto-Capture photo retrieval) + the
session-format brainstorm; memory `project_app_capture_phase1` /
`project_g2408_ai_photo_probe`; `archive/videos.py`, `_refresh_oss_gallery`,
`protocol/photo_meta`; `docs/research/g2408-app-capture-playbook-2026-06-09.md`.

---

### Live video stream + snapshot/record — camera entity (Tencent XP2P)

**Why:** The app shows a live camera feed whenever the mower is off the dock, with
in-app photo/video capture buttons (captures land in the OSS gallery). The g2408 HAS
a camera — `feature:"video_tx"`, vendor `tx` = Tencent IoT Video — confirming the
earlier "no camera module on g2408" notes were stale (now retracted across
`inventory.yaml` s4p22/s4p44/s4p59/s4p83 + the s2p55 IPC clarification). The full
session-establishment chain is **wire-verified and captured**; the only uncaptured
piece is the raw media payload, which is Tencent XP2P / TRTC P2P-over-UDP (off-relay
by design) and needs the Tencent IoT-Video XP2P SDK to consume.

**What's captured (control plane, all on `eu.iot.dreame.tech:13267`):**
- Enable/disable: routed action `o=400 {on:1|0}` (auto-fires at patrol start;
  `o=15 {c:0|1}` is the separate remote-control-mode camera toggle).
- Cred chain on `dreame-third-video/tx/*`: `user/accesstoken` → `dev/isDevUser`
  → `mgr/dev/getIdentity` (secretId/secretKey/deviceId/deviceName/productId)
  → `dev/getP2PInfo` (XP2P connect string; SDK v2.4.49). Order: 1→2 at app start,
  3→4 just before live view; accesstoken ≈ 7-day life, p2pInfo per-session.
- Snapshot/record: client-side frame/clip grab → `iotoss/addOssNew` (signed PUT)
  → PUT → `iotoss/ossUploaded`; 60 s record cap; retrievable via `userDidOssList`.
- Two-way "Talk" audio and ambient audio ride entirely over the P2P stream — ZERO
  control command on the wire.

**Done when:** EITHER (a) a `camera` entity drives live view — run the `o=400` + cred
chain, feed creds + p2pInfo into an XP2P/IoTVideo P2P client usable from Python/HA,
expose still+stream, `o=400 {on:0}` + close on stop; OR (b) if no viable Python XP2P
client exists, the live-preview half is explicitly deferred and only the pure-HTTP
**snapshot/record + gallery playback** is built (fully reproducible without the SDK).
Either way the decision + rationale is recorded.

**Open questions / blockers:**
- **XP2P SDK in Python is THE blocker** — Tencent's SDK is C/Java/iOS-first; live
  preview is not implementable until a binding or P2P-handshake reimpl exists. The
  HTTP capture/gallery features are not blocked by this.
- Stream codec/container (H.264 vs H.265) — needed to wire an HA camera/stream.
- `sign` algorithm for the video endpoints assumed identical to the integration's
  existing Dreame request signer — confirm the `dreame-third-video/tx/*` endpoints
  accept the same scheme. `addOssNew.pwd` purpose unconfirmed. [UNVERIFIED]

**Status:** open (control-plane setup fully captured; live preview blocked-by-XP2P-SDK;
HTTP snapshot/record/gallery feasible now). Roadmap row G ("Live camera") — attempt last.
**Cross-refs:** `docs/research/live-video-stream-setup.md` (wire-verified handoff,
authoritative); `inventory.yaml` § `api_endpoints` (`tencent_video`, `oss_manual_upload`,
`oss_photo_list`, `oss_storage_quota`) + § `opcodes` (`o400`) + § s4p22/s4p44/s4p59/s4p83
(camera-presence corrections); `OLD/from-mitm-claude/live-video.txt` (raw Mac-MITM notes
this was folded from); `docs/research/app-integration-roadmap.md` row G; the Photo/video
archive item above (shares the OSS gallery).

---

### Phase 3a DEFERRED — move the render transform out of `map_decoder` + unify zone types

**Why:** The P3a frame-untangle (2026-06-14) shipped only the SAFE, render-output-
preserving subset (folded `_render_*` into `map_render/`, added the Python↔JS
projection-parity test, JS cleanup, card version banners + camera `schema_version`).
Two genuinely render-output-CHANGING pieces were explicitly DEFERRED because the
mower is dead and the plan's Checkpoint-3a requires a **live HA map-render visual
confirmation** (there is no golden-image test, so a compositing/orientation
regression wouldn't be caught automatically):
  1. Move rotation + midline-reflection OUT of `map_decoder.py` into a `map_render`
     presentation step — make `ExclusionZone.points` / `SpotZone.points` / `dock_xy`
     raw-cloud-mm, relocate the transform, and handle the bbox-expansion-depends-on-
     post-rotation-corners coupling at `map_decoder.py:716-729`.
  2. Unify `ExclusionZone` / `SpotZone` / `MowingZone` into one Zone type (only clean
     AFTER step 1 makes them all raw-frame).
**Done when:** with a live mower, the transform is relocated and a live HA map render
is visually confirmed unchanged (lawn/zones/dock/obstacles land identically); the new
`tests/www/test_projection_parity.py` still passes (it is the regression gate for the
transform-move); zone types are unified with all existing render/decoder tests green.
**Status:** UNBLOCKED 2026-06-16 — the mower is live again (mowed + patrolled + OTA'd
0550→0625 this session; live map renders were exercised during the WiFi-overlay work). The
dead-mower blocker is gone; now open work, gated only on doing the relocation + a deliberate
before/after live map-render visual comparison — not on hardware availability.
**Cross-refs:** `/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/superpowers/refactor-2026-06-13/p3a-frame-spec.md` § "Explicitly DEFERRED";
`custom_components/dreame_a2_mower/map_decoder.py:716-729`;
`custom_components/dreame_a2_mower/map_render/_geometry.py` (`_cloud_to_px` /
`_renderer_to_px`); `tests/www/test_projection_parity.py`.

---

## In-progress

_(none currently)_

---

## Blocked

### `ai_obstacle` blob format

**Why:** `SessionSummary.ai_obstacle` is typed `tuple[Any, ...]` because no
captured session has produced a non-empty value. Need an AI-obstacle trigger
event to capture the wire shape.
**Still blocked after the 2026-06-16 session:** real **AI-human detections did fire**
this session (the `ai_human` gallery photos + "Human entry … View snapshots" alerts),
yet the session-summary `ai_obstacle` array stayed **empty in every capture** —
confirming the detection photos ride a SEPARATE channel (the OSS gallery /
`userDidOssList`), not the summary's `ai_obstacle`. So the trigger that populates
`ai_obstacle` in the OSS JSON is still uncaptured (it may require an *object/animal*
AI-obstacle on the path, distinct from a human-presence alert).
**Done when:** a session produces `ai_obstacle: [...]` in the OSS JSON;
fixture saved under `tests/protocol/fixtures/`; decoder and renderer updated.
**Status:** blocked-by-capture (need a non-empty `ai_obstacle` — human-presence alerts
do NOT populate it).
**Procedure:** [docs/research/g2408-capture-procedures.md#2-take-a-photo-flow-apk-s-takepic-vs-ha-integration-path](g2408-capture-procedures.md#2-take-a-photo-flow-apk-s-takepic-vs-ha-integration-path)
**Cross-refs:** `protocol/session_summary.py`; journal topic `apk cross-walk findings`;
DONE.md "Mowing direction" (closed by CFG.PRE[5]).

---

### Patrol Logs — remaining open items

**Trigger + capture + integration surfacing + activity-typing + photo retrieval
are closed — see `docs/DONE.md`** ("Patrol Logs — trigger and wire format" and
"Patrol Logs — activity typing, photo retrieval, app-tab"): a patrol is triggered,
captured, typed `session_type=patrol`, replayed, excluded from the "Mowing"
aggregates, surfaced as `patrol_edge`/`patrol_point` activities, and its
auto-capture photos render on the photo-archive dashboard tab. **T1, T2 and T4
are DONE and moved to DONE.md.** What remains:
**Remaining:**
- ~~App "Patrol Logs" TAB empty~~ — RESOLVED 2026-06-15: the tab now carries
  ~10–15 entries, matching our per-session replay captures (so it is fed by the
  same session-summary archive `[UNVERIFIED]` — count-parity, not a wire capture).
- Per-field OSS schema for patrol keys: mostly decoded — see
  `inventory.yaml § summary_point / summary_point_status / summary_complete_count /
  summary_photo_list / summary_photo_detected / summary_pref`. The s4 eiid1
  piid→summary cross-walk is still partial (piid10≈photo_detected, piid2=complete_count,
  piid14≈map_area, piid60=stop_reason); still need a `photo_detected=0` session to
  confirm piid10, and piid3/7/11/12/15 remain ambiguous.
- **[T3] ✅ DONE (2026-06-16).** Picker labels postfix the patrol subtype + actual
  run time, keeping `[Patrol]` as the primary tag: `[Patrol] [Map N] <ts> — Point / Dmin`
  (mode 107) / `… — Edge / Dmin` (108); either part omitted when unknown (legacy /
  non-echoed patrol → bare `[Patrol]`). Implemented via a new `ArchivedSession.mode`
  field (mirrored from raw_dict `mow_type_raw`, backward-compat `None`) +
  `session_card.py:format_session_label` (`_PATROL_SUBTYPE` derived from the
  `mode_enum` SoT). The work-log SELECT + calendar inherit it (shared helper).
  Tests: `tests/integration/test_session_label_type.py`,
  `tests/archive/test_session.py::test_index_entry_carries_mode_from_raw_json`.
  The MOW subtype postfix landed too (2026-06-16): `[Mowing] [Map N] <ts> —
  All areas / N.N m² / Dmin` (modes 100/101/102/103 → All areas/Edge/Zone/Spot,
  via `MOW_MODE_CODES`); omitted when mode unknown → original area-only format.
  Live index was backfilled with `mode` for all patrol + mow entries.
  **Nothing residual** — old entries without `mode` degrade gracefully to the
  bare/area-only form; `tools/session/rebuild_session.py` can backfill if ever
  wanted.

**[BRAINSTORM] Session title + archive-format design (decide before touching the
persisted format).** Scope agreed 2026-06-03; label design RESOLVED 2026-06-15 (see T3):
  1. **Subtype postfix in the picker title — ✅ DONE (2026-06-16, see T3).** Kept
     `[Mowing]`/`[Patrol]` as the primary tag and POSTFIXED the subtype (+ duration):
     `[Patrol] … — Point / Dmin`. The `[Patrol — Point]` / `[Mowing — Edge]` bracket
     form was NOT adopted. The MOW subtype postfix (`— All areas / N.N m² / Dmin`)
     also shipped 2026-06-16, so patrol and mow now match.
  2. **Scheduled vs manual visual differentiation:** considered, NOT now (start_mode
     is decoded; revisit later).
  3. **Can a patrol be scheduled?** RESOLVED — NO. The app's schedule UI offers only
     mow types (All areas / Zone / Edge mow); there is no patrol option, so a patrol is
     manual-trigger only `[app-ui@2026-06-03]`. No integration action now — patrol
     scheduling has no surface to model. (NB the classifier already handles a non-echoed
     patrol via `saw_patrol_start`/s2p2=51, so if firmware ever emitted a scheduled
     patrol it would still type `patrol` — defensive only.)
  4. **House per-point/edge settings + `photo_list`** on the patrol session record so
     they're tied to the session — photos are now reachable (T4 done), so this is
     UNGATED; the per-point settings remain reconstruct-only (T5).
  5. **Migration:** rebuild existing sessions via `tools/session/rebuild_session.py` once the
     format lands (the 2026-06-03 point patrol currently reads `[Mowing]` on disk).
- **[T4] Auto-Capture photo retrieval — ✅ DONE (2026-06-15, moved to DONE.md).**
  The "blocked-by-path / 479D-FDS subpath unknown" premise was debunked by the
  2026-06-09 app-MITM (photos live in the `dreame-eu` OSS album bucket); confirmed
  for patrol 2026-06-15 — 18 patrol photos render on the photo-archive dashboard tab.
  See `inventory.yaml § summary_photo_list` (`decoded: confirmed`).
- **[T6] Partial/interrupted edge patrol mis-typed `maintenance_run` ("To Point").**
  Observed 2026-06-03 on a real edge patrol (op=108) that was interrupted by a stuck
  event then by rain protection (OLD code — pre-T1/T3 deploy). It archived as a
  "To Point" session and finalized with location ON_LAWN although the mower was in
  fact docked. Two distinct defects to investigate (with POST-deploy data — re-test
  the edge patrol after the release):
    (a) **typing:** an op=108 patrol should classify `patrol`, but after a
    stuck/rain interruption it landed `maintenance_run`. Likely `last_task_op` got
    overwritten away from 108 by a return/cancel op AND `saw_patrol_start` (s2p2=51)
    didn't survive the interruption/session-split. Verify against the wire
    (`probe_log_20260520_131350.jsonl`, the ~21:xx edge patrol) — do NOT presume.
    (b) **location:** finalized ON_LAWN while docked — the dock-return s2p1 either
    wasn't seen or wasn't applied to the archived snapshot at finalize. Cross-ref
    `project_rain_reboot_session_fix`.
  Side observation (LEAVE debugging for now per user): rain protection appears to
  CANCEL a patrol (the app cancelled the session), unlike a mow which it pauses —
  TBD whether that's firmware behaviour.
- **[T5] Settings are reconstructable, not stored — SETTLED conclusion (no action).**
  Wire-confirmed (`inventory.yaml § o107` / `summary_point`): the per-point app
  settings (Number of Patrol Cycles, Auto-Capture) are command-only and absent from
  every reachable read surface (`summary_point.param` is `{}`). They are NOT
  fetchable — if per-point patrol info is ever surfaced, DERIVE it: cycles = count of
  in-place ~360° rotations at the point; auto-capture = whether `photo_list`
  timestamps fall in that point's dwell window. No probing or write-path work remains
  here; kept only as the derivation recipe.
**Procedure:** [docs/research/g2408-capture-procedures.md#4-patrol-log-trigger-investigation](g2408-capture-procedures.md#4-patrol-log-trigger-investigation)
**Cross-refs:** journal topic `s2p50 op-code catalog`; apk opcodes 107/108; DONE.md "Patrol Logs"

---

### Pathway Obstacle Avoidance test — CFG.BP / CFG.PATH semantics

**Why:** Two CFG keys (`BP`, `PATH`) still have placeholder semantics.
Hypothesis: they relate to Pathway Obstacle Avoidance. No pathways are defined
on the user's map so neither field has been observed changing.
**Done when:** A test pathway is created and toggled in the app; CFG snapshot
diff identifies which key(s) change and what values mean; entities added.
**Status:** blocked-by-test (user has no pathway defined; needs deliberate setup)
**Procedure:** [docs/research/g2408-capture-procedures.md#5-pathway-obstacle-avoidance-user-fakeable](g2408-capture-procedures.md#5-pathway-obstacle-avoidance-user-fakeable)
**Cross-refs:** journal topic `s2p51 multiplexed config — disambiguation evolution`; canonical § CFG keys

---

### P6: offline / restart last-known persistence + config availability (refactor-v2)

**Why:** Found during the P5.5 live eyeball with the mower away for repairs.
When offline, ~29 writable config switches + action buttons go `unavailable`
(correctly MQTT-gated since the P2 `is_connected` fix) and ~45 read-only values
go `unknown` — consumables %, lifetime totals, SIM status, network SSID/IP, dock
position, firmware version, DnD/charging/low-speed time windows. Confirmed NOT a
refactor regression: the persisted snapshot only carries state-machine fields
(session/battery/position/charging/errors), which are the ones that DO survive;
the rest are only populated by live cloud/MQTT fetches and were never persisted.
The result is a poor offline/restart dashboard (mostly blank). User ruling
2026-07-04: defer this hardening to P6 (it is a state + entity-availability
design change, not a dashboard tweak). A concrete inconsistency the split
produces (user-flagged): on the Diagnostics connectivity card `wifi_rssi_dbm`
shows a last-known value (−65 dB) while `wifi_ssid`/`wifi_ip` are blank — because
RSSI lives in the PERSISTED state-machine snapshot (s1p1 heartbeat byte[17]) and
is restored on boot, whereas SSID/IP are MowerState-only (NET fetch) and are not
persisted. Resolve the whole connectivity group ONE way (all last-known, or all
`unknown`/stale-gated) rather than the current per-field split. Same class: a
stale persisted value can read as "connected" when the mower is away — decide a
freshness/staleness policy for restored snapshot fields.
**Done when:** slowly-changing read-only values (consumables, totals, SIM, dock,
firmware, device-wide time windows) survive a restart-while-offline showing
last-known; AND config switches present last-known state (failing only the
write) instead of `unavailable` when the mower is offline — OR a deliberate
decision is recorded that a subset must stay `unavailable`. Includes persisting
`_active_map_id` so `domain/boot.py:render_base` produces the Overview live-map
base offline (today it early-returns because the active map is unknown offline;
the per-map `*_base` cameras already render each map). No behaviour change while
online; corpus IDENTICAL.
**Status:** open (deferred from P5.5 to P6)
**Cross-refs:** `state/snapshot.py` (persisted StateSnapshot); `domain/render.py:render_base` (+`_active_map_id`); entity `available` props on the settings switches; memory `project_refactor_v2_2026_07_02`; `.superpowers/sdd/progress.md` P5.5 findings.

---

### Pillow 14 deprecation deadline (2027-10-15) — `Image.getdata()` in the test suite

**Why:** Pillow 14 is scheduled to remove `Image.Image.getdata()` on 2027-10-15
(the warning text: `Image.Image.getdata is deprecated and will be removed in
Pillow 14 (2027-10-15). Use get_flattened_data instead.`). A 2026-07-05 audit
(refactor-v2 P6.5a, R-67) checked the codebase against the Pillow-14 removed/
deprecated API surface — `textsize`/`multiline_textsize`, `ImageFont.getsize`/
`font.getsize`, the removed `Image.ANTIALIAS`/`Image.LINEAR`/`Image.CUBIC`
resampling aliases, `Image.frombuffer`/`tobitmap` raw-mode usage, and
`ImageDraw.getfont` — with Pillow 12.1.1 installed (`python -c 'import PIL;
print(PIL.__version__)'`).
**Findings:**
- **Production rendering code is clean.** `map_render/base_map.py`,
  `main_view.py`, `work_log.py`, `stripes.py` use only current, non-deprecated
  API: `ImageDraw.Draw`, `ImageFont.truetype`/`load_default`,
  `draw.text`/`.polygon`/`.line`, `Image.new`/`.open`/`.alpha_composite`/
  `.composite`/`.transpose`, and the resampling constant `Image.BICUBIC`
  (`base_map.py:352`) — confirmed still a live, non-deprecated top-level alias
  of `Image.Resampling.BICUBIC` under Pillow 12.1.1 (no `DeprecationWarning` on
  access), unlike `Image.ANTIALIAS` which Pillow already removed. No
  `textsize`/`getsize`/`getfont`/`frombuffer`/`tobitmap` hits anywhere in
  `custom_components/`. The lone `.getsize(` grep hit is `os.path.getsize` in
  `cloud_client/_helpers.py:50` (filesystem, unrelated to PIL).
- **The TEST SUITE does use a Pillow-14-removed call**, confirmed by running
  `pytest tests/ -W always::DeprecationWarning -k render`: `Image.getdata()` is
  called in 15 sites across 9 files — `tests/map_render/test_render_base.py:95`,
  `tests/protocol/test_m_path_render.py:50,68,83,104,151`,
  `tests/protocol/test_nav_paths_render.py:71,86`,
  `tests/protocol/test_patrol_render.py:29`,
  `tests/protocol/test_render_base_with_obstacles.py:67,107`,
  `tests/protocol/test_render_dark_green_base.py:62`,
  `tests/protocol/test_render_traversal_visible.py:72`,
  `tests/protocol/test_render_work_log_uses_split.py:78`,
  `tests/integration/test_work_log_render.py:52`. All are test-only pixel
  assertions (`set(img.getdata())` / `list(img.getdata())` / pixel-membership
  checks) — none are in shipped `custom_components/` code.
**Conclusion:** no Pillow-14-removed API in use in shipped code as of Pillow
12.1.1; the only removal-scheduled call site is `Image.getdata()` in 9 test
files (15 sites, listed above), which the Pillow 14 changelog says to replace
with `get_flattened_data()`.
**Done when:** the 15 `.getdata()` test call sites are switched to
`get_flattened_data()` (or whatever Pillow 14's stable replacement API turns
out to be) before Pillow 14 ships, and a follow-up grep confirms no new
deprecated call sites were introduced in the interim.
**Status:** open (deadline 2027-10-15; low urgency — 2026-07-05 audit found the
gap is test-only, production code is already clean).
**Precaution:** re-audit if a Pillow `DeprecationWarning` surfaces in the render
tests before then (run `pytest tests/ -W always::DeprecationWarning -k render`);
consider pinning `pillow<14` in `manifest.json` in the meantime if desired
(currently `pillow>=10.0`, unpinned on the upper bound).
**Cross-refs:** `custom_components/dreame_a2_mower/manifest.json` (`pillow>=10.0`);
`map_render/base_map.py`; the 9 test files listed above.

---

### `MowerAction.SUPPRESS_FAULT` semantics

**Why:** The service exists in the integration but has never been live-tested.
It is unclear whether "suppress fault" means acknowledge a technical
malfunction, clear a physical-alert latch, or is a generic dismiss. Adding
a UI button without knowing semantics risks confusing users or triggering
unintended state changes.
**Done when:** A known-safe fault is triggered (e.g. lift lockout), the
SUPPRESS_FAULT action is called, and the resulting state change is observed.
Outcome: either a button entity is added with the right display conditions, or
the service is documented as power-user-only.
**Status:** blocked-by-safe-test-design (need a controlled fault scenario)
**Cross-refs:** `custom_components/dreame_a2_mower/actions.py`; journal topic `s1p1 byte[3] bit 7 PIN-required clarification`
