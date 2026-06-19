# Error-tier persistent notices (P3b) — design

**Date:** 2026-06-19 · **Status:** approved, pre-implementation
**Program:** `2026-06-18-fault-catalog-program-overview.md`. Builds on P0–P3a.

## Goal
Surface a Home Assistant `persistent_notification` for **error-tier** s2p2 faults
(the "mower can't continue / needs intervention" tier), created when the fault is
detected and dismissed when it clears, with the localized catalog solution text.
No other tier gets a persistent notice.

## Per-tier surfacing (final, app-faithful)
| Tier | HA surfacing | Rationale |
|---|---|---|
| **error** | **persistent_notification** (create on detect, dismiss on clear) | needs intervention; blocks mowing — mirrors the app's sticky modal |
| **attention** | transient — the notification event + logbook (already fires, P3a) | app shows a popup at mow-start that self-dismisses and **repeats** over time if unaddressed; a sticky banner would be wrong |
| **alert** | transient — the notification event + logbook (already fires) | recoverable operation failure |
| **info** | none beyond the event | lifecycle/status |

Only **error** tier needs new code. Attention/alert/info are unchanged (their
transient surfacing already exists via the P3a notification event + logbook).

## Why this is low-risk
`snapshot.errors` (the latched fault set) contains **only** error-tier codes —
the latch condition is `is_fault(code)` ⟺ `fault_tier(code) == "error"`. The
existing `_fire_fault_delta(prev_errors, new_errors, now_unix)` in
`coordinator/_device_sync.py` already fires `fault_detected`/`fault_cleared`
lifecycle events per added/removed code, with localized descriptions, from both
MQTT-push paths (s2p1/s2p2 and s1p4 position). P3b adds persistent-notice
create/dismiss **alongside those exact loops** — same lifecycle, same clear
signals (undock / mow-start / 0.3 m movement), same localization. No
state-machine change.

## Components

### A. Persistent-notice helpers — `coordinator/_device_sync.py`
Add two small methods mirroring the existing `_handle_emergency_stop_transition`
pattern (try/except-wrapped so a notification failure never breaks the delta):
```python
_EMERGENCY_STOP_CODE = 23  # owned by _handle_emergency_stop_transition (PIN notice)

def _fault_notification_id(self, code: int) -> str:
    return f"{DOMAIN}_fault_{int(code)}_{self.entry.entry_id}"

def _post_fault_notice(self, code: int, lang: str) -> None:
    """Post a persistent_notification for a newly-detected error-tier fault.
    Title = the catalog fault_text; body = the catalog detail (solution steps)
    when present, else the fault_text. Skips emergency-stop (its dedicated
    PIN notice owns code 23)."""
    if int(code) == self._EMERGENCY_STOP_CODE:
        return
    from ..mower import fault_catalog
    title = fault_catalog.fault_text(int(code), lang) or f"Fault {int(code)}"
    detail = fault_catalog.fault_detail(int(code), lang)
    body = detail or title
    try:
        from homeassistant.components import persistent_notification as _pn
        _pn.async_create(
            self.hass,
            message=body,
            title=f"Dreame A2 Mower — {title}",
            notification_id=self._fault_notification_id(code),
        )
        LOGGER.info("fault %d active — persistent_notification posted", int(code))
    except Exception as ex:  # never let a UI notice break state handling
        LOGGER.warning("fault %d notice create failed: %s", int(code), ex)

def _dismiss_fault_notice(self, code: int) -> None:
    """Dismiss the persistent_notification for a cleared error-tier fault."""
    if int(code) == self._EMERGENCY_STOP_CODE:
        return
    try:
        from homeassistant.components import persistent_notification as _pn
        _pn.async_dismiss(self.hass, notification_id=self._fault_notification_id(code))
        LOGGER.info("fault %d cleared — persistent_notification dismissed", int(code))
    except Exception as ex:
        LOGGER.warning("fault %d notice dismiss failed: %s", int(code), ex)
```

