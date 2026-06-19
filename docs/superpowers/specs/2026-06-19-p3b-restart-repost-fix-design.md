# P3b restart re-post fix — design

**Date:** 2026-06-19 · **Status:** approved, pre-implementation
Follow-up to P3b (`2026-06-19-fault-catalog-p3b-error-persistent-notices-design.md`).

## Problem
After an HA restart while an error-tier fault is still latched, the
`persistent_notification` is **not re-posted**: `snapshot.errors` is restored from
disk, but the two `_fire_fault_delta` call sites read `_prev_errors` from the
restored snapshot and only fire when `new != prev`. The first MQTT push carries the
same set → no delta → no `_post_fault_notice`. The Error sensor / `lawn_mower` ERROR
still reflect the fault (they read the snapshot directly), but the banner is gone.
HA `persistent_notification`s are in-memory and don't survive a restart.

## Fix
A one-shot, unconditional startup re-post of the error banners for the restored
`snapshot.errors`, calling `_post_fault_notice` **directly** (not via
`_fire_fault_delta`) so it does NOT fire spurious `fault_detected` lifecycle events.

### A. `_repost_active_fault_notices()` — `coordinator/_device_sync.py`
New method on `_DeviceSyncMixin`:
```python
def _repost_active_fault_notices(self) -> None:
    """Re-post error-tier persistent notices for faults restored from disk.

    On HA restart with a still-latched fault, snapshot.errors is restored but
    _fire_fault_delta won't re-fire (no delta when the first MQTT push equals the
    restored set), so the banner is lost. This one-shot startup call re-posts it
    directly — WITHOUT firing fault_detected (no _fire_fault_delta). Idempotent:
    _post_fault_notice uses a per-code notification_id, so re-posting just updates
    in place. emergency-stop (23) is skipped by _post_fault_notice (its own notice
    re-posts via _handle_emergency_stop_transition on the first heartbeat)."""
    if getattr(self, "hass", None) is None or getattr(self, "entry", None) is None:
        return
    sm = getattr(self, "state_machine", None)
    if sm is None:
        return
    try:
        errors = sm.snapshot().errors
    except Exception:
        return
    if not errors:
        return
    from ..mower import fault_catalog
    cfg = getattr(self.hass, "config", None)
    lang = fault_catalog.resolve_lang(getattr(cfg, "language", None))
    for code in sorted(errors):
        self._post_fault_notice(int(code), lang)
```

### B. Call site — `coordinator/_core.py`
Unconditionally, right after `await self._restore_in_progress()` (line 591) and
before `_init_mqtt` (line 593) — `snapshot.errors` is restored (line 571), hass/
entry/cloud are ready, MQTT isn't subscribed yet:
```python
            await self._restore_in_progress()

            # Re-post error-tier persistent notices for faults latched on disk:
            # snapshot.errors is restored above, but _fire_fault_delta won't
            # re-fire them across a restart (no delta vs the restored set), so the
            # banner would be lost. Re-post directly (no spurious fault_detected).
            self._repost_active_fault_notices()
```
Placed OUTSIDE `_restore_in_progress` (which is session-conditional) so it runs even
when a fault is latched with no active mow session (e.g. stuck at the dock).

## Why not emergency-stop
`emergency_stop` is **not persisted** in `StateSnapshot`; on restart its prior value
is `None`, so the first heartbeat's `None→True` transition fires
`_handle_emergency_stop_transition` and re-posts that notice correctly. No change.

## Out of scope
- Dismissing stale notices for faults that cleared *while HA was down* — the next
  movement/undock/mow-start clears `snapshot.errors` and fires `fault_cleared` →
  `_dismiss_fault_notice`, so they self-heal. No extra handling.

## Testing
- `_repost_active_fault_notices`: with a coord stub (hass+entry+state_machine whose
  `snapshot().errors == {7, 9}`) and a fake persistent_notification, calling it posts
  notices with ids `dreame_a2_mower_fault_7_<entry>` + `_fault_9_<entry>`, and fires
  NO lifecycle event (assert the lifecycle recorder is empty / `_fire_lifecycle`
  never called).
- code 23 in the restored set is skipped (no notice for 23).
- empty `snapshot.errors` → no pn calls.
- missing hass/entry → no-op (no crash).
- localized: lang resolved from `hass.config.language`.
- (call-site) a light test or existing coordinator-setup test still passes; the call
  is additive.
- Full suite green.

## Verification (live, after release)
Trigger or wait for an error-tier fault, restart HA while it's active, confirm the
"Dreame A2 Mower — …" banner reappears after restart (vs. disappearing pre-fix).
