"""CONTROL_MODES (code) must equal the control_mode verdicts in the inventory.

Keeps the runtime source (control_honesty.CONTROL_MODES) and the documentation
source (entity-inventory.yaml control_mode / control_mode_by_key) from drifting.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from custom_components.dreame_a2_mower.control_honesty import CONTROL_MODES

INV = Path(__file__).resolve().parents[2] / "custom_components" / "dreame_a2_mower" / "entity-inventory.yaml"
CONTROL_PLATFORMS = {"number", "select", "switch", "time", "lawn_mower", "button"}


def _inventory_modes() -> dict[str, object]:
    data = yaml.safe_load(INV.read_text())
    out: dict[str, object] = {}
    for e in data["entities"]:
        if e.get("platform") not in CONTROL_PLATFORMS:
            continue
        if str(e.get("class", "")).startswith("("):  # tombstone
            continue
        mode = e["control_mode"]
        out[e["id"]] = e["control_mode_by_key"] if mode == "per_key" else mode
    return out


def _code_modes() -> dict[str, object]:
    out: dict[str, object] = {}
    for k, v in CONTROL_MODES.items():
        out[k] = {kk: str(vv) for kk, vv in v.items()} if isinstance(v, dict) else str(v)
    return out


def test_code_and_inventory_control_modes_match():
    code, inv = _code_modes(), _inventory_modes()
    only_code = sorted(set(code) - set(inv))
    only_inv = sorted(set(inv) - set(code))
    mismatched = {k: (code[k], inv[k]) for k in set(code) & set(inv) if code[k] != inv[k]}
    assert not only_code, f"ids in CONTROL_MODES but not inventory: {only_code}"
    assert not only_inv, f"control ids in inventory but not CONTROL_MODES: {only_inv}"
    assert not mismatched, f"control_mode mismatches (code, inventory): {mismatched}"
