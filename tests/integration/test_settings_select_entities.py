"""Tests for per-map SETTINGS-driven select entities (v1.0.10a7).

Replaces the prior mower-scoped active-map-follower tests — the 3 SETTINGS
selects (mowingDirection, mowingDirectionMode, edgeMowingWalkMode) now live
on map sub-devices, one entity per map, reading from
``cloud_state.settings.by_map_id_canonical``.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.dreame_a2_mower.const import DOMAIN


@pytest.mark.parametrize("cls_name,key", [
    ("DreameA2PerMapMowingDirectionSelect", "settings_mowing_direction"),
    ("DreameA2PerMapMowingDirectionModeSelect", "settings_mowing_direction_mode"),
    ("DreameA2PerMapTurningMethodSelect", "settings_turning_method"),
    ("DreameA2PerMapEdgeMowingWalkModeSelect", "settings_edge_mowing_walk_mode"),
])
def test_per_map_settings_select_unique_id_and_device(
    coordinator_with_two_maps, cls_name, key
):
    coord = coordinator_with_two_maps
    import custom_components.dreame_a2_mower.select as select_mod
    cls = getattr(select_mod, cls_name)

    e0 = cls(coord, map_id=0)
    e1 = cls(coord, map_id=1)

    assert e0._attr_unique_id == f"G2408000TESTSN0000_map_0_{key}"
    assert e1._attr_unique_id == f"G2408000TESTSN0000_map_1_{key}"
    assert e0._attr_device_info["identifiers"] == {
        (DOMAIN, "G2408000TESTSN0000_map_0")
    }


def test_per_map_mowing_direction_reads_correct_map(coordinator_with_two_maps):
    """Per-map MowingDirection picks the option corresponding to its map_id."""
    coord = coordinator_with_two_maps
    cs = MagicMock()
    cs.settings.by_map_id_canonical = {
        0: {"mowingDirection": 0},
        1: {"mowingDirection": 180},
    }
    coord.cloud_state = cs

    import custom_components.dreame_a2_mower.select as select_mod
    e0 = select_mod.DreameA2PerMapMowingDirectionSelect(coord, map_id=0)
    e1 = select_mod.DreameA2PerMapMowingDirectionSelect(coord, map_id=1)
    assert e0.current_option == "0°"
    assert e1.current_option == "180°"


def test_per_map_mowing_pattern_reads_correct_map(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    cs = MagicMock()
    cs.settings.by_map_id_canonical = {
        0: {"mowingDirectionMode": 0},
        1: {"mowingDirectionMode": 2},
    }
    coord.cloud_state = cs

    import custom_components.dreame_a2_mower.select as select_mod
    e0 = select_mod.DreameA2PerMapMowingDirectionModeSelect(coord, map_id=0)
    e1 = select_mod.DreameA2PerMapMowingDirectionModeSelect(coord, map_id=1)
    assert e0.current_option == "Crisscross"
    assert e1.current_option == "Chequerboard"


def test_per_map_edge_walk_mode_reads_correct_map(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    cs = MagicMock()
    cs.settings.by_map_id_canonical = {
        0: {"edgeMowingWalkMode": 0},
        1: {"edgeMowingWalkMode": 1},
    }
    coord.cloud_state = cs

    import custom_components.dreame_a2_mower.select as select_mod
    e0 = select_mod.DreameA2PerMapEdgeMowingWalkModeSelect(coord, map_id=0)
    e1 = select_mod.DreameA2PerMapEdgeMowingWalkModeSelect(coord, map_id=1)
    assert e0.current_option == "walk_0"
    assert e1.current_option == "walk_1"


# ---------------------------------------------------------------------------
# Turning Method (PRE[19] / SETTINGS.steeringMode) — fw-0625 OTA add.
# ---------------------------------------------------------------------------


def test_turning_method_options_and_current(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    cs = MagicMock()
    cs.settings.by_map_id_canonical = {0: {"steeringMode": 1}}
    coord.cloud_state = cs

    import custom_components.dreame_a2_mower.select as select_mod
    sel = select_mod.DreameA2PerMapTurningMethodSelect(coord, map_id=0)
    assert sel._attr_options == ["Efficient", "Lawn-Care"]
    assert sel.current_option == "Lawn-Care"


async def test_turning_method_write_uses_pre_index_19(
    coordinator_with_two_maps, monkeypatch
):
    coord = coordinator_with_two_maps
    cs = MagicMock()
    cs.settings.by_map_id_canonical = {0: {"steeringMode": 1}}
    coord.cloud_state = cs

    import custom_components.dreame_a2_mower.select as select_mod
    sel = select_mod.DreameA2PerMapTurningMethodSelect(coord, map_id=0)

    captured: dict = {}

    async def _fake(*a, **k):
        captured.update(k)

    monkeypatch.setattr(
        "custom_components.dreame_a2_mower.entities.select.map_settings."
        "pre_settings_optimistic_write",
        _fake,
    )
    await sel.async_select_option("Efficient")
    assert captured["pre_index"] == 19
    assert captured["pre_value"] == 0
    assert captured["settings_field"] == "steeringMode"
    assert captured["state_field"] == "settings_turning_method"


def test_turning_method_unavailable_when_no_steeringmode(coordinator_with_two_maps):
    """fw-0550 short PRE / no steeringMode in SETTINGS → current_option None."""
    coord = coordinator_with_two_maps
    cs = MagicMock()
    cs.settings.by_map_id_canonical = {0: {}}
    coord.cloud_state = cs

    import custom_components.dreame_a2_mower.select as select_mod
    sel = select_mod.DreameA2PerMapTurningMethodSelect(coord, map_id=0)
    assert sel.current_option is None  # → available False


def test_apply_pre_short_array_refuses_index_19():
    """fw-0550 PRE is 19 ints; writing index 19 must NOT IndexError — apply_pre
    returns None (no base) so _write_pre_scoped aborts gracefully."""
    from custom_components.dreame_a2_mower.protocol import cfg_payloads
    short = list(range(19))  # indices 0..18 only (fw 0550)
    assert cfg_payloads.apply_pre(short, map_idx=0, index=19, value=0) is None
    full = list(range(21))  # fw 0625
    out = cfg_payloads.apply_pre(full, map_idx=0, index=19, value=1)
    assert out is not None and out[19] == 1
