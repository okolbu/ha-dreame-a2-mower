"""Re-export shim — ``_rotate_path_around_centroid`` relocated to
``protocol/map/geom.py`` (P3 map-decoder package split, track-2 autopsy #8).

Preserved for the two test importers (``test_cloud_map_geom``,
``test_map_decoder``); new code imports from ``protocol.map.geom``. Shim
retirement is P3.10.
"""

from __future__ import annotations

from .map.geom import _rotate_path_around_centroid  # noqa: F401
