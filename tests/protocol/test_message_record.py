import json

from custom_components.dreame_a2_mower.protocol.message_record import (
    Message,
    normalize_service,
    normalize_device,
    normalize_share,
    unread_count,
)


def _svc_rec(name, content, link, read, mid="1", ts=1780000000):
    return {
        "id": mid,
        "readStatus": read,        # 1 = read, 0 = unread
        "createTime": ts,
        "multiLangDisplay": json.dumps(
            {"en": {"name": name, "content": content, "link": link}}
        ),
    }


def test_normalize_service_maps_fields_and_unread():
    recs = [_svc_rec("Summer sale", "30% off", "https://x", 0, "9", 1780000900)]
    out = normalize_service(recs)
    assert out == [
        Message(
            id="9",
            title="Summer sale",
            date="2026-05-28T20:41:40+00:00",  # 1780000900 UTC
            body="30% off",
            link="https://x",
            unread=True,
        )
    ]


def test_normalize_service_orders_newest_first():
    recs = [_svc_rec("old", "", None, 1, "1", 1000), _svc_rec("new", "", None, 1, "2", 2000)]
    out = normalize_service(recs)
    assert [m.id for m in out] == ["2", "1"]


def test_normalize_service_tolerates_missing_keys():
    assert normalize_service([{"id": "x"}]) == [
        Message(id="x", title="", date=None, body=None, link=None, unread=True)
    ]


def test_normalize_device_has_no_read_flag_so_all_unread():
    recs = [
        {
            "messageId": "m1",
            "sendTime": 1780000000,
            "multiLangDisplay": json.dumps({"en": {"name": "Right drive wheel error"}}),
        }
    ]
    out = normalize_device(recs)
    assert out[0].id == "m1"
    assert out[0].title == "Right drive wheel error"
    assert out[0].unread is True  # device has no reliable read flag → treated unread


def test_normalize_share_defensive_returns_messages():
    out = normalize_share([{"id": "s1", "title": "Home shared with you"}])
    assert len(out) == 1 and out[0].id == "s1"


def test_unread_count_counts_unread():
    msgs = [
        Message("1", "a", None, None, None, True),
        Message("2", "b", None, None, None, False),
    ]
    assert unread_count(msgs) == 1
