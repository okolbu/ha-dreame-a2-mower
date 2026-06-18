from custom_components.dreame_a2_mower.protocol.message_record import (
    merge_device_messages,
)


def _m(i, date, **extra):
    return {"id": i, "title": f"t{i}", "date": date, "body": None,
            "link": None, "unread": True, **extra}


def test_merge_unions_by_id_newest_first():
    existing = [_m("b", "2026-06-18T10:00:00+00:00"), _m("a", "2026-06-18T09:00:00+00:00")]
    fresh = [_m("c", "2026-06-18T11:00:00+00:00"), _m("b", "2026-06-18T10:00:00+00:00")]
    out = merge_device_messages(existing, fresh, cap=10)
    assert [m["id"] for m in out] == ["c", "b", "a"]


def test_merge_existing_priority_preserves_photos():
    existing = [_m("b", "2026-06-18T10:00:00+00:00", photos=["p1"])]
    fresh = [_m("b", "2026-06-18T10:00:00+00:00")]
    out = merge_device_messages(existing, fresh, cap=10)
    assert out[0]["photos"] == ["p1"]


def test_merge_caps_to_newest():
    existing = [_m("a", "2026-06-18T08:00:00+00:00")]
    fresh = [_m("c", "2026-06-18T10:00:00+00:00"), _m("b", "2026-06-18T09:00:00+00:00")]
    out = merge_device_messages(existing, fresh, cap=2)
    assert [m["id"] for m in out] == ["c", "b"]


def test_merge_handles_empty_and_missing_dates():
    assert merge_device_messages([], [], cap=5) == []
    out = merge_device_messages([], [_m("a", None), _m("b", "2026-06-18T09:00:00+00:00")], cap=5)
    assert out[0]["id"] == "b"
    assert {m["id"] for m in out} == {"a", "b"}


def test_merge_skips_entries_without_id():
    out = merge_device_messages([], [{"id": "", "date": "x"}, _m("a", "y")], cap=5)
    assert [m["id"] for m in out] == ["a"]
