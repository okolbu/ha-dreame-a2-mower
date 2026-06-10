# Phase B — Core-control verdicts (design)

**Date:** 2026-06-10
**Status:** design, awaiting user review → writing-plans
**Phase:** B of the app-integration roadmap (`docs/research/app-integration-roadmap.md`).
**Predecessors:** Phase 0 (knowledge capture), A1 (CFG writable, v1.0.24a9), A2 (PRE writable, v1.0.25a1).

## Context

The core-control buttons pause/stop/dock(recharge) are `DEVICE_WRITE_UNPROVEN`
(`_U`) because their `ACTION_TABLE` entries have **no `routed_o`** — they dispatch
via the direct `(siid:5, aiid:N)` path, which returns **80001 (no effect)** on
g2408. The button fires (no padlock, `_U` is operable) but the action no-ops.

The 2026-06-09 app capture shows the app drives all core control through the
routed `s2.a50 {m:"a",o:N}` path: **stop=o3, pause=o4, resume=o5, dock/recharge=o6,
cancel-dock-return=o13**. START already uses `routed_o=100` (works, `_W`). These
opcodes are recorded `verified` in `inventory.yaml` (Phase 0).

So the fix is to add the confirmed `routed_o` to pause/stop/dock — `dispatch_action`
routes via `routed_action(o)` when `routed_o` is present, else falls back to the
direct path (the 80001 no-op). The verdict flip `_U → _W` is then the honesty
update. The capture also reveals two controls the integration doesn't expose:
Resume (o=5) and Cancel-dock-return (o=13).

**Honesty basis:** the app capture is the wire verification (consistent with A1/A2).

## Goal & scope

**Goal:** make pause/stop/dock/recharge actually reach the mower via the
capture-confirmed routed opcodes, flip those buttons to `DEVICE_WRITABLE`, and add
Resume + Cancel-dock-return controls.

**In scope:**
- `ACTION_TABLE` (`mower/actions.py`): add `routed_o` to `STOP`(3), `PAUSE`(4),
  `DOCK`(6), `RECHARGE`(6); add `MowerAction.RESUME` (o=5) and
  `MowerAction.CANCEL_DOCK_RETURN` (o=13). All no-payload routed actions.
- `button.py`: flip `pause_mowing`/`stop_mowing`/`recharge` `_U → _W`; add
  `DreameA2ResumeButton` (`resume_mowing`) + `DreameA2CancelDockReturnButton`
  (`cancel_dock_return`), both `_W`.
- `control_honesty.py` + `entity-inventory.yaml` verdicts (kept in sync).
- Inventory/entity-inventory fact-discipline records.

**Out of scope — TODO (open questions):**
- `lock_bot` (o=12) — stays `_U`. There is no lock button in the app; the backend
  may gain support later. Accepted-but-no-effect on current g2408 firmware.
- `generate_3dmap` (o=10) — stays `_U`. An unknown trigger snapshots the 3D map
  (multiple versions of the same map exist in our data); the trigger is unknown.
- START (o=100) — already `_W`; untouched.

## §1 ACTION_TABLE changes

Existing entries keep `siid`/`aiid` (record/fallback); adding `routed_o` makes
`dispatch_action` use the working routed path:
- `PAUSE`: add `routed_o: 4`
- `STOP`: add `routed_o: 3`
- `DOCK`: add `routed_o: 6`
- `RECHARGE`: add `routed_o: 6` (same wire call as DOCK)
- **new** `MowerAction.RESUME`: `routed_o: 5`, no payload — continue a paused mow
- **new** `MowerAction.CANCEL_DOCK_RETURN`: `routed_o: 13`, no payload — stop an
  in-progress dock-return without a full stop (distinct from STOP o=3)

All are `{m:"a",o:N}` no-payload routed actions, matching the capture. No change to
START or the mow opcodes (100–103/107/108).

## §2 Entities & verdicts

