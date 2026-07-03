"""P2 Task 2 (T3-2 / R-5): first-refresh cloud failure must not crash setup.

Before this fix, `coordinator.cloud_state` stayed `None` whenever the very
first `_refresh_cloud_state()` fetch failed (fresh install, or an HA reboot
that races a Dreame-cloud blip), but `_async_update_data` never raised — so
`async_config_entry_first_refresh()` "succeeded" and
`hass.config_entries.async_forward_entry_setups` went ahead and forwarded to
every platform. Five platform `async_setup_entry` functions dereference
`coordinator.cloud_state.maps_by_id` unguarded (camera/__init__.py,
switch.py, select.py x2, sensor.py, number.py), so each one crashed with
`AttributeError: 'NoneType' object has no attribute 'maps_by_id'`.

Locked decision (.superpowers/sdd/task-2-brief.md): raise
`ConfigEntryNotReady` when the FIRST cloud fetch fails (HA retries setup
with backoff — the correct public-install semantics), AND give every
platform loop a cheap `maps_by_id = coordinator.cloud_state.maps_by_id if
coordinator.cloud_state else {}` guard as defense-in-depth (a reload racing
a mid-life `cloud_state=None` must not crash either).
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from homeassistant.exceptions import ConfigEntryNotReady

import custom_components.dreame_a2_mower.camera as camera_platform
import custom_components.dreame_a2_mower.number as number_platform
import custom_components.dreame_a2_mower.select as select_platform
import custom_components.dreame_a2_mower.sensor as sensor_platform
import custom_components.dreame_a2_mower.switch as switch_platform
from custom_components.dreame_a2_mower.const import DOMAIN
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.mower.state import MowerState

# The five platforms T3-2 identified as dereferencing
# `coordinator.cloud_state.maps_by_id` unguarded in their async_setup_entry.
_MAP_AWARE_PLATFORMS = [
    switch_platform,
    select_platform,
    sensor_platform,
    number_platform,
    camera_platform,
]


# ---------------------------------------------------------------------------
# Coordinator first-refresh contract
# ---------------------------------------------------------------------------

def _make_coordinator_stub(*, refresh_succeeds: bool) -> DreameA2MowerCoordinator:
    """A real (uninitialised) coordinator instance for exercising just the
    new `_refresh_cloud_state_or_raise` method — mirrors the
    `_make_coordinator_with_cloud` pattern in test_coordinator.py
    (`object.__new__` skips `__init__`; only the attributes the method
    under test touches are set).
    """
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.cloud_state = None

    async def _fake_refresh_cloud_state() -> None:
        if refresh_succeeds:
            coord.cloud_state = MagicMock(maps_by_id={0: MagicMock()})
        # else: simulate the real _refresh_cloud_state failure path, which
        # logs a warning and returns without touching self.cloud_state.

    coord._refresh_cloud_state = _fake_refresh_cloud_state  # type: ignore[method-assign]
    return coord


def test_first_refresh_failure_raises_config_entry_not_ready():
    """Step 1/3 of the brief: a failed first fetch must raise
    ConfigEntryNotReady, not silently proceed with cloud_state=None."""
    coord = _make_coordinator_stub(refresh_succeeds=False)

    with pytest.raises(ConfigEntryNotReady):
        asyncio.run(coord._refresh_cloud_state_or_raise())

    assert coord.cloud_state is None


def test_first_refresh_success_does_not_raise():
    """A healthy first fetch must not raise, and cloud_state lands."""
    coord = _make_coordinator_stub(refresh_succeeds=True)

    asyncio.run(coord._refresh_cloud_state_or_raise())

    assert coord.cloud_state is not None


# ---------------------------------------------------------------------------
# Platform setup: cloud_state=None (and the 0-map / 3-map parametrization)
# ---------------------------------------------------------------------------

class _FakeHass:
    """Minimal hass — just enough for the five platforms' async_setup_entry.

    Only camera/__init__.py touches `hass.http` (view registration); the
    other four only read `hass.data[DOMAIN][entry.entry_id]`.
    """

    def __init__(self, coordinator) -> None:
        self.data = {DOMAIN: {"entry-1": coordinator}}
        self.http = MagicMock()


def _run_platform_setup(module, coordinator) -> list:
    """Drive one platform's async_setup_entry and return the built entities."""
    hass = _FakeHass(coordinator)
    entry = MagicMock()
    entry.entry_id = "entry-1"
    collected: list = []
    asyncio.run(module.async_setup_entry(hass, entry, collected.extend))
    return collected


def _make_map_coordinator(map_ids: list[int]):
    """A MagicMock coordinator whose cloud_state.maps_by_id has exactly the
    given map ids (each a MagicMock map object), or is `None` entirely if
    `map_ids` is `None` (the crash scenario)."""
    coordinator = MagicMock()
    coordinator.data = MowerState()
    if map_ids is None:
        coordinator.cloud_state = None
    else:
        maps_by_id = {}
        for map_id in map_ids:
            m = MagicMock()
            m.map_id = map_id
            m.name = f"Map {map_id}"
            maps_by_id[map_id] = m
        coordinator.cloud_state = MagicMock(maps_by_id=maps_by_id)
    return coordinator


@pytest.mark.parametrize("module", _MAP_AWARE_PLATFORMS, ids=lambda m: m.__name__)
def test_platform_setup_none_cloud_state_matches_empty_maps(module):
    """Step 1/3 of the brief (platform half): cloud_state=None must build
    exactly the entities that 0 known maps would build (i.e. zero per-map
    entities), not raise AttributeError.

    Comparing against the explicit empty-`maps_by_id` case (rather than
    asserting an absolute count) pins the guard's behaviour without
    hard-coding how many non-map entities each platform happens to build
    today.
    """
    none_state = _make_map_coordinator(None)
    entities_none = _run_platform_setup(module, none_state)

    empty_maps = _make_map_coordinator([])
    entities_empty = _run_platform_setup(module, empty_maps)

    assert len(entities_none) == len(entities_empty)
    # Sanity: the platform still builds its non-map entities.
    assert len(entities_none) > 0


@pytest.mark.parametrize("module", _MAP_AWARE_PLATFORMS, ids=lambda m: m.__name__)
@pytest.mark.parametrize("map_count", [0, 3], ids=["0-maps", "3-maps"])
def test_platform_setup_scales_with_map_count(module, map_count):
    """T7-22 scope: entity-setup counts scale correctly across 0 and 3 maps
    (not just the welded 2-map fixture)."""
    coordinator = _make_map_coordinator(list(range(map_count)))
    entities = _run_platform_setup(module, coordinator)

    baseline = _run_platform_setup(module, _make_map_coordinator([]))
    per_map_entity_count = len(entities) - len(baseline)

    if map_count == 0:
        assert per_map_entity_count == 0
    else:
        # However many per-map entities one map contributes, N maps must
        # contribute exactly N times as many (linear scaling, no crash).
        one_map = _run_platform_setup(module, _make_map_coordinator([0]))
        per_map_unit = len(one_map) - len(baseline)
        assert per_map_entity_count == per_map_unit * map_count
