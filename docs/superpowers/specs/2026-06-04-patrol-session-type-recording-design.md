# Reliable session-type recording via a pending task-op latch — Design

**Date:** 2026-06-04
**Status:** Approved (brainstorming → spec)
**Branch (planned):** `fix/patrol-session-type-recording`

## Problem

Patrol sessions are intermittently mis-typed as `maintenance_run`
("[To Point]") and finalized early (missing the return leg). Observed
2026-06-04: the first point patrol recorded a correct full `patrol`
session; the second point patrol and an edge patrol both closed early
and were labelled "Point". The HA restart that day happened *after* the
failing runs, so restart is **not** a factor.

### Root cause (recording, upstream of finalize)

`live_map/classify.py:classify_session_type` re-derives the session type
at **finalize** from two MQTT clues that must still be present on the
live session:

```python
if last_task_op in (107, 108) or saw_patrol_start:   # saw_patrol_start = 51 in error_samples
    return "patrol", None
...
return "maintenance_run", outcome    # silent fall-through
```

Both clues are captured into a session that does not exist yet when they
arrive, then lost:

1. **The `s2p50` op echo** (`op=107/108`, the command-ack) is captured at
   `coordinator/_mqtt_handlers.py:284-302` **only if
   `self.live_map.is_active()`** at the moment the threadsafe callback
   runs. A patrol commanded from the dock echoes the op ~40s *before*
   the first `s1p4` position push triggers `begin_session()`, so the
   session is not active yet → **the op echo is dropped, `last_task_op`
   is never set.**
2. **`s2p2=51`** (patrol_started) is appended to `error_samples` by
   `_capture_telemetry_sample` (`:792`, ungated) — but
   `begin_session()` (`:406`) **resets `error_samples = []`**
   (`live_map/state.py:151`), so a `51` that arrived before the session
   began is **wiped.**

Net: a dock-started patrol can reach finalize with *neither* clue →
`classify` falls through to `maintenance_run`. Whether it fails depends
purely on the arrival **order** of (op echo / `s2p2=51`) vs the first
`s1p4` that calls `begin_session()` — hence intermittent and
restart-independent.

The same pre-`begin_session` drop affects **every** task type
(mow/zone/spot/cruise/manual), not only patrol — the user's decision is
to fix it generally rather than special-case patrol.

### Downstream effect (early finalize)

Because the session is not recognized as cloud-finalized, the
`s2p2=75` (arrived-at-point) immediate-finalize gate
(`_mqtt_handlers.py:997`) and the `s2p56` new-command-boundary gate
(`:1022`) — both guarded by `_provisional_session_is_cloud_finalized()`
— fire on the first point arrival, closing the patrol early and losing
the return leg. This requires **no separate fix**: it resolves once the
type is recorded correctly.

## Design

One new piece of coordinator state, `_pending_task_op`, captured from
MQTT (never from "which button the integration pressed" — an app-started
patrol only has the MQTT clues) and seeded into the session at birth.

### 1. Capture (ungated by `is_active()`)

On every `s2p50` op echo, set `self._pending_task_op = op`
**unconditionally**. The `is_active()` guard at
`_mqtt_handlers.py:290-302` is removed *for the latch capture*; the
command-time `_render_base` trigger that shares that block keeps its
existing behavior. This catches the op regardless of whether a session
has begun.

### 2. Seed at session birth

In `_on_state_update`, immediately after `begin_session()` fires
(`:406`), seed `self.live_map.last_task_op = self._pending_task_op` when
it is set. The session is born already knowing its type. This applies to
**all** task ops (15 manual, 100-103 mow, 107/108 patrol, 109 cruise),
fixing the pre-`begin_session` drop generally.

`saw_patrol_start` (the `s2p2=51` path) remains a secondary signal but is
no longer load-bearing for the dock-start case, because `last_task_op`
now carries the type.

### 3. No recency window

Per the user's decision, no time-window guard: the last op echo wins.
Rationale: the only failure mode of "no window" is a stale op from a
prior session leaking into a later one while the integration was down
across a session boundary — which §4 (persistence) plus normal finalize
clearing makes safe, and which is far rarer than an average session.

### 4. Persist across boot (sidecar)

The `s2p50` op echo is a one-shot command-ack; it never replays. To
survive a restart that straddles the op-echo → `begin_session` boundary
(the integration was down when the session would have begun, and comes
back before it records the start), persist `_pending_task_op`:

- **Write:** whenever `_pending_task_op` changes (on each op echo), write
  `sessions/pending_task_op.json` via `session_archive` (sidecar next to
  `in_progress.json`). Op echoes are infrequent (task-start only), so the
  write cost is negligible.
- **Read:** on `_restore_in_progress`, load the sidecar into
  `self._pending_task_op`.
- **Clear:** delete/zero the sidecar on session finalize (both the
  cloud-finalized and incomplete paths) so a completed session's op
  cannot seed a later one.

