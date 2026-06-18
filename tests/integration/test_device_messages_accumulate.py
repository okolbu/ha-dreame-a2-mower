import asyncio
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
    existing = [{"id": "old", "title": "old", "date": "2026-06-18T08:00:00+00:00",
                 "body": None, "link": None, "unread": True}]
    c, captured = _bare_coord(existing)
    c._apply_device_messages([_rec("new", "2026-06-18 10:00:00")])
    ids = [m["id"] for m in captured["state"].device_messages]
    assert "old" in ids and "new" in ids
    assert ids[0] == "new"


def test_merge_device_messages_returns_capped_union():
    existing = [{"id": f"e{i}", "title": "x", "date": f"2026-06-18T0{i}:00:00+00:00",
                 "body": None, "link": None, "unread": True} for i in range(3)]
    c, _ = _bare_coord(existing, cap=4)
    fresh = [{"id": "z", "title": "z", "date": "2026-06-18T09:00:00+00:00",
              "body": None, "link": None, "unread": True}]
    merged = c._merge_device_messages(fresh)
    assert merged[0]["id"] == "z"
    assert len(merged) == 4


def test_merge_device_messages_schedules_store_save():
    """When a store is present, the merged list is scheduled for a debounced
    persist via async_delay_save (the callable returns the merged list)."""
    calls = []

    class _FakeStore:
        def async_delay_save(self, data_func, delay):
            calls.append((data_func(), delay))

    existing = [{"id": "old", "title": "old", "date": "2026-06-18T08:00:00+00:00",
                 "body": None, "link": None, "unread": True}]
    c, _ = _bare_coord(existing)
    c._device_messages_store = _FakeStore()
    fresh = [{"id": "new", "title": "new", "date": "2026-06-18T10:00:00+00:00",
              "body": None, "link": None, "unread": True}]
    merged = c._merge_device_messages(fresh)
    assert len(calls) == 1
    saved, delay = calls[0]
    assert [m["id"] for m in saved] == [m["id"] for m in merged]  # saves the merged list
    assert delay == 5  # DEVICE_MESSAGES_SAVE_DELAY_S


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
    assert len(c.data.device_messages) == 1

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
