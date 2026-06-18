# Accumulate device messages to 200 (todo7 #1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `sensor.dreame_a2_mower_device_messages` retain up to 200 messages by merging each fetch's latest-10 into a persisted, deduped list (instead of replacing), surviving restarts.

**Architecture:** A pure `merge_device_messages` helper unions by `id` (existing-priority, newest-first, capped). A coordinator method merges each fetch into `MowerState.device_messages`, links snapshot photos, and debounce-saves to an HA `Store`; a boot restore seeds the list from disk. The device sensor's state becomes the total count. Service/shared lists are untouched.

**Tech Stack:** Python (Home Assistant custom component); `homeassistant.helpers.storage.Store`; vanilla-pytest venv at `/data/claude/homeassistant/.venv-vanilla/bin/python`.

**Test command (throughout):** `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest <path> -q`. System python3 is broken — never use it. Stage commits by EXPLICIT path; never `git add -A` (a second process commits with `add -A`; there are untracked `tools/probes/oss_*` files that are NOT ours).

**Message dict shape** (from `protocol/message_record.py` `Message.as_dict`): `{"id": str, "title": str, "date": str|None (ISO-8601), "body": None, "link": None, "unread": True}`; `link_message_snapshot_photos` may add `"photos": [...]`. The dedup key is `id`; the sort key is `date`.

---

### Task 1: Pure `merge_device_messages` helper

**Files:**
- Modify: `custom_components/dreame_a2_mower/protocol/message_record.py` (add function)
- Test: `tests/unit/test_message_record.py` (create if absent; otherwise append)

- [ ] **Step 1: Write the failing tests**

Create/append `tests/unit/test_message_record.py`:

```python
from custom_components.dreame_a2_mower.protocol.message_record import (
    merge_device_messages,
)


def _m(i, date, **extra):
    return {"id": i, "title": f"t{i}", "date": date, "body": None,
            "link": None, "unread": True, **extra}


def test_merge_unions_by_id_newest_first():
    existing = [_m("b", "2026-06-18 10:00:00"), _m("a", "2026-06-18 09:00:00")]
    fresh = [_m("c", "2026-06-18 11:00:00"), _m("b", "2026-06-18 10:00:00")]
    out = merge_device_messages(existing, fresh, cap=10)
    assert [m["id"] for m in out] == ["c", "b", "a"]  # newest-first, no dup b


def test_merge_existing_priority_preserves_photos():
    # 'b' already stored WITH photos; the fresh copy lacks photos → keep stored.
    existing = [_m("b", "2026-06-18 10:00:00", photos=["p1"])]
    fresh = [_m("b", "2026-06-18 10:00:00")]
    out = merge_device_messages(existing, fresh, cap=10)
    assert out[0]["photos"] == ["p1"]


def test_merge_caps_to_newest():
    existing = [_m("a", "2026-06-18 08:00:00")]
    fresh = [_m("c", "2026-06-18 10:00:00"), _m("b", "2026-06-18 09:00:00")]
    out = merge_device_messages(existing, fresh, cap=2)
    assert [m["id"] for m in out] == ["c", "b"]  # 'a' dropped (oldest beyond cap)


def test_merge_handles_empty_and_missing_dates():
    assert merge_device_messages([], [], cap=5) == []
    out = merge_device_messages([], [_m("a", None), _m("b", "2026-06-18 09:00:00")], cap=5)
    assert out[0]["id"] == "b"  # dated sorts before undated
    assert {m["id"] for m in out} == {"a", "b"}


def test_merge_skips_entries_without_id():
    out = merge_device_messages([], [{"id": "", "date": "x"}, _m("a", "y")], cap=5)
    assert [m["id"] for m in out] == ["a"]
```

