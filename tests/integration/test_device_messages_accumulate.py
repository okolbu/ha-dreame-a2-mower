import asyncio
import dataclasses
from types import SimpleNamespace

from custom_components.dreame_a2_mower.coordinator._notifications import (
    _NotificationsMixin,
)
from custom_components.dreame_a2_mower.state import MowerState


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


class _AsyncLoadStore:
    def __init__(self, data):
        self._data = data
    async def async_load(self):
        return self._data


def _stub_photo_deps(c):
    """Give a bare _CoreMixin the deps _restore_device_messages needs to re-link
    photos: an executor to run the (blocking) photo-index load on, and an
    archive. Without these the re-link falls into its except branch, so the test
    would pass while silently exercising the error path."""
    async def _exec(fn, *a):
        return fn(*a)
    c.hass = SimpleNamespace(async_add_executor_job=_exec)
    c._photo_archive = SimpleNamespace(load_index=lambda: None)
    c.link_message_snapshot_photos = lambda lst: None
    return c


def test_restore_device_messages_seeds_state():
    c = _CoreMixin.__new__(_CoreMixin)
    c.data = MowerState()
    c.entry = SimpleNamespace(entry_id="e1", options={"messages_keep": 200})
    _stub_photo_deps(c)
    stored = [{"id": "a", "title": "a", "date": "2026-06-18T09:00:00+00:00",
               "body": None, "link": None, "unread": True}]
    c._device_messages_store = _AsyncLoadStore(stored)
    asyncio.run(c._restore_device_messages())
    assert [m["id"] for m in c.data.device_messages] == ["a"]


def test_restore_device_messages_caps_and_tolerates_bad_store():
    c = _CoreMixin.__new__(_CoreMixin)
    c.data = MowerState()
    c.entry = SimpleNamespace(entry_id="e1", options={"messages_keep": 1})
    _stub_photo_deps(c)
    stored = [{"id": "b", "date": "2026-06-18T09:00:00+00:00"},
              {"id": "a", "date": "2026-06-18T08:00:00+00:00"}]
    c._device_messages_store = _AsyncLoadStore(stored)
    asyncio.run(c._restore_device_messages())
    assert [m["id"] for m in c.data.device_messages] == ["b"]  # newest retained, oldest dropped

    class _BadStore:
        async def async_load(self):
            raise RuntimeError("corrupt")
    c2 = _CoreMixin.__new__(_CoreMixin)
    c2.data = MowerState()
    c2.entry = SimpleNamespace(entry_id="e1", options={})
    _stub_photo_deps(c2)
    c2._device_messages_store = _BadStore()
    asyncio.run(c2._restore_device_messages())  # must not raise
    assert c2.data.device_messages == []


# --- signed URLs must never reach the persisted store ------------------------
#
# A signed photo URL is a CREDENTIAL, not data: HA's http sign secret is
# regenerated per process (`secrets.token_hex()` at http setup), so every
# restart invalidates every previously-issued signature REGARDLESS of its 7-day
# `exp`. Persisting the URL therefore guarantees a 401 after any restart:
# _restore_device_messages seeds the sensor straight from disk with signatures
# minted by a dead process.
#
# Live evidence 2026-07-16: a persisted signature with exp 2026-07-23 (valid)
# returned 401, while a freshly-minted signature for the SAME path returned 200
# with the JPEG. The photo gallery never had this bug because it rebuilds its
# manifest in memory at boot and so is always signed by the running process.
#
# The URL is fully DERIVED — link_message_snapshot_photos recomputes it from the
# photo archive on every merge — so it never needed persisting.


def _photo_msg():
    return {
        "id": "m1",
        "title": "Human entry detected. View snapshots in the app.",
        "date": "2026-06-21T17:43:11+00:00",
        "body": None, "link": None, "unread": True,
        "photos": [{
            "id": "a.jpg", "ts": 1782063795, "category": "ai_human",
            "detections": [{"cls": "person"}],
            "url": "/api/dreame_a2_mower/photo/a.jpg?authSig=DEAD",
            "thumb_url": "/api/dreame_a2_mower/photo/a.jpg?authSig=DEAD",
        }],
    }