### B. Hook into `_fire_fault_delta` — `coordinator/_device_sync.py`
In the existing `_fire_fault_delta`, the two loops already iterate
`new_errors - prev_errors` (detected) and `prev_errors - new_errors` (cleared)
with `lang` already resolved. Add the notice calls inside those loops:
```python
    for code in sorted(new_errors - prev_errors):
        self._fire_lifecycle(EVENT_TYPE_FAULT_DETECTED, {...})   # unchanged
        self._post_fault_notice(int(code), lang)                  # NEW
    for code in sorted(prev_errors - new_errors):
        self._fire_lifecycle(EVENT_TYPE_FAULT_CLEARED, {...})    # unchanged
        self._dismiss_fault_notice(int(code))                     # NEW
```
`lang` is already computed at the top of `_fire_fault_delta`
(`fault_catalog.resolve_lang(hass.config.language)`). No new import there.

### C. Restart behavior (known limitation — under-notifies, never spams)
`snapshot.errors` is persisted/restored. The two `_fire_fault_delta` call sites
in `coordinator/_mqtt_handlers.py` read `_prev_errors` from the *restored*
snapshot before applying each push and only fire when `new != prev`. So after a
restart with a still-active fault, the re-pushed code equals the restored set →
no delta → **the banner is NOT re-posted** (HA `persistent_notification`s are
in-memory and don't survive a restart). The fault is still surfaced via the Error
sensor / `lawn_mower` ERROR state (those read `snapshot.errors` directly), just
without the banner until the fault clears and a later code re-fires it. This is
the *safe* direction (under-notify, never duplicate) and matches the existing
`_handle_emergency_stop_transition` banner's identical limitation. A startup
re-post of banners for the restored `snapshot.errors` is a possible follow-up
(deferred — would add a first-refresh hook; out of scope for P3b).

## Out of scope (later)
- Per-tier **device-trigger exposure** (which tiers get triggers) — **P3c**.
- Any persistent/latched surfacing for **attention** tier — intentionally NOT done
  (app-faithful: attention is transient + repeating).
- Heartbeat (s1p1) channel — **P4**.
- Companion-app push / actionable notifications — user automations via the
  device-triggers (P3c) + the notification event.

## Testing
Unit tests in `tests/coordinator/` (mirror the existing emergency-stop notice
test harness + the `_fire_fault_delta` tests). Use a fake/captured
`persistent_notification` (patch `homeassistant.components.persistent_notification`
async_create/async_dismiss to record calls), or the project's existing pattern
for asserting pn calls.
- **detect → create:** a delta adding an error code (e.g. 7 `cutter`) calls
  `async_create` with `notification_id == dreame_a2_mower_fault_7_<entry>`, title
  containing the localized `fault_text(7)`, body == `fault_detail(7)` (non-empty).
- **clear → dismiss:** a delta removing that code calls `async_dismiss` with the
  same id.
- **detail-absent fallback:** a code whose catalog `detail` is empty posts with
  body == title (no crash, no empty message).
- **emergency-stop excluded:** a delta adding/removing code 23 does NOT call
  `async_create`/`async_dismiss` via the fault path (the dedicated handler owns it).
- **localization:** with `hass.config.language = "nb"`, the title/body use the
  Norwegian catalog text (assert ≠ the English string for a code that differs).
- **robustness:** if `async_create` raises, `_fire_fault_delta` still completes
  (the lifecycle event still fires) — patch pn to raise and assert no exception
  propagates.
- **attention/alert not persisted:** assert an attention-tier code (e.g. 30
  `maintain_loss`) is never in `snapshot.errors` (it isn't latched), so the delta
  never posts a notice for it — i.e. confirm the latch is error-only (guard test).
- Full suite green.

## Verification (live, after release)
On the next error-tier fault (or by injecting one), confirm a persistent
notification appears in the HA notifications panel titled "Dreame A2 Mower — …"
with the solution text, and that it auto-dismisses when the mower recovers
(undocks / starts mowing / moves). Attention/alert codes show only in the
logbook/notification history, no banner — matching the app.
