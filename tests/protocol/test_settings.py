"""Tests for SETTINGS decoder + read-modify-write helper."""
from __future__ import annotations

import json
from pathlib import Path

from custom_components.dreame_a2_mower.protocol.settings import (
    parse_settings_batch,
    write_setting,
)

FIXTURE = Path(__file__).parent / "fixtures" / "2026-05-08-settings-sample.json"


def _load():
    return json.loads(FIXTURE.read_text())


# Live 2-map structure [probe:settings_dump@2026-06-19]: top-level index = map,
# inner "0" = the map's general (map-level) setting; "1"+ are per-zone slots.
# map1 general dir 26, map2 general dir 118 (≠ each other — proves top-level is
# per-map, not user/firmware-mirror).
_LIVE_2MAP = [
    {"mode": 0, "settings": {
        "0": {"mowingDirection": 26, "mowingDirectionMode": 2, "mowingHeight": 5},
        "1": {"mowingDirection": 180, "mowingDirectionMode": 0, "mowingHeight": 6},
    }},
    {"mode": 0, "settings": {
        "0": {"mowingDirection": 118, "mowingDirectionMode": 2, "mowingHeight": 5},
        "1": {"mowingDirection": 180, "mowingDirectionMode": 0, "mowingHeight": 6},
        "2": {"mowingDirection": 180, "mowingDirectionMode": 0, "mowingHeight": 6},
    }},
]


def test_parse_canonical_is_per_map_general_slot():
    """Top-level index = map; by_map_id_canonical[map] = that map's general '0'."""
    raw = _load()
    result = parse_settings_batch(raw)
    assert set(result.by_map_id_canonical.keys()) == {0, 1}
    assert result.by_map_id_canonical[0]["mowingDirection"] == 0     # raw[0].settings['0']
    assert result.by_map_id_canonical[1]["mowingDirection"] == 180   # raw[1].settings['0']


def test_parse_reads_second_map_general_not_first_maps_zone():
    """Regression for the map2 mis-read: map2's value comes from raw[1]['0']
    (=118), NOT raw[0]['1'] (=180, which is map1's zone-1 slot)."""
    result = parse_settings_batch(_LIVE_2MAP)
    assert result.by_map_id_canonical[0]["mowingDirection"] == 26   # map1 general
    assert result.by_map_id_canonical[1]["mowingDirection"] == 118  # map2 general (was wrongly 180)


def test_parse_preserves_full_raw():
    """The full list (both top-level entries) is preserved verbatim."""
    raw = _load()
    result = parse_settings_batch(raw)
    assert result.raw == raw
    assert len(result.raw) == 2


def test_write_setting_targets_only_that_maps_general_slot():
    """Writing map 1 lands in raw[1].settings['0'] ONLY — it must NOT touch
    map 0's entry (the old 'write every entry' behaviour clobbered other maps)."""
    new_raw = write_setting(_LIVE_2MAP, map_id=1, field="mowingHeight", value=7)
    assert new_raw[1]["settings"]["0"]["mowingHeight"] == 7        # target map's general
    assert new_raw[0]["settings"]["0"]["mowingHeight"] == 5        # map 0 UNTOUCHED
    # per-zone slots of the target map untouched too
    assert new_raw[1]["settings"]["1"]["mowingHeight"] == 6


def test_write_setting_unknown_map_id_raises():
    try:
        write_setting(_LIVE_2MAP, map_id=99, field="mowingHeight", value=7)
    except KeyError as ex:
        assert "99" in str(ex)
    else:
        raise AssertionError("write_setting should raise KeyError on unknown map_id")


def test_write_setting_returns_new_object():
    """write_setting is non-mutating: returns a new list, leaves input alone."""
    raw = _load()
    original_height = raw[0]["settings"]["0"]["mowingHeight"]
    new_raw = write_setting(raw, map_id=0, field="mowingHeight", value=7)
    assert raw[0]["settings"]["0"]["mowingHeight"] == original_height
    assert new_raw is not raw


def test_parse_handles_missing_settings_key():
    """If entry 0 has no `settings` dict, by_map_id_canonical is
    empty (defensive)."""
    result = parse_settings_batch([{"mode": 0}])
    assert result.by_map_id_canonical == {}


def test_parse_handles_empty_list():
    result = parse_settings_batch([])
    assert result.raw == []
    assert result.by_map_id_canonical == {}
