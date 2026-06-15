"""Re-export shim — ``map_decoder`` relocated to ``protocol/map_decoder.py``.

The cloud-map parser lives under ``protocol/`` now (it parses cloud JSON →
dataclasses, matching the ``parse_*`` decoder-naming convention). This shim
preserves the ~31 deep-import sites across the codebase + tests
(CLAUDE.md § "Public-import preservation"). New code should import from
``.protocol.map_decoder`` directly.

Explicit re-export list (NOT ``import *``): two helpers and three module
constants are underscore-prefixed, which ``*`` would not carry, and the test
suite imports them by name.
"""
from __future__ import annotations

from .protocol.map_decoder import (  # noqa: F401
    CHARGER_OFFSET_MM,
    GRID_SIZE_MM,
    ExclusionZone,
    MaintenancePoint,
    MapData,
    MowingZone,
    NavPath,
    PatrolPoint,
    SpotZone,
    apply_session_geometry,
    join_map_parts,
    parse_cloud_map,
    parse_cloud_maps,
    _collect_exclusion_entries,
    _parse_cruise_points,
)
