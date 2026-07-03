"""Re-export shim — ``map_decoder`` relocated to the ``protocol/map/`` package.

The cloud-map parser is now the ``protocol/map/`` package (``types`` /
``parse`` / ``parts`` / ``geom`` / ``shapes`` — split from the 1077-LOC
``map_decoder.py`` in P3, track-2 autopsy #8). This shim preserves the ~31
deep-import sites across the codebase + tests
(CLAUDE.md § "Public-import preservation"). New code should import from
``.protocol.map`` directly; the import rewrite + shim retirement is P3.10.

Explicit re-export list (NOT ``import *``): two helpers and three module
constants are underscore-prefixed, which ``*`` would not carry, and the test
suite imports them by name.
"""
from __future__ import annotations

from .protocol.map import (  # noqa: F401
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
