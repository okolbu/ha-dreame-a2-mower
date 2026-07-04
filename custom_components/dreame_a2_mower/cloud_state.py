"""Back-compat re-export shim (P3.6): the ``CloudState`` aggregate moved to
``state/cloud_state.py`` (the state layer, where it is composed by the
refresh service — R-31/T2-6).

The protocol decoder output types (``MowPathData``/``ScheduleData``/
``SchedulePlan``/``ScheduleSlot``/``SettingsRoot``) are still re-exported
here verbatim so the ~20 importers that reach them through ``cloud_state``
keep working. New code should import ``CloudState`` from ``..state`` /
``..state.cloud_state`` and the protocol types from ``protocol/`` directly.
Retired with the P3.10 import-path rewrite.
"""
from __future__ import annotations

from .state.cloud_state import (  # noqa: F401 — re-export
    CloudState as CloudState,
    MowPathData as MowPathData,
    ScheduleData as ScheduleData,
    SchedulePlan as SchedulePlan,
    ScheduleSlot as ScheduleSlot,
    SettingsRoot as SettingsRoot,
)

__all__ = [
    "CloudState",
    "MowPathData",
    "ScheduleData",
    "SchedulePlan",
    "ScheduleSlot",
    "SettingsRoot",
]