A reboot *after* `begin_session()` is already covered separately —
`last_task_op` is persisted inside `in_progress.json` by
`dump_to_payload` (`:295`) and restored by the existing session-restore
path. The sidecar covers only the narrow pre-`begin_session` straddle.

### 5. Observability

Add a `WARNING` log in `classify_session_type` when it reaches the
`maintenance_run` fall-through with **no** positive signal
(`last_task_op` is None / not a known task op, `area_ever_positive`
False, `saw_patrol_start` False). This makes a future silent type-loss
visible in the log instead of masked behind the default — per "if we do
not know what type to finalize, something is wrong earlier in the
session recording." A genuine to-point maintenance run (op=109) still
classifies correctly and does **not** trip this warning.

## Components touched

| File | Change |
|---|---|
| `coordinator/_core.py` | Add `self._pending_task_op: int \| None = None` to `__init__`. |
| `coordinator/_mqtt_handlers.py` | Capture: set `_pending_task_op` ungated on `s2p50` echo (`:284-302`). Seed: after `begin_session()` (`:406`) set `live_map.last_task_op` from the latch. Persist-on-change write. |
| `coordinator/_session.py` | Restore: read sidecar in `_restore_in_progress`. Clear: delete sidecar on finalize (incomplete + cloud paths). |
| `archive/session.py` (`SessionArchive`, `:197`) | Add `write_pending_op` / `read_pending_op` / `delete_pending_op` mirroring the existing `read_in_progress` / `delete_in_progress` helpers (`:351`+). |
| `live_map/classify.py` | Add the no-signal `maintenance_run` fall-through WARNING. |

No change to wire/op semantics, to `classify`'s branch order (beyond the
log), to entity definitions, or to inventory protocol facts. No migration
code (single-user; reinstall is fine).

## Data flow (dock-started patrol, happy path)

```
app/card → patrol command
  → s2p50 op=107 echo   ⇒ _pending_task_op = 107 (ungated)  + sidecar write
  → s2p2=51             ⇒ error_samples += 51 (secondary)
  → (~40s) first s1p4, task_state 0
        ⇒ begin_session()            (resets error_samples)
        ⇒ live_map.last_task_op = _pending_task_op (=107)   ← SEED
  → s2p2=75 (arrived pt 1)
        ⇒ _provisional_session_is_cloud_finalized() == True (op 107)
        ⇒ early-finalize gate SKIPS  → patrol keeps running
  → … points … → return leg → dock (charging)
        ⇒ cloud-finalized path, return leg captured
        ⇒ classify → "patrol"        + sidecar cleared
```

## Testing (TDD)

Unit / sequencing tests (vanilla stubbed-HA venv,
`/data/claude/homeassistant/.venv-vanilla/bin/python`):

1. **Op-echo before begin → session seeded.** Feed `s2p50 op=107` while
   `live_map` inactive, then drive `task_state None→0`; assert
   `live_map.last_task_op == 107` after `begin_session`.
2. **All-ops generality.** Same for op=109 and op=102 — assert the seed
   is not patrol-specific.
3. **No-window last-wins.** Two op echoes before begin (108 then 102) →
   seeded value is 102.
4. **Sidecar round-trip.** `write_pending_op(107)` → `read_pending_op()`
   == 107; `delete_pending_op()` → read == None.
5. **Restore seeds across boot.** Sidecar has 108, no `in_progress.json`,
   restore then `begin_session` → `last_task_op == 108`.
6. **Sidecar cleared on finalize.** After a finalize, `read_pending_op()`
   == None.
7. **Classify regression.** `classify_session_type(last_task_op=107,…)`
   → `("patrol", None)`; with all signals absent → `("maintenance_run",
   …)` **and** the new WARNING is emitted (caplog).
8. **Dock-start race reproduction (the bug).** Sequence op echo +
   `s2p2=51` (inactive) → `begin_session` → `s2p2=75`; assert the session
   is **not** finalized and provisional type == `patrol`.

Regression: the existing finalize/classify/early-finalize suites
(`tests/**`) must stay green — baseline ~1980 passed / 4 skipped.

## Out of scope (YAGNI)

- Re-reading the current task op from cloud props on restart (unknown
  whether `s2.50` holds current-op state — would need a capture probe).
- Any change to the `s2p2=75` / `s2p56` early-finalize gates themselves —
  they become correct once the type is recorded.
- Migration / registry code.

## Inventory / fact-discipline note

This change does not assert any new wire fact. `s2p2=51 = patrol_started`
and `op=107/108 = point/edge patrol` are already `verified` in
`inventory.yaml`. The o108 `open_question` about patrol session tracking
("the live map can't track the mower during patrol… Patrol should be a
first-class session_type") should be updated to reference this fix once
shipped and live-confirmed.