- [ ] **Step 2: Run, verify FAIL**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_message_record.py -q`
Expected: FAIL — `merge_device_messages` undefined / ImportError.

- [ ] **Step 3: Implement the helper**

Append to `protocol/message_record.py` (pure — no HA imports; it already has `from typing import Any`):

```python
def merge_device_messages(
    existing: list[dict], fresh: list[dict], cap: int
) -> list[dict]:
    """Merge a freshly-fetched device-message page into the accumulated list.

    device-messages/v2 is a fixed window of the latest ~10 (server-capped,
    pagination ignored — [probe@2026-06-18]), so the only way to retain more is
    to accumulate. Union by ``id`` with EXISTING-PRIORITY: an id already present
    keeps its stored dict (preserving a linked ``photos`` key and the immutable
    text); only ids new to ``existing`` are taken from ``fresh``. Result is
    sorted newest-first by ``date`` (ISO-8601 str; missing/non-str dates sort
    last) and truncated to ``cap``. Entries with a falsy ``id`` are dropped.
    """
    by_id: dict[str, dict] = {}
    for m in existing:
        mid = m.get("id")
        if mid:
            by_id[mid] = m
    for m in fresh:
        mid = m.get("id")
        if mid and mid not in by_id:
            by_id[mid] = m

    def _key(m: dict) -> tuple[int, str]:
        d = m.get("date")
        # Present dates → (1, date) sort FIRST (newest) under reverse=True;
        # missing/non-str dates → (0, "") sort LAST.
        return (1, d) if isinstance(d, str) and d else (0, "")

    ordered = sorted(by_id.values(), key=_key, reverse=True)
    return ordered[:cap] if cap >= 0 else ordered
```

- [ ] **Step 4: Run, verify PASS**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_message_record.py -q`
Expected: PASS. (The `_key` puts present dates at `(1, date)` and missing at `(0, "")`, so under `reverse=True` dated entries sort newest-first and undated land last — `test_merge_handles_empty_and_missing_dates` pins this.)

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/message_record.py tests/unit/test_message_record.py
git commit -m "feat(messages): pure merge_device_messages (union-by-id, newest-first, capped)"
```

---

### Task 2: Raise cap default + tag the verified server-cap docstring

**Files:**
- Modify: `custom_components/dreame_a2_mower/const.py` (`DEFAULT_MESSAGES_KEEP`)
- Modify: `custom_components/dreame_a2_mower/cloud_client/_fetchers.py` (`fetch_device_messages` docstring)
- Test: `tests/unit/test_message_record.py` (no new test needed; const change is covered by accumulation tests later)

- [ ] **Step 1: Bump the default**

In `const.py`, change `DEFAULT_MESSAGES_KEEP: Final = 100` to:

```python
DEFAULT_MESSAGES_KEEP: Final = 200
```

- [ ] **Step 2: Tag the verified docstring**

In `cloud_client/_fetchers.py`, in `fetch_device_messages`, change the docstring sentence
`Server caps `page_size` at 10 and ignores pagination — this is a` to:

```
        Server caps `page_size` at 10 and ignores pagination (pageNum 2+ returns
        the same latest-10) [probe@2026-06-18] — this is a
```

- [ ] **Step 3: Sanity-run a quick suite slice**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_message_record.py -q`
Expected: PASS (unchanged). The default bump has no isolated test; it's exercised by Task 3/4 accumulation + the full suite in Task 6.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/const.py custom_components/dreame_a2_mower/cloud_client/_fetchers.py
git commit -m "feat(messages): raise message-keep default to 200; tag verified device-msg server cap"
```

---

### Task 3: Coordinator `_merge_device_messages` + wire both refresh sites

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_core.py` (`__init__`: add store field)
- Modify: `custom_components/dreame_a2_mower/coordinator/_notifications.py` (add method; rewire `_apply_device_messages`)
- Modify: `custom_components/dreame_a2_mower/coordinator/_refreshers.py` (rewire `_refresh_messages` device block)
- Test: `tests/integration/test_device_messages_accumulate.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_device_messages_accumulate.py`:

