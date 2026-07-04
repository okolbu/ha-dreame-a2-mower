"""Back-compat re-export shim (P3.6): ``MowerStateMachine`` moved to
``state/machine.py`` (the state layer).

New code should import from ``..state.machine`` directly. Retired with the
P3.10 import-path rewrite.
"""
from __future__ import annotations

from ..state.machine import MowerStateMachine as MowerStateMachine  # noqa: F401

__all__ = ["MowerStateMachine"]
