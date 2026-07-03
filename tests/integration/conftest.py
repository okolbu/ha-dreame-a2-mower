"""Conftest for integration tests.

F1.4.2 tests are non-HA (they only exercise the pure apply_property_to_state
function). homeassistant is not installed in this environment yet
(pytest-homeassistant-custom-component is wired in F1.4.3). We inject
minimal stubs so the coordinator module can be imported and the class
definition parsed without errors.
"""
from __future__ import annotations

import sys
import types


def _patch_missing_stubs() -> None:
    """Add any sub-module stubs that weren't present in an earlier call."""
    if "homeassistant.components.logbook" not in sys.modules:
        ha_components = sys.modules.setdefault(
            "homeassistant.components",
            types.ModuleType("homeassistant.components"),
        )
        ha_logbook = types.ModuleType("homeassistant.components.logbook")
        ha_logbook.LOGBOOK_ENTRY_MESSAGE = "message"
        ha_logbook.LOGBOOK_ENTRY_NAME = "name"
        sys.modules["homeassistant.components.logbook"] = ha_logbook
        # Expose as attribute so dotted access works too.
        sys.modules["homeassistant.components"] = ha_components

    # Ensure homeassistant.core has the symbols used by logbook.py.
    ha_core = sys.modules.get("homeassistant.core")
    if ha_core is not None:
        if not hasattr(ha_core, "callback"):
            ha_core.callback = lambda fn: fn  # type: ignore[attr-defined]
        if not hasattr(ha_core, "Event"):
            ha_core.Event = type("Event", (), {})  # type: ignore[attr-defined]
        if not hasattr(ha_core, "HomeAssistant"):
            ha_core.HomeAssistant = type("HomeAssistant", (), {})  # type: ignore[attr-defined]


# P3 Task 1 (T7-7): the full `_stub_homeassistant()` body that used to live
# here was DEAD CODE — the root tests/conftest.py installs its homeassistant
# stub at import time, so the "homeassistant in sys.modules" early-return
# always fired and this file's richer DataUpdateCoordinator stub never
# installed. The faithful coordinator stub now lives in the ROOT conftest
# (the one layer that actually wins); this file only patches in the
# integration-test-only sub-modules the root stub doesn't carry.
_patch_missing_stubs()


import pytest  # noqa: E402


@pytest.fixture
def coordinator_with_two_maps():
    from unittest.mock import MagicMock
    from custom_components.dreame_a2_mower.coordinator import (
        DreameA2MowerCoordinator,
    )

    # spec=DreameA2MowerCoordinator is omitted: the stub DataUpdateCoordinator
    # doesn't declare `hass` as a class attribute, so spec= would prevent
    # setting it and the guard in _sync_map_subdevices would short-circuit.
    coord = MagicMock()
    coord.sn = "G2408000TESTSN0000"
    coord.hass = MagicMock()
    coord.entry = MagicMock()
    coord.entry.entry_id = "abc123"
    coord._cloud = MagicMock()
    coord._cloud.serial_number = "G2408000TESTSN0000"
    coord._cloud.mac_address = "ef:ce:cc:aa:fe:fd"
    coord._cloud.model = "dreame.mower.g2408"
    m0 = MagicMock()
    m0.map_id = 0
    m0.name = "Front"
    m1 = MagicMock()
    m1.map_id = 1
    m1.name = "Back"
    coord.cloud_state.maps_by_id = {0: m0, 1: m1}
    # Bind the real method so the test exercises actual logic.
    coord._sync_map_subdevices = (
        DreameA2MowerCoordinator._sync_map_subdevices.__get__(coord)
    )
    return coord


def make_empty_cloud_state(**overrides):
    """Build a minimal real CloudState for tests that need dataclasses.replace.

    All fields default to empty; pass overrides (e.g. maps_by_id=...) as needed.
    """
    from custom_components.dreame_a2_mower.cloud_state import (
        CloudState,
        ScheduleData,
        SettingsRoot,
    )

    base = dict(
        cfg={},
        maps_by_id={},
        mow_paths_by_map_id={},
        settings=SettingsRoot(raw=[], by_map_id_canonical={}),
        schedule=ScheduleData(version=0, slots=()),
        ai_human_enabled=None,
        forbidden_node_types_by_map={},
        ota_status=None,
        task_id=0,
        props={},
        mapl=None,
        mihis={},
        fetched_at_unix=0,
    )
    base.update(overrides)
    return CloudState(**base)
