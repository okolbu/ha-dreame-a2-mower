"""Cloud-map decoder package (split from the 1077-LOC ``map_decoder.py``).

Layout (track-2 autopsy #8): ``types`` = dataclasses, ``parse`` =
``parse_cloud_map`` + collectors + ``apply_session_geometry``, ``parts`` =
``parse_cloud_maps`` / ``join_map_parts``, ``geom`` = pure rotation helper,
``shapes`` = ``DECORATIVE_SHAPE_TYPES`` (wire knowledge; kills the T2-3
back-edge). Public surface preserved for the ``map_decoder`` re-export shim
(retirement is P3.10).
"""

from __future__ import annotations

from .parse import (  # noqa: F401
    apply_session_geometry,
    parse_cloud_map,
    _collect_exclusion_entries,
    _parse_cruise_points,
)
from .parts import join_map_parts, parse_cloud_maps  # noqa: F401
from .shapes import DECORATIVE_SHAPE_TYPES  # noqa: F401
from .types import (  # noqa: F401
    CHARGER_OFFSET_MM,
    GRID_SIZE_MM,
    ExclusionZone,
    MaintenancePoint,
    MapData,
    MowingZone,
    NavPath,
    PatrolPoint,
    SpotZone,
)

__all__ = [
    "CHARGER_OFFSET_MM",
    "GRID_SIZE_MM",
    "DECORATIVE_SHAPE_TYPES",
    "ExclusionZone",
    "MaintenancePoint",
    "MapData",
    "MowingZone",
    "NavPath",
    "PatrolPoint",
    "SpotZone",
    "apply_session_geometry",
    "join_map_parts",
    "parse_cloud_map",
    "parse_cloud_maps",
    "_collect_exclusion_entries",
    "_parse_cruise_points",
]
