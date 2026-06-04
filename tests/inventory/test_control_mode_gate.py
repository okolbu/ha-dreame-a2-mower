"""Control-honesty gate: every control entity declares a `control_mode`.

Closes the loop on the 2026-06-03 control-honesty audit
(`docs/research/control-honesty-audit-2026-06-03.md`). A control-platform
entity (number/select/switch/time/lawn_mower/button) renders an interactive
HA control; whether that control actually reaches the g2408 firmware varies
per entity. This gate forces every control entity in entity-inventory.yaml to
carry an explicit honesty verdict so a new control can't ship un-classified.

Allowed `control_mode` values (see the audit doc for the A–E buckets):
  - device_writable        (A) reaches firmware AND proven applied
  - device_write_unproven  (B) real device RPC, not live-proven on g2408
  - integration_local      (E) no device write by design; controls integration
                               state/rendering/selection — honest & operable
  - read_only_pending          believed ineffective, unconfirmed (needs probe)
  - read_only_confirmed    (C) cloud accepts but firmware does NOT apply
  - read_only_noop         (D) handler is a deliberate logged no-op

A class collapsing several CFG keys with DIFFERENT verdicts (the generic
DreameA2Switch / DreameA2Number families) uses the scalar `control_mode: per_key`
plus a `control_mode_by_key:` mapping whose every value is one of the modes above.
"""
from __future__ import annotations

from pathlib import Path

import yaml

INV = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "dreame_a2_mower"
    / "entity-inventory.yaml"
)

CONTROL_PLATFORMS = {"number", "select", "switch", "time", "lawn_mower", "button"}
VALID_MODES = {
    "device_writable",
    "device_write_unproven",
    "integration_local",
    "read_only_pending",
    "read_only_confirmed",
    "read_only_noop",
}


def _control_entities() -> list[dict]:
    data = yaml.safe_load(INV.read_text())
    out = []
    for e in data["entities"]:
        if e.get("platform") not in CONTROL_PLATFORMS:
            continue
        # Tombstones ("(removed …)") record a deleted entity; exempt.
        if str(e.get("class", "")).startswith("("):
            continue
        out.append(e)
    return out


def test_every_control_entity_has_a_valid_control_mode() -> None:
    bad: list[str] = []
    for e in _control_entities():
        eid = e.get("id", "<no-id>")
        mode = e.get("control_mode")
        if mode is None:
            bad.append(f"{eid}: missing control_mode")
            continue
        if mode == "per_key":
            by_key = e.get("control_mode_by_key")
            if not isinstance(by_key, dict) or not by_key:
                bad.append(f"{eid}: control_mode=per_key but no control_mode_by_key map")
                continue
            for k, v in by_key.items():
                if v not in VALID_MODES:
                    bad.append(f"{eid}: control_mode_by_key[{k}]={v!r} not a valid mode")
        elif mode not in VALID_MODES:
            bad.append(f"{eid}: control_mode={mode!r} not a valid mode")
    assert not bad, "control_mode gate failures:\n" + "\n".join(bad)