```python
import dataclasses
from types import SimpleNamespace

from custom_components.dreame_a2_mower.coordinator._notifications import (
    _NotificationsMixin,
)
from custom_components.dreame_a2_mower.mower.state import MowerState


def _rec(mid, send_time, text="hello"):
    return {
        "messageId": mid,
        "sendTime": send_time,
        "localizationContents": {"en": text},
        "source": {"siid": "2", "piid": "2", "value": "0"},
    }


def _bare_coord(existing_msgs, *, cap=200):
    c = _NotificationsMixin()
    c.data = MowerState(device_messages=list(existing_msgs))
    c.entry = SimpleNamespace(options={"messages_keep": cap})
    c.link_message_snapshot_photos = lambda lst: None  # no-op stub
    c._device_messages_store = None  # no store in this test
    captured = {}

    def _set(state):
        captured["state"] = state
    c.async_set_updated_data = _set
    return c, captured


def test_apply_device_messages_accumulates_not_replaces():
    # Start with one already-stored message 'old'.
    existing = [{"id": "old", "title": "old", "date": "2026-06-18T08:00:00+00:00",
                 "body": None, "link": None, "unread": True}]
    c, captured = _bare_coord(existing)
    # A fresh page carrying a NEW message 'new'.
    c._apply_device_messages([_rec("new", "2026-06-18 10:00:00")])
    ids = [m["id"] for m in captured["state"].device_messages]
    assert "old" in ids and "new" in ids  # accumulated, not replaced
    assert ids[0] == "new"  # newest first


def test_merge_device_messages_returns_capped_union():
    existing = [{"id": f"e{i}", "title": "x", "date": f"2026-06-18T0{i}:00:00+00:00",
                 "body": None, "link": None, "unread": True} for i in range(3)]
    c, _ = _bare_coord(existing, cap=4)
    fresh = [{"id": "z", "title": "z", "date": "2026-06-18T09:00:00+00:00",
              "body": None, "link": None, "unread": True}]
    merged = c._merge_device_messages(fresh)
    assert merged[0]["id"] == "z"  # newest
    assert len(merged) == 4  # capped
```

- [ ] **Step 2: Run, verify FAIL**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_device_messages_accumulate.py -q`
Expected: FAIL — `_merge_device_messages` undefined.

- [ ] **Step 3: Add the store field in `_core.py __init__`**

In `coordinator/_core.py`, find `self._state_store: Store | None = None  # initialised in _async_update_data` (~line 419) and add directly after it:

```python
        self._device_messages_store: Store | None = None  # initialised in _async_update_data
```

- [ ] **Step 4: Add `_merge_device_messages` to `_notifications.py`**

In `coordinator/_notifications.py`, near the top add a module constant (after the imports):

```python
# Debounce window for persisting the accumulated device-message list.
DEVICE_MESSAGES_SAVE_DELAY_S = 5
```

Add this method to `_NotificationsMixin` (next to `_apply_device_messages`):

```python
    def _merge_device_messages(self, fresh_dicts: list[dict]) -> list[dict]:
        """Merge a freshly-fetched device-message page into the accumulated list.

        Unions by id with the persisted list (existing wins → keeps linked
        `photos` + immutable text), newest-first, capped at CONF_MESSAGES_KEEP,
        links snapshot photos, and schedules a debounced persist. Returns the
        merged list. The cloud windows device-messages/v2 to the latest ~10, so
        accumulation is the only way to retain more.
        """
        from ..protocol.message_record import merge_device_messages

        entry = getattr(self, "entry", None)
        cap = int(
            entry.options.get(CONF_MESSAGES_KEEP, DEFAULT_MESSAGES_KEEP)
            if entry is not None else DEFAULT_MESSAGES_KEEP
        )
        existing = list(getattr(self.data, "device_messages", None) or [])
        merged = merge_device_messages(existing, fresh_dicts, cap)
        self.link_message_snapshot_photos(merged)
        store = getattr(self, "_device_messages_store", None)
        if store is not None:
            store.async_delay_save(lambda: merged, DEVICE_MESSAGES_SAVE_DELAY_S)
        return merged
```

Confirm `CONF_MESSAGES_KEEP` and `DEFAULT_MESSAGES_KEEP` are imported in `_notifications.py` (they already are — `_apply_device_messages` uses them). If not, add them to the `from ..const import (...)` block.

