# Tier classification + app-faithful ERROR latch (P2) — design

**Date:** 2026-06-18 · **Status:** approved, pre-implementation
**Program:** `2026-06-18-fault-catalog-program-overview.md`. Builds on P0/P1.

## Goal
Replace the ad-hoc 6-code `FAULT_CODES` with an authoritative, fully
app-derived tier classification (from the catalog's `category` + `severity`),
and make the `lawn_mower` ERROR latch faithful to the app. No carryover.

## The classification (app-derived, two axes from the catalog)
Tier names track the app vocabulary: `alert`/`info` mirror the app `category`
words; `error`/`attention` are the `FAULT` category split by `severity`.

| Tier | Rule (catalog `category` + `severity`) | count (iot) |
|---|---|---|
| **error** | `FAULT` & (`anomaly`\|`malfunction`) | 26 |
| **attention** | `FAULT` & (`work_message`\|`consumable`) | 8 |
| **alert** | `ALERT` (any severity) | 11 |
| **info** | `INFO` (any severity) | 24 |
| (none) | code not in catalog | — |

Only the **error** tier latches the HA error state in P2. The attention/
alert/info *surfacing* is P3; the heartbeat channel is P4.

## Components

### A. `fault_tier` — `mower/fault_catalog.py` (pure)
```python
def fault_tier(code: int, channel: str = "iot") -> str | None:
    """App-derived surfacing tier for a code, or None if unknown. Tier names
    track the app vocabulary (alert/info = category words; error/attention =
    the FAULT category split by severity).

    error     = FAULT + (anomaly|malfunction)    — mower can't continue / needs help
    attention = FAULT + (work_message|consumable) — attention, not broken
    alert     = ALERT (any severity)              — recoverable operation failure
    info      = INFO  (any severity)              — lifecycle/status
    """
    cat = fault_category(code, channel)
    if cat is None:
        return None
    sev = fault_severity(code, channel)
    if cat == "FAULT":
        return "error" if sev in ("anomaly", "malfunction") else "attention"
    if cat == "ALERT":
        return "alert"
    if cat == "INFO":
        return "info"
    return None
```
Add a small convenience: `error_tier_codes(channel="iot") -> frozenset[int]` =
`{c for c in known_codes(channel) if fault_tier(c, channel) == "error"}` (handy
for tests + any consumer wanting the set).

### B. Retire `FAULT_CODES`; `is_fault` → tier-derived — `mower/error_codes.py`
- DELETE the `FAULT_CODES: frozenset[int] = {...}` literal.
- Rewrite `is_fault`:
  ```python
  def is_fault(code: int | None) -> bool:
      """True if a code is the app's 'error' tier (FAULT + anomaly|malfunction):
      the mower can't continue without intervention. Drives the latched error
      state. Sourced from the app catalog [apk:g2408-plugin-ext1423] — no
      hand-curated list."""
      return code is not None and fault_catalog.fault_tier(int(code)) == "error"
  ```
- Update the surrounding comment that referenced "added to FAULT_CODES".

### C. State machine — no code change
`state_machine.py:331` already latches via `is_fault(event_code)`. Its behavior
is unchanged in shape; the SET of codes that latch expands from the 6 to the 26
app-derived error-tier codes. `lawn_mower.project_activity` (errors → ERROR) and
the Error sensor / `fault_detected`/`cleared` events follow automatically.

### Net behavior change (lawn_mower ERROR + Error sensor + fault events)
- WAS `{2,4,5,23,31,36}`.
- BECOMES the 26 `FAULT`&(`anomaly`|`malfunction`) codes:
  `{0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,17,20,21,22,23,24,26,37,59,73}`.
- **Adds** ~22 genuine hardware/stuck/thermal faults currently missed.
- **Drops** 31 (back-charge-failed) and 36 (task-start-failed) — the app
  classifies them `ALERT` → **alert** tier (no longer hard errors). Faithful
  to the app.

### D. Inventory reconciliation
`inventory.yaml § s2p2` property: the verification claiming
`FAULT_CODES={2,4,5,23,31,36}` is now superseded. Reword to: the integration's
HA error latch is the app-derived **error tier** = `FAULT` & (`anomaly`|`malfunction`)
(26 codes), via `fault_catalog.fault_tier` `[apk:g2408-plugin-ext1423]`; the
hand-curated `FAULT_CODES` is retired. Per the retraction rule, append the prior
`FAULT_CODES={2,4,5,23,31,36}` claim (verbatim) + reason to
`OLD/ha-dreame-a2-mower-docs/inventory-history/s2p2.md`. Add a 2026-06-18
`verified` row recording the tier rule + the new 26-code error set. Note the
31/36 move to alert.

## Out of scope (later phases)
- Per-tier surfacing for attention/alert/info (persistent vs transient
  notices, device-triggers per tier) — **P3**.
- Correcting catalog-revealed wrong `S2P2_EVENT_TYPES` slugs (e.g. 31
  `positioning_failed_stuck` → it's `ALERT_BACK_CHARGE_FAILED`) — **P3** (slugs
  feed the notification resolver + triggers).
- Heartbeat (s1p1) channel — **P4**.
- Exposing `fault_tier` as a sensor attribute — **P3** (surfacing).

## Testing
- `fault_tier`: 27→attention (FAULT/work_message, NOT error); 4→error
  (FAULT/malfunction); 31→alert (ALERT); 48→info (INFO); 9999→None.
- `error_tier_codes("iot")` == the pinned 26-code set.
- `is_fault`: true for 4/0/73 (error tier), false for 27/31/36/48, false for None.
- State machine: an s2p2 error-tier code (e.g. 7 cutter) latches `snapshot.errors`
  → present in the set; a non-error code (e.g. 27 human, 31 back-charge) does NOT
  latch. (Mirror the existing latch test for a code that newly qualifies.)
- Any pre-existing test asserting `FAULT_CODES` membership/contents → convert to
  `error_tier_codes()` / `is_fault()`.
- Full suite green (the lawn_mower/Error-sensor/fault-event tests must reflect
  the expanded set, not the old 6).

## Verification (live, after release)
P2 changes behavior, so it releases. On live HA: confirm the mower entity goes
ERROR for an error-tier fault (the next time one occurs) and that
back-charge-failed/task-start-failed no longer force ERROR (alert tier). Until
a live fault occurs, the expanded latch is verified by the test suite.
