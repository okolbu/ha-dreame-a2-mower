"""Tests for the g2408 property-mapping overlay in dreame/types.py.

These tests require `homeassistant` to be importable — the parent package's
__init__ imports from it. When HA isn't installed in the dev venv (the
default for the Plan B pure-Python test environment), the tests skip
cleanly. The overlay is exercised live on HA during Plan C Task 10.
"""

from __future__ import annotations

import importlib

import pytest


def _import_types():
    try:
        return importlib.import_module(
            "custom_components.dreame_a2_mower.dreame.types"
        )
    except ImportError:
        pytest.skip(
            "homeassistant not installed in venv; overlay exercised during "
            "live deploy in Task 10"
        )


def test_overlay_exports_function():
    types = _import_types()
    assert hasattr(types, "property_mapping_for_model")
    assert callable(types.property_mapping_for_model)


def test_g2408_mapping_swaps_state_and_error_piid():
    types = _import_types()
    mapping = types.property_mapping_for_model("dreame.mower.g2408")
    assert mapping[types.DreameMowerProperty.STATE] == {"siid": 2, "piid": 2}
    assert mapping[types.DreameMowerProperty.ERROR] == {"siid": 2, "piid": 1}


def test_g2408_mapping_preserves_battery_mapping():
    types = _import_types()
    mapping = types.property_mapping_for_model("dreame.mower.g2408")
    assert mapping[types.DreameMowerProperty.BATTERY_LEVEL] == {"siid": 3, "piid": 1}


def test_unknown_model_returns_upstream_mapping_unchanged():
    types = _import_types()
    mapping = types.property_mapping_for_model("dreame.mower.unknown_model")
    assert mapping is types.DreameMowerPropertyMapping