- [ ] **Step 5: Rewire `_apply_device_messages` (same file) to accumulate**

Replace the body from the `cap = int(...)` block through the `dataclasses.replace` so it uses the merge method:

```python
    def _apply_device_messages(self, records: list | None) -> None:
        """Reactively refresh ``MowerState.device_messages`` from a freshly
        fetched device-messages/v2 page (called by the s2p2 resolver), merging
        it into the accumulated list so the sensor reflects new notifications
        immediately. No-op on an empty page."""
        if not records:
            return
        fresh = [m.as_dict() for m in message_record.normalize_device(records)]
        merged = self._merge_device_messages(fresh)
        new = dataclasses.replace(self.data, device_messages=merged)
        if new != self.data:
            self.async_set_updated_data(new)
```

(The per-call `cap`/`link_message_snapshot_photos` are gone — both now happen inside `_merge_device_messages`.)

- [ ] **Step 6: Rewire `_refresh_messages` device block in `_refreshers.py`**

In `coordinator/_refreshers.py` `_refresh_messages`, replace the `if dev_raw is not None:` block:

```python
        if dev_raw is not None:
            dev_list = [
                msg.as_dict() for msg in _msg.normalize_device(dev_raw)[:cap]
            ]
            # Link "View snapshots in the app." notifications to their photos.
            self.link_message_snapshot_photos(dev_list)
            kw["device_messages"] = dev_list
```

with:

```python
        if dev_raw is not None:
            fresh = [msg.as_dict() for msg in _msg.normalize_device(dev_raw)]
            kw["device_messages"] = self._merge_device_messages(fresh)
```

(The `cap` local is still used for the service/shared lists below — leave it.)

- [ ] **Step 7: Run, verify PASS**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_device_messages_accumulate.py -q`
Expected: PASS.

- [ ] **Step 8: Run any pre-existing message/notification tests to catch regressions**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q -k "message or notification or refresh" 2>&1 | tail -20`
Expected: PASS. If a pre-existing test asserted REPLACE semantics (e.g. that device_messages exactly equals the latest fetch), update it to the accumulate contract (the list now unions with prior state); note any such change.

- [ ] **Step 9: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_core.py custom_components/dreame_a2_mower/coordinator/_notifications.py custom_components/dreame_a2_mower/coordinator/_refreshers.py tests/integration/test_device_messages_accumulate.py
git commit -m "feat(messages): accumulate device messages by id instead of replacing"
```

---

### Task 4: Persist + restore on boot

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_core.py` (add `_restore_device_messages`; call it in `_async_update_data`)
- Test: `tests/integration/test_device_messages_accumulate.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_device_messages_accumulate.py`:

```python
import asyncio
from custom_components.dreame_a2_mower.coordinator._core import _CoreMixin


class _FakeStore:
    def __init__(self, data):
        self._data = data
    async def async_load(self):
        return self._data


def test_restore_device_messages_seeds_state():
    c = _CoreMixin.__new__(_CoreMixin)
    c.data = MowerState()
    c.entry = SimpleNamespace(entry_id="e1", options={"messages_keep": 200})
    c.hass = SimpleNamespace()
    stored = [{"id": "a", "title": "a", "date": "2026-06-18T09:00:00+00:00",
               "body": None, "link": None, "unread": True}]
    c._device_messages_store = _FakeStore(stored)
    asyncio.run(c._restore_device_messages())
    assert [m["id"] for m in c.data.device_messages] == ["a"]


def test_restore_device_messages_caps_and_tolerates_bad_store():
    c = _CoreMixin.__new__(_CoreMixin)
    c.data = MowerState()
    c.entry = SimpleNamespace(entry_id="e1", options={"messages_keep": 1})
    c.hass = SimpleNamespace()
    stored = [{"id": "a", "date": "2026-06-18T08:00:00+00:00"},
              {"id": "b", "date": "2026-06-18T09:00:00+00:00"}]
    c._device_messages_store = _FakeStore(stored)
    asyncio.run(c._restore_device_messages())
    assert len(c.data.device_messages) == 1  # capped on restore

    class _BadStore:
        async def async_load(self):
            raise RuntimeError("corrupt")
    c2 = _CoreMixin.__new__(_CoreMixin)
    c2.data = MowerState()
    c2.entry = SimpleNamespace(entry_id="e1", options={})
    c2.hass = SimpleNamespace()
    c2._device_messages_store = _BadStore()
    asyncio.run(c2._restore_device_messages())  # must not raise
    assert c2.data.device_messages == []
```