- **`button.py`:** add `DreameA2ResumeButton` (suffix `resume_mowing`, dispatches
  `MowerAction.RESUME`) and `DreameA2CancelDockReturnButton` (suffix
  `cancel_dock_return`, dispatches `MowerAction.CANCEL_DOCK_RETURN`), following the
  `_DreameA2ActionButton` pattern (sets `self._action`); register both in
  `async_setup_entry`.
- **`control_honesty.py` `CONTROL_MODES`:** `button.dreame_a2_mower_pause_mowing`,
  `_stop_mowing`, `_recharge` → `_W`; add `_resume_mowing`, `_cancel_dock_return`
  → `_W`. `_lock_bot`, `_generate_3dmap` stay `_U`.
- **`entity-inventory.yaml`:** flip the 3 control_mode fields, add the 2 new button
  entries (with sources + control_mode), mirror.

## §3 Testing (TDD)

- `ACTION_TABLE`: assert `routed_o` == 3/4/6/6 for stop/pause/dock/recharge; RESUME
  == 5; CANCEL_DOCK_RETURN == 13; all no-payload.
- `dispatch_action`: for PAUSE/STOP/DOCK/RECHARGE/RESUME/CANCEL_DOCK_RETURN it calls
  `cloud_client.routed_action(<o>, …)` (NOT the direct `action(siid,aiid)` path).
  Use a mocked cloud client and assert the opcode.
- `button.py`: the 2 new buttons dispatch the correct `MowerAction`; the pause/stop/
  recharge buttons report `provisional=False` / writable (`control_mode` ==
  `device_writable`).
- `control_mode` code-sync test green (CONTROL_MODES ↔ entity-inventory).
- Full suite green.

## §4 Fact-discipline

- **`inventory.yaml`:** opcodes 3/4/5/6/13 are already `verified` (Phase 0). Append
  a verification (date 2026-06-10) that the integration now **wires** them via
  `ACTION_TABLE.routed_o`, replacing the direct `siid:5/aiid:N` path that returned
  80001. Evidence `app-mitm:2026-06-09-settings-sweep`. Bump `last_seen`.
- **`entity-inventory.yaml`:** for pause/stop/recharge, append a verification that
  they are now wired + writable via routed `o=4/3/6`; add entries for the 2 new
  buttons. If any prior entity-inventory claim states pause/stop/dock are unproven
  *because the routed opcode is unknown*, that's now resolved → append a
  progression verification (retract only if a claim is literally false).
- **TODO** (`knowledge-gaps.md` + inventory open_questions):
  - `lock_bot` o=12 — no app lock button; backend may add support later;
    accepted-but-no-effect on g2408. `[UNKNOWN — to capture]`.
  - `generate_3dmap` o=10 — an unknown trigger snapshots the 3D map (multiple
    versions of the same map observed); capture step = find what fires the
    snapshot. `[UNKNOWN — to capture]`.

## §5 Risks & edge cases

- **Direct-path fallback retained:** keeping `siid`/`aiid` on the entries is
  harmless — `dispatch_action` prefers `routed_o` when present. No behavior change
  for START or other already-routed actions.
- **RESUME vs START semantics:** HA's `lawn_mower.start_mowing` maps to o=100 (full
  start). Resume (o=5) is a distinct "continue from pause" — exposed as its own
  button, not folded into start, so a paused mow can be continued without
  restarting.
- **CANCEL_DOCK_RETURN vs STOP:** o=13 cancels an in-progress dock-return only;
  it is NOT o=3 (End/Stop). Documented + named distinctly.
- **No live re-verification required** beyond the capture (per the honesty basis);
  if the firmware ever rejects one, `dispatch_action`'s `routed_action` returns a
  non-zero `r` and the failure is logged (no silent success).

## Out-of-scope follow-ups (TODO, not built here)

- `lock_bot` (o=12) device support — revisit if the backend adds it.
- `generate_3dmap` (o=10) snapshot trigger — capture what fires it.
