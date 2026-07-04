"""Back-compat re-export shim (P3.6): ``StateSnapshot`` + its dimension
enums moved to ``state/snapshot.py`` (the state layer).

New code should import from ``..state.snapshot`` directly. Retired with the
P3.10 import-path rewrite.
"""
from __future__ import annotations

from ..state.snapshot import (  # noqa: F401 — re-export
    Connectivity as Connectivity,
    CurrentActivity as CurrentActivity,
    Location as Location,
    MowSession as MowSession,
    PositioningHealth as PositioningHealth,
    RpcHealth as RpcHealth,
    StateSnapshot as StateSnapshot,
)

__all__ = [
    "MowSession",
    "CurrentActivity",
    "Location",
    "PositioningHealth",
    "Connectivity",
    "RpcHealth",
    "StateSnapshot",
]
