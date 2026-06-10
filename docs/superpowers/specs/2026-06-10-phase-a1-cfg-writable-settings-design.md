# Phase A1 — CFG single-key writable settings (design)

**Date:** 2026-06-10
**Status:** design, awaiting user review → writing-plans
**Phase:** A1 of the app-integration roadmap (`docs/research/app-integration-roadmap.md`).
**Predecessor:** Phase 0 (knowledge capture) — facts live in `inventory.yaml`.

## Context

The 2026-06-09 app-MITM sweep captured the exact write envelopes for the g2408
CFG keys, recorded as `confirmed` in `inventory.yaml`. Per the user's direction,
**the app capture IS the wire verification** (the user toggled each setting live
and the device accepted it; raw logs in the private, off-GitHub
`dreame-app-capture-2026-06-09/`). Older "read-only / no-setter / unknown wire
format" claims predate the sweep and are not to be trusted.

The integration is already plumbed for CFG writes: entity descriptors carry
`cfg_key` (WRP/DND/LOW/BAT/LIT/REC/LANG/…), `coordinator.write_setting(cfg_key,
full_value, field_updates)` exists, and `cloud_client.set_cfg` builds the
`{m:"s",t:KEY,d:<payload>}` routed-action envelope and checks `out[0].r==0`. The
read-only controls are held back only by the `read_only` gate (from
`control_mode`) short-circuiting to snap-back, and by the multi-field/typed keys
(BAT/REC/LANG) having been built with a *guessed* shape (set_cfg flagged these
"unknown wire format").

## Goal & non-goals

**Goal:** make the CFG-single-key "More Settings" controls write to the mower
using the app's exact captured envelopes, and flip their `control_mode` to
`DEVICE_WRITABLE`. Additionally, **audit every CFG single-key write transport**
(including already-writable keys) against the capture and fix any mismatch.

**In scope — read-only controls to make writable:**
- **WRP** — `rain_protection` (switch), `rain_protection_resume_hours` (select)
- **DND** — `dnd` (switch) + start/end time entities
- **LOW** — `low_speed_at_night` (switch) + start/end time entities
- **BAT** (typed) — `custom_charging_period` (switch) + charging start/end time →
  `type:"charging"`; `auto_recharge_battery_pct` + `resume_battery_pct` (numbers)
  → `type:"power"`
- **LIT** — `led_period` + `led_in_standby/working/charging/error` (switches) +
  start/end time entities
- **REC** — `human_presence_alert` (switch), `human_presence_alert_sensitivity`
  (number)
- **LANG** — `lcd_language`, `voice_language` (selects)

**In scope — transport-parity audit only (already writable):** PROT, CLS, ATA,
FDP, STUN, AOP, MSG_ALERT, VOICE, VOL. Verify the integration's emitted envelope
matches the capture; fix + retract if it diverged; otherwise add a confirming
verification (no code change).

**Non-goals:**
- PRE General-Mode per-map settings (Phase A2 — includes the `d:[...]`-vs-`d:{value}`
  envelope fix).
- `ai_human_enabled` (different transport — chunked KV with a consent gate;
  deferred).
- Fresh-fetch-before-write (cached RMW is the chosen default; see §3).
- New entities for unexposed fields (REC `mode`/`report`, WRP `sen`, LIT `fill`).

## §1 Honesty basis

Confirmed keys flip straight to `DEVICE_WRITABLE`. The correctness gate is
**transport parity** against `dreame-app-capture-2026-06-09/`, not a fresh live HA
round-trip. This is the user's explicit direction: treat the sweep as wire truth.

## §2 Architecture — three layers, one new module

1. **`protocol/cfg_payloads.py` (new) — pure per-key payload builders.** One
   function per CFG key: `build_wrp`, `build_dnd`, `build_low`,
   `build_bat_charging`, `build_bat_power`, `build_lit`, `build_rec`,
   `build_lang`. Each takes the *current* full key value + the field(s) being
   changed and returns the exact `d`-payload dict the app sends, doing
   read-modify-write at the dict level so untouched fields (`sen`, `fill`, BAT
   `flag`, REC `mode`/`report`) are preserved. Pure functions, no I/O →
   unit-tested directly against the captured envelopes. A builder returns `None`
   when it has no cached base to RMW from (see §5) so the caller reverts rather
   than sending a partial payload that wipes fields.

2. **`set_cfg` transport (audit + align).** Confirm `set_cfg`'s envelope
   (`{m:"s",t:KEY,d:<payload>}`, `out[0].r==0` success check) matches the capture
   for every key — both the builders' dict output and the existing primitive
   `{value:X}` path. Fix any divergence found in the audit.

