from __future__ import annotations
import json
from tools.wire_census_lib import build_census


def _line(siid, piid, value, ts="2026-05-20 13:00:00"):
    return json.dumps({
        "type": "mqtt_message", "timestamp": ts,
        "payload": {"data": {"method": "properties_changed",
                             "params": [{"siid": siid, "piid": piid, "value": value}]}},
    })


def test_build_census_classifies_by_value_type():
    lines = [
        _line(5, 104, 7), _line(5, 104, 12),          # int -> discrete enum
        _line(1, 53, True), _line(1, 53, False),       # bool -> discrete
        _line(2, 50, {"d": {"o": 107}, "t": "TASK"}),  # dict -> nested shape-sig
        _line(1, 1, [206, 0, 0]),                      # list -> blob
        _line(99, 20, "abc"),                          # str -> blob
    ]
    c = build_census(lines)
    assert c["s5p104"]["values"] == [7, 12]
    assert c["s5p104"]["value_kind_hint"] == "enum"
    assert set(c["s1p53"]["values"]) == {0, 1}          # bool normalised to 0/1
    assert c["s2p50"]["shape_sigs"] == ["d,t"]          # sorted top-level keys
    assert c["s2p50"]["value_kind_hint"] == "nested"
    assert c["s1p1"]["is_blob"] is True
    assert c["s1p1"]["value_kind_hint"] == "blob"
    assert c["s99p20"]["is_blob"] is True


def test_build_census_counter_hint_for_wide_int_spread():
    lines = [_line(5, 107, v) for v in range(0, 200, 2)]  # 100 distinct, wide
    c = build_census(lines)
    assert c["s5p107"]["value_kind_hint"] == "counter"


def test_build_census_first_seen_records_earliest_ts():
    lines = [_line(5, 104, 12, "2026-05-25 12:32:24"),
             _line(5, 104, 12, "2026-05-26 09:00:00")]
    c = build_census(lines)
    assert c["s5p104"]["first_seen"]["12"] == "2026-05-25 12:32:24"
