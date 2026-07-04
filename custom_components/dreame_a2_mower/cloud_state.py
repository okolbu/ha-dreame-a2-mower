"""CloudState — unified container for all cloud-fetched data.

Replaces the scattered `_cached_*` attributes on the coordinator.
Populated by `_refresh_cloud_state()` (every 2 min) plus the MAPL
probe. DOCK is NOT stored here — it goes directly to MowerState
via its own 60 s timer (`_refresh_dock`).

All sub-dataclasses are frozen + slots for O(1) attribute access
and immutability semantics. Mutation goes through coordinator
helpers that build a new CloudState and replace.

`MowPathData`/`ScheduleData`/`SchedulePlan`/`ScheduleSlot`/`SettingsRoot`
are the protocol DECODERS' own output types (R-29a/T2-4) — their
definitions live in `protocol/m_path.py`, `protocol/schedule_decode.py`,
and `protocol/settings.py` respectively, so those modules no longer
import the state-layer container module. They are re-exported here
verbatim (this is a downward import: state layer -> protocol layer,
not a back-edge) so the ~20 existing production/test importers that
reach them via `cloud_state` keep working unchanged. Only `CloudState`
itself (the state-layer aggregate) is actually defined in this file.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .map_decoder import MapData
from .protocol.m_path import MowPathData as MowPathData
from .protocol.schedule_decode import (
    ScheduleData as ScheduleData,
    SchedulePlan as SchedulePlan,
    ScheduleSlot as ScheduleSlot,
)
from .protocol.settings import SettingsRoot as SettingsRoot


@dataclass(frozen=True, slots=True)
class CloudState:
    """Unified container for all cloud-fetched device state."""

    cfg: dict[str, Any]
    maps_by_id: dict[int, MapData]
    mow_paths_by_map_id: dict[int, MowPathData]
    settings: SettingsRoot
    schedule: ScheduleData
    ai_human_enabled: bool | None
    forbidden_node_types_by_map: dict[int, dict[str, Any]]
    ota_status: tuple[int, int] | None
    task_id: int
    props: dict[str, str]
    mapl: list[list[Any]] | None
    mihis: dict[str, Any]
    fetched_at_unix: int
    # Per-map patrol-point config from the CRUISE.0 device-data key:
    # {map_idx: {point_id: {"cycles": int, "auto_capture": bool}}}. Empty when
    # CRUISE.0 is absent. See protocol/cruise_config.py + inventory.yaml § CRUISED.
    cruise_config_by_map: dict = field(default_factory=dict)