3. **Entity handlers — remove the read-only gate, call the builder.** Descriptors
   already carry `cfg_key`; handlers already call `write_setting`. The change:
   build `full_value` via the new builder instead of today's guessed shape, and
   stop short-circuiting on `read_only` once the verdict flips. Optimistic update
   + revert-on-failure already exist (`write_setting`'s `field_updates`,
   `_settings_writes.settings_optimistic_write`).

## §3 RMW source of truth

Builders read the current full key value from `cloud_state.cfg[KEY]` (last poll).
**Cached RMW — no fresh-fetch-before-write.** For a single-user setup the app/HA
dual-write race on the same key within the 2-min poll window is negligible
(matches the no-over-engineering preference). Fresh-fetch (mirroring the
`write_settings` SETTINGS-blob pattern) is added later only if clobbering shows up.

## §4 Verdict flip & fact-discipline

- **`control_honesty.py`:** flip in-scope controls `_C`/`_P`/`_N` → `_W`. The
  `control_mode` code-sync CI test enforces `CONTROL_MODES` ↔
  `entity-inventory.yaml`, so both move in the same change.
- **`entity-inventory.yaml`:** supersede each flipped control's Phase 0
  "captured, NOT wired" record with a verification: now wired + writable,
  transport-parity-confirmed against the 2026-06-09 capture; update the
  `control_mode` field.
- **`inventory.yaml`:** record the transport-parity audit result for the
  already-writable keys. Any key whose integration transport diverged from the
  app's captured shape gets a verification + a verbatim `retracted` record for the
  prior wire claim. Keys that already match get a confirming verification.
- The CI `inventory-touch-gate` requires these land in the same change as the
  code.

## §5 Testing (TDD)

**Constraint:** the capture is private/off-GitHub (real PIN/tokens/GPS), so CI
cannot read it. During the build, extract the non-secret CFG `d`-payload shapes
into a committed, scrubbed fixture (`tests/fixtures/cfg_envelopes_2026-06-09.json`
— WRP/DND/LOW/BAT/LIT/REC/LANG + the audited already-writable keys; PIN/tokens
excluded). That fixture is the oracle. Test code never references the off-repo
capture.

Layers (write the failing test first):
1. **Per-key builder unit tests** — `build_<key>(current, **changes)` output,
   wrapped by `set_cfg`'s envelope, equals the captured `d`-payload. Cover RMW
   field-preservation (toggle `led_in_working` → only `light[1]` changes;
   `fill`/`time`/other bits intact; BAT `flag` preserved; REC `mode`/`report`
   preserved).
2. **`set_cfg` transport-parity test** — full `{m:"s",t:KEY,d:…}` envelope matches
   the fixture for every audited key; `out[0].r==0` success-parse unchanged.
3. **Entity-handler tests** — verdict `_W` ⇒ read-only short-circuit no longer
   fires; handler builds the right payload, calls `write_setting`; optimistic
   update applies and reverts on `r!=0`.
4. **`control_mode` code-sync test** — green (now asserts `_W` for flipped
   controls).
5. **Existing read-only assertions** for these controls updated to expect
   writable.
6. Full suite baseline (2055 passed / 4 skipped) green afterward.

## §6 Risks & edge cases

- **REC** — `mode:[Standby,Mowing,Recharge,Patrol]` and `report:[VoiceInApp,
  CaptureHumanPhotos, PushInterval]` have no entities; the builder RMW-preserves
  them from the current REC value. If `cloud_state.cfg` has no REC base, the
  builder returns `None` and the handler reverts (never send a partial REC that
  wipes `mode`/`report`). Same defensive stance for any multi-field key with no
  cached base.
- **BAT typed split** — one 6-int read (`[recharge,resume,flag,custom,start,end]`)
  feeds two write types; builders map read → `{type:"power",value:[recharge,
  resume,flag]}` / `{type:"charging",value:[en,start,end]}`, preserving the
  untouched type's fields and `flag`.
- **WRP `sen`, LIT `fill`** — no entities → always preserved from current.
- **LANG** — `text` = app display language, `voice` = device voice; both
  device-accepted writes per capture (no download on voice change). Keep both.
- **Audit may find an already-writable key was silently wrong** — align to capture
  + retract the old wire claim. If everything matches, just add a confirming
  verification (no code change).
- **Capture is private** — fixtures are scrubbed/committed; test code never
  references the off-repo capture.

## Out-of-scope follow-ups (noted, not built here)

- Entities for REC `mode`/`report`, WRP `sen`, LIT `fill` (surface later if wanted).
- Fresh-fetch-before-CFG-write hardening (only if clobbering is observed).
- Phase A2 (PRE General-Mode per-map settings).
