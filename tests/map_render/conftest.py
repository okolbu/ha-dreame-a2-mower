"""Shared fixtures for tests/map_render/.

``make_map_data()`` returns a small synthetic MapData built via parse_cloud_map,
with one mowing zone polygon.  Reuses the same ``_MINIMAL_MAP`` fixture already
used in tests/integration/test_map_decoder.py so the construction is known-good.
"""
from __future__ import annotations

import sys
import pathlib

_REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.integration.test_map_decoder import _MINIMAL_MAP  # noqa: E402
from custom_components.dreame_a2_mower.protocol.map import parse_cloud_map  # noqa: E402


def make_map_data():
    """Return a minimal synthetic MapData with one mowing zone."""
    md = parse_cloud_map(_MINIMAL_MAP)
    assert md is not None, "parse_cloud_map returned None for _MINIMAL_MAP"
    return md
