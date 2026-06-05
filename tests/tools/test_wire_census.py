from __future__ import annotations
import json
from tools.inventory.wire_census_lib import build_census


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


from tools.inventory.wire_census_lib import check_coverage


def test_check_coverage_passes_when_all_values_parked():
    census = {"s5p104": {"siid": 5, "piid": 104, "value_kind_hint": "enum",
                         "values": [7, 12], "shape_sigs": [], "is_blob": False}}
    inv = {(5, 104): {"value_kind": "enum",
                      "observed_values": [{"value": 7, "status": "confirmed"},
                                          {"value": 12, "status": "unknown"}]}}
    assert check_coverage(census, inv) == []


def test_check_coverage_flags_unparked_value():
    census = {"s5p105": {"siid": 5, "piid": 105, "value_kind_hint": "enum",
                         "values": [1, 2, 3, 4, 5], "shape_sigs": [], "is_blob": False}}
    inv = {(5, 105): {"value_kind": "enum",
                      "observed_values": [{"value": v, "status": "confirmed"} for v in (1, 2, 4)]}}
    viols = check_coverage(census, inv)
    assert any("s5p105" in v and "3" in v for v in viols)
    assert any("s5p105" in v and "5" in v for v in viols)


def test_check_coverage_flags_unregistered_property():
    census = {"s9p9": {"siid": 9, "piid": 9, "value_kind_hint": "enum",
                       "values": [1], "shape_sigs": [], "is_blob": False}}
    viols = check_coverage(census, {})
    assert any("s9p9" in v and "no inventory entry" in v for v in viols)


def test_check_coverage_skips_counter_value_enumeration():
    census = {"s5p107": {"siid": 5, "piid": 107, "value_kind_hint": "counter",
                         "values": list(range(256)), "shape_sigs": [], "is_blob": False}}
    inv = {(5, 107): {"value_kind": "counter", "observed_values": []}}
    assert check_coverage(census, inv) == []


def test_check_coverage_checks_nested_shape_sigs():
    census = {"s2p50": {"siid": 2, "piid": 50, "value_kind_hint": "nested",
                        "values": [], "shape_sigs": ["d,t", "exe,o,status"], "is_blob": False}}
    inv = {(2, 50): {"value_kind": "nested",
                     "observed_shapes": [{"sig": "d,t", "status": "confirmed"}]}}
    viols = check_coverage(census, inv)
    assert any("s2p50" in v and "exe,o,status" in v for v in viols)


import yaml
from tools.inventory.wire_census_lib import seed_blocks


def test_seed_blocks_emits_valid_yaml_for_enum_and_nested():
    census = {
        "s5p104": {"siid": 5, "piid": 104, "value_kind_hint": "enum",
                   "values": [7, 12], "shape_sigs": [], "is_blob": False},
        "s2p50": {"siid": 2, "piid": 50, "value_kind_hint": "nested",
                  "values": [], "shape_sigs": ["d,t"], "is_blob": False},
        "s1p1": {"siid": 1, "piid": 1, "value_kind_hint": "blob",
                 "values": [], "shape_sigs": [], "is_blob": True},
    }
    text = seed_blocks(census)
    parsed = yaml.safe_load(text)
    assert parsed["s5p104"]["value_kind"] == "enum"
    assert {ov["value"] for ov in parsed["s5p104"]["observed_values"]} == {7, 12}
    # all seeded values start parked as unknown (decoder fills in meaning later)
    assert all(ov["status"] == "unknown" for ov in parsed["s5p104"]["observed_values"])
    assert parsed["s2p50"]["observed_shapes"][0]["sig"] == "d,t"
    assert parsed["s1p1"]["value_kind"] == "blob"
    assert "observed_values" not in parsed["s1p1"]  # blobs: presence only


import subprocess, sys, os


def test_cli_writes_census_json(tmp_path):
    logdir = tmp_path / "logs"
    logdir.mkdir()
    (logdir / "probe_log_1.jsonl").write_text(_line(5, 104, 7) + "\n" + _line(5, 104, 12) + "\n")
    out = tmp_path / "wire-census.json"
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    r = subprocess.run(
        [sys.executable, "tools/inventory/wire_census.py", "--log-dir", str(logdir), "--out", str(out)],
        cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    data = json.loads(out.read_text())
    assert data["s5p104"]["values"] == [7, 12]
