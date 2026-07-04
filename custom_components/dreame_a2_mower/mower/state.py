"""Back-compat re-export shim (P3.6): ``MowerState`` and its value enums
moved to the ``state/`` package (the T2-15 container split).

The typed model now lives in:
  - ``state/containers.py``  — the 8 frozen domain sub-dataclasses +
    the value enums (``State``, ``ActionMode``, ``ChargingStatus``)
  - ``state/mower_state.py``  — ``MowerState`` = composition of the containers

This shim preserves the ~86 test importers + the production
``from ..mower.state import MowerState`` sites unchanged. New code should
import from ``..state`` / ``..state.mower_state`` directly. Retired with the
P3.10 import-path rewrite.
"""
from __future__ import annotations

from ..state.containers import (  # noqa: F401 — re-export
    ActionMode as ActionMode,
    ChargingStatus as ChargingStatus,
    State as State,
)
from ..state.mower_state import (  # noqa: F401 — re-export
    FLAT_FIELDS as FLAT_FIELDS,
    MowerState as MowerState,
)

__all__ = ["State", "ActionMode", "ChargingStatus", "MowerState", "FLAT_FIELDS"]