- [ ] **Step 2: Run, verify FAIL**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_device_messages_accumulate.py -k restore -q`
Expected: FAIL — `_restore_device_messages` undefined.

- [ ] **Step 3: Add `_restore_device_messages` to `_core.py`**

Confirm `_core.py` imports `CONF_MESSAGES_KEEP` and `DEFAULT_MESSAGES_KEEP` from `..const`; if not, add them to the existing `from ..const import (...)` block. Add this method to `_CoreMixin` (near `_async_update_data`):

```python
    async def _restore_device_messages(self) -> None:
        """Seed MowerState.device_messages from the persisted store on boot so
        the sensor shows retained history immediately and it becomes the merge
        base for the first fetch. Tolerates a missing/corrupt store."""
        if self._device_messages_store is None:
            self._device_messages_store = Store(
                self.hass,
                version=1,
                key=f"dreame_a2_mower_device_messages_{self.entry.entry_id}",
            )
        try:
            stored = await self._device_messages_store.async_load()
        except Exception:
            LOGGER.exception("device_messages restore failed; continuing empty")
            return
        if isinstance(stored, list) and stored:
            cap = int(
                self.entry.options.get(CONF_MESSAGES_KEEP, DEFAULT_MESSAGES_KEEP)
            )
            self.data.device_messages = stored[:cap]
```

- [ ] **Step 4: Call it from `_async_update_data` first-run block**

In `_core.py` `_async_update_data`, inside `if not hasattr(self, "_cloud"):`, after the `state_machine.load_persisted` try/except block and before `self._cloud = await self.hass.async_add_executor_job(self._init_cloud)`, add:

```python
            await self._restore_device_messages()
```

- [ ] **Step 5: Run, verify PASS**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_device_messages_accumulate.py -q`
Expected: PASS (all, including restore tests).

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_core.py tests/integration/test_device_messages_accumulate.py
git commit -m "feat(messages): persist accumulated device messages + restore on boot"
```

---

### Task 5: Device sensor state = total count

**Files:**
- Modify: `custom_components/dreame_a2_mower/entities/sensor/device.py` (`DreameA2DeviceMessagesSensor`)
- Test: `tests/integration/test_cloud_state_sensors.py` (append) — or wherever message-sensor tests live; check first.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_cloud_state_sensors.py`:

```python
def test_device_messages_sensor_state_is_total_not_unread():
    from custom_components.dreame_a2_mower.entities.sensor.device import (
        DreameA2DeviceMessagesSensor,
    )
    from types import SimpleNamespace

    s = object.__new__(DreameA2DeviceMessagesSensor)
    s.coordinator = SimpleNamespace(
        data=SimpleNamespace(device_messages=[
            {"id": "a", "unread": True}, {"id": "b", "unread": True},
            {"id": "c", "unread": True},
        ])
    )
    assert s.native_value == 3  # total count, not an unread subset
    assert s.extra_state_attributes["items"] == s._items()
```

- [ ] **Step 2: Run, verify FAIL**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_cloud_state_sensors.py::test_device_messages_sensor_state_is_total_not_unread -q`
Expected: FAIL — base `native_value` returns the unread count (which here equals 3, so it may PASS by coincidence). To make the test meaningful, also assert against a mixed read/unread case where total != unread:

```python
    s.coordinator.data.device_messages.append({"id": "d", "unread": False})
    assert s.native_value == 4  # total, even though one is 'read'
