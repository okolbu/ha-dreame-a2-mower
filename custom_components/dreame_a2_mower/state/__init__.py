"""State layer (P3.6): MowerState (composed of 8 domain containers),
CloudState, StateSnapshot, MowerStateMachine, and the pure property/CFG
apply funnel.

Layer 3 in the target architecture (``docs/superpowers/specs/
2026-07-02-refactor-v2-target-architecture.md`` §1): imports only
protocol/transport/foundation, never domain/entity/presentation.

Modules land here across the P3.6 sub-tasks:
  - containers.py   — the 8 frozen sub-dataclasses + value enums
  - mower_state.py  — MowerState = composition of the containers
  - snapshot.py     — StateSnapshot + dimension enums (from mower/)
  - machine.py      — MowerStateMachine (from mower/)
  - cloud_state.py  — CloudState aggregate (from root cloud_state.py)
  - apply.py        — pure (siid,piid,value)/CFG -> MowerState apply
"""
from __future__ import annotations

from .containers import (
    ActionMode as ActionMode,
    ChargingStatus as ChargingStatus,
    State as State,
)
from .machine import MowerStateMachine as MowerStateMachine
from .mower_state import FLAT_FIELDS as FLAT_FIELDS, MowerState as MowerState
from .snapshot import StateSnapshot as StateSnapshot
