# Accumulate device messages to 200 (todo7 #1) — design

**Date:** 2026-06-18 · **Status:** approved, pre-implementation

## Problem & verified premise

`sensor.dreame_a2_mower_device_messages` only ever shows the latest ~10 messages.
The cloud endpoint `device-messages/v2` is a **fixed moving window of the latest
10**: live-probed 2026-06-18, `pageSize` 10/50/200 all return exactly 10, and
`pageNum` 2/3/4 return the same 10 (pagination ignored). The integration also
*replaces* `device_messages` on every fetch. So the only way to retain more is to
**accumulate**: merge each fetch's 10 into a persisted, deduped list capped at the
keep limit.

## Decisions (from brainstorming)
- **Persist + restore** the accumulated list (otherwise a restart resets to 10).
- **Cap 200**: `DEFAULT_MESSAGES_KEEP` 100 → 200; the `CONF_MESSAGES_KEEP` option
  still overrides (range 1–500).
- **Device sensor state = total count** (history stays in the `items` attribute).
  Device messages have no read flag (`unread` is hard-coded `True`), so an
  "unread count" state is misleading for a growing log.

## Out of scope
- Service / shared message lists keep *replacing* (their endpoints return full
  lists; the server doesn't window them). They are NOT persisted/accumulated.
- No per-message read-state tracking (the API gives none).

## Components

### 1. Pure merge helper — `protocol/message_record.py`
`merge_device_messages(existing: list[dict], fresh: list[dict], cap: int) -> list[dict]`
- Union by `id` with **existing-priority**: an id already in `existing` keeps the
  stored dict (preserving its linked `photos`); only ids new to `existing` are
  added from `fresh`. (Device-message text is immutable, so keeping the stored
  copy loses nothing and keeps photo links.)
- Sort newest-first by `date` (ISO-8601 string; missing/!str dates sort last).
- Truncate to `cap`.
- Pure (no HA imports), unit-testable. Mirrors the `_restore_merge.py` style.

### 2. Coordinator merge+persist — `coordinator/_notifications.py`
New method `_merge_device_messages(self, fresh_dicts: list[dict]) -> list[dict]`:
- `cap` is read from `entry.options.get(CONF_MESSAGES_KEEP, DEFAULT_MESSAGES_KEEP)`
  (same as the existing sites — factor the 3-line cap lookup into a tiny helper or
  inline it identically).
- `merged = merge_device_messages(self.data.device_messages, fresh_dicts, cap)`
- `self.link_message_snapshot_photos(merged)` (only adds a `photos` key — safe to
  re-run; old links survive because existing dicts win the merge).
- Schedule a debounced persist: `self._device_messages_store.async_delay_save(
  lambda: merged, DEVICE_MESSAGES_SAVE_DELAY_S)` (works from the reactive sync
  path; debounces rapid s2p2 bursts). `DEVICE_MESSAGES_SAVE_DELAY_S = 5`.
- Return `merged`.

### 3. Both refresh sites merge instead of replace
- `coordinator/_refreshers.py:_refresh_messages` — replace
  ```python
  dev_list = [msg.as_dict() for msg in _msg.normalize_device(dev_raw)[:cap]]
  self.link_message_snapshot_photos(dev_list)
  kw["device_messages"] = dev_list
  ```
  with
  ```python
  fresh = [msg.as_dict() for msg in _msg.normalize_device(dev_raw)]
  kw["device_messages"] = self._merge_device_messages(fresh)
  ```
  (drop the now-duplicated `[:cap]` and `link_message_snapshot_photos` here —
  both happen inside `_merge_device_messages`.)
- `coordinator/_notifications.py:_apply_device_messages` — same: build `fresh`
  from `normalize_device(records)`, then `device_messages =
  self._merge_device_messages(fresh)` in the `dataclasses.replace`.

### 4. Persistence (mirror `_state_store`)
- `_core.py __init__`: add `self._device_messages_store = None`.
- `_core.py _async_update_data` (first-run init, near the `_state_store` /
  `state_machine.load_persisted` block): lazily construct
  `Store(self.hass, version=1, key=f"dreame_a2_mower_device_messages_{self.entry.entry_id}")`,
  `await async_load()`. If a non-empty list comes back, **seed it immediately
  onto the coordinator's MowerState** so the sensor shows the retained history on
  boot AND it is the merge base for the first fetch — i.e. set
  `device_messages = stored[:cap]` on the MowerState that first-run
  `_async_update_data` produces/returns (the exact injection point is wherever the
  initial `MowerState` is built/returned; if state is only available post-return,
  set it and call `async_set_updated_data`). Do NOT merely stash it for a later
  merge — that would leave the sensor empty until the (up-to-hourly) refresh runs.
  Guard with try/except like the state restore (never fail setup on a bad store).
- Saves happen via `async_delay_save` inside `_merge_device_messages` (step 2).
  The stored payload is the plain `list[dict]` (JSON-serializable: id/title/date/
  body/link/unread/optional photos).

### 5. Cap default — `const.py`
`DEFAULT_MESSAGES_KEEP: Final = 200` (was 100).

### 6. Device sensor state = total count — `entities/sensor/device.py`
`DreameA2DeviceMessagesSensor` overrides `native_value` to `len(self._items())`
(total retained), instead of inheriting the base's unread-count. Service/shared
sensors are unchanged. Keep the `items` attribute (the full newest-first list).

### 7. Docstring fact-tag
`cloud_client/_fetchers.py:fetch_device_messages` docstring's "Server caps
page_size at 10 and ignores pagination" gains a `[probe@2026-06-18]` tag (the
claim was untagged; now live-verified).

## Data flow
fetch (latest 10) → `normalize_device` → `as_dict` → `_merge_device_messages`
(union-by-id with persisted list → link photos → debounced save) → set on
`MowerState.device_messages` → sensor `items` attr + state=len. On boot: Store
→ seed `device_messages` → first refresh merges new 10 on top.

## Testing
- `merge_device_messages`: dedup by id; existing-priority preserves a stored
  `photos` key when the same id reappears without photos; newest-first by date;
  cap truncation; empty/None inputs.
- Persist/restore: save a list, reload, assert round-trip; bad/empty store →
  empty list, no raise.
- Both sites accumulate: simulate two successive fetches with overlapping ids →
  union grows, no dupes, capped.
- Device sensor `native_value == len(items)`; service/shared still unread-count.

## Verification (live, after release)
Over time / across a restart, confirm `device_messages` `items` grows past 10 and
persists across an HA restart; sensor state equals the item count.