```

Add that to the test BEFORE running, so the test genuinely fails on the base (which would return 3).

- [ ] **Step 3: Override `native_value` on the device sensor**

In `entities/sensor/device.py`, in `class DreameA2DeviceMessagesSensor(_DreameA2MessageListSensor)`, add:

```python
class DreameA2DeviceMessagesSensor(_DreameA2MessageListSensor):
    """Device-targeted messages (device_messages list).

    State is the TOTAL retained count (not the unread subset): device-messages/v2
    gives no read flag, so every message is 'unread' — an unread-count state
    would just climb to the cap. The newest-first history stays in `items`.
    """

    _attr_name = "Device messages"
    _attr_icon = "mdi:robot"
    _MOWER_KEY = "device_messages"
    _FIELD = "device_messages"

    @property
    def native_value(self) -> int:
        return len(self._items())
```

- [ ] **Step 4: Run, verify PASS**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_cloud_state_sensors.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/entities/sensor/device.py tests/integration/test_cloud_state_sensors.py
git commit -m "feat(messages): device-messages sensor state = total retained count"
```

---

### Task 6: Entity-inventory, full suite, release + live-verify

**Files:**
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml`

- [ ] **Step 1: Update entity-inventory.yaml**

Find the `sensor.dreame_a2_mower_device_messages` entry (key likely `device_messages`). Update it to reflect: (a) state is now the TOTAL retained count (was unread count); (b) the list ACCUMULATES (merge-by-id) up to `CONF_MESSAGES_KEEP` (default now 200) and is PERSISTED across restarts via a `Store`. Add a `verifications:` row dated `2026-06-18`, status `presumed` (code-read; live-verified after release), claim summarizing the accumulate+persist behavior and the device-messages/v2 latest-10 server cap `[probe@2026-06-18]`. Match the file's existing schema (read neighboring sensor entries first).

- [ ] **Step 2: Validate inventory schema (if entity-inventory is gated)**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only`
Expected: `ok: inventory schema valid`. (This validates `inventory.yaml`; `entity-inventory.yaml` is validated by a test in the full suite — Step 3 covers it.)

- [ ] **Step 3: Run the FULL suite**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q --ignore=tests/archive`
Expected: all pass (baseline ~2504 + the new tests). KNOWN pre-existing unrelated failures may exist only if introduced by other branches — none expected here. Fix any failure caused by THIS feature:
- A `test_card_contract` / message-shape test asserting the device_messages dict keys or REPLACE semantics → update to the accumulate contract.
- An entity-inventory coverage/consistency test → satisfied by Step 1.
- `test_readme_in_sync` AppleDouble crash from `tools/probes/._*` files → already guarded; if it recurs, the guard is in `tools/gen_readme.py`.
Re-run until green.

- [ ] **Step 4: Commit docs**

```bash
git add custom_components/dreame_a2_mower/entity-inventory.yaml
git commit -m "docs(messages): entity-inventory for device-message accumulation"
```

- [ ] **Step 5: Release + live-verify (controller does this; not a subagent step)**

Push, move untracked `tools/probes/oss_*` aside for a clean tree, run `tools/release/release.sh --notes "..."`, restore the probes, install via HACS, restart HA. Then verify on live HA:
1. `sensor.dreame_a2_mower_device_messages` state == length of its `items` (total count).
2. Over time the `items` list grows past 10 as new notifications arrive.
3. After an HA restart, the accumulated `items` persist (not reset to ≤10).

---

## Notes / gotchas
- Test interpreter: `/data/claude/homeassistant/.venv-vanilla/bin/python`. Stage by explicit path; leave untracked `tools/probes/oss_*` alone.
- The merge is EXISTING-PRIORITY: a re-seen id keeps its stored copy (frozen text + `photos`). Device-message text is immutable, so nothing is lost.
- `async_delay_save(lambda: merged, 5)` debounces writes and is safe from the reactive sync path (`_apply_device_messages`) and the async refresh path.
- Service/shared message lists are NOT accumulated — they still replace (their endpoints return full lists).
- `MowerState` is `slots=True` but mutable, so `self.data.device_messages = ...` works during restore.