def test_persisted_messages_carry_no_signed_url():
    calls = []

    class _FakeStore:
        def async_delay_save(self, data_func, delay):
            calls.append(data_func())

    c, _ = _bare_coord([_photo_msg()])
    c._device_messages_store = _FakeStore()
    c._merge_device_messages([])

    saved = calls[0]
    blob = repr(saved)
    assert "authSig" not in blob, "a signed URL reached the persisted store"
    # The photo IDENTITY must survive — it's what the re-link matches on.
    photo = saved[0]["photos"][0]
    assert photo["id"] == "a.jpg"
    assert photo["ts"] == 1782063795
    assert photo["category"] == "ai_human"
    assert photo["detections"] == [{"cls": "person"}]


def test_merge_keeps_signed_url_in_memory():
    """Stripping is for the STORE only — the live list still needs the URL,
    otherwise the card has nothing to render between merges."""
    c, _ = _bare_coord([_photo_msg()])
    c._device_messages_store = None
    merged = c._merge_device_messages([])
    assert merged[0]["photos"][0]["url"].endswith("authSig=DEAD")


def test_persist_does_not_mutate_the_live_list():
    """The strip must copy — mutating the merged list in place would blank the
    URLs out from under the sensor that is about to publish them."""
    calls = []

    class _FakeStore:
        def async_delay_save(self, data_func, delay):
            calls.append(data_func())

    c, _ = _bare_coord([_photo_msg()])
    c._device_messages_store = _FakeStore()
    merged = c._merge_device_messages([])
    assert "authSig" not in repr(calls[0])
    assert merged[0]["photos"][0]["url"].endswith("authSig=DEAD"), "live list was mutated"


async def test_restore_relinks_photo_urls():
    """Restore must RE-SIGN, not just seed.

    The store no longer holds signed URLs (they are a per-process credential —
    see strip_signed_urls), so a restore that only seeds would leave the sensor
    publishing photo dicts with no URL until the first hourly merge. Re-linking
    at restore mints signatures with the CURRENT process's secret, which is what
    the photo gallery effectively does by rebuilding at boot.
    """
    from custom_components.dreame_a2_mower.coordinator._core import _CoreMixin

    stored = [{
        "id": "m1", "title": "Human entry detected. View snapshots in the app.",
        "date": "2026-06-21T17:43:11+00:00", "body": None, "link": None,
        "unread": True,
        # As persisted: identity only, no url/thumb_url.
        "photos": [{"id": "a.jpg", "ts": 1782063795, "category": "ai_human",
                    "detections": []}],
    }]

    class _Store:
        async def async_load(self):
            return stored

    c = object.__new__(_CoreMixin)
    c.data = MowerState()
    c._device_messages_store = _Store()
    c.entry = SimpleNamespace(options={})
    relinked = []
    c.link_message_snapshot_photos = lambda lst: relinked.append(lst)
    executor_jobs = []

    async def _exec(fn, *a):
        executor_jobs.append(fn)
        return fn(*a)

    c.hass = SimpleNamespace(async_add_executor_job=_exec)
    c._photo_archive = SimpleNamespace(load_index=lambda: None)

    await c._restore_device_messages()

    assert [m["id"] for m in c.data.device_messages] == ["m1"]
    assert relinked, "restore did not re-link (photos would have no signed URL)"
    assert relinked[0] is c.data.device_messages
    # PhotoArchive.load_index is blocking ("call from an executor") and this
    # runs inside boot's _timed critical path, before the gallery refresh warms
    # the index. Reading it on the event loop is the startup-stall regression
    # class fixed in v2.0.3–2.0.6.
    assert c._photo_archive.load_index in executor_jobs, (
        "the photo index must be loaded via an executor, not on the event loop"
    )


async def test_restore_survives_a_broken_photo_archive():
    """A photo-archive failure must not lose the restored message text."""
    from custom_components.dreame_a2_mower.coordinator._core import _CoreMixin

    class _Store:
        async def async_load(self):
            return [{"id": "m1", "title": "t", "date": "2026-06-21T17:43:11+00:00",
                     "body": None, "link": None, "unread": True}]

    c = object.__new__(_CoreMixin)
    c.data = MowerState()
    c._device_messages_store = _Store()
    c.entry = SimpleNamespace(options={})

    async def _boom(fn, *a):
        raise OSError("index.json is toast")

    c.hass = SimpleNamespace(async_add_executor_job=_boom)
    c._photo_archive = SimpleNamespace(load_index=lambda: None)
    c.link_message_snapshot_photos = lambda lst: None

    await c._restore_device_messages()  # must not raise
    assert [m["id"] for m in c.data.device_messages] == ["m1"]
