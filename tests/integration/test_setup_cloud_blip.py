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
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.exceptions import ConfigEntryNotReady

import custom_components.dreame_a2_mower.button as button_platform
import custom_components.dreame_a2_mower.camera as camera_platform
import custom_components.dreame_a2_mower.number as number_platform
import custom_components.dreame_a2_mower.select as select_platform
import custom_components.dreame_a2_mower.sensor as sensor_platform
import custom_components.dreame_a2_mower.switch as switch_platform
from custom_components.dreame_a2_mower.const import DOMAIN
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.mower.state import MowerState

from tests.factories import make_coordinator

# The six platforms whose async_setup_entry dereferences
# `coordinator.cloud_state.maps_by_id` unguarded: the five T3-2 named plus
# button.py (found in review — its per-map DreameA2HeadToPointButton loop
# had the identical crash).
_MAP_AWARE_PLATFORMS = [
    switch_platform,
    select_platform,
    sensor_platform,
    number_platform,
    camera_platform,
    button_platform,
]


# ---------------------------------------------------------------------------
# Coordinator first-refresh contract
# ---------------------------------------------------------------------------

def _make_coordinator_stub(*, refresh_succeeds: bool) -> DreameA2MowerCoordinator:
    """A REAL coordinator (P3 Task 1: factory-built through the real
    __init__, which seeds ``cloud_state = None`` — the exact fresh-install
    precondition this test exercises) with only the one network-touching
    collaborator, `_refresh_cloud_state`, stubbed per scenario.
    """
    coord = make_coordinator()
    assert coord.cloud_state is None  # real __init__ precondition, not seeded

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


# ---------------------------------------------------------------------------
# Final P2 review (Task 2 x Task 8 interaction): ConfigEntryNotReady from
# async_config_entry_first_refresh() must tear down both transports before
# propagating.
#
# By the time first_refresh can raise ConfigEntryNotReady,
# _async_update_data has already run _init_cloud (cloud login + API worker
# thread + requests.Session) and _init_mqtt (paho thread, connected) — see
# coordinator/_core.py. HA does NOT call async_unload_entry when
# async_setup_entry itself raises, and hass.data[DOMAIN] is not populated
# yet at the point of the raise (__init__.py sets it only AFTER
# first_refresh succeeds), so Task 8's teardown (async_unload_entry) never
# runs. Each HA setup retry then builds a brand new coordinator + transports
# on top of the previous ones that never disconnected — a leaking paho
# thread + cloud worker per retry, with the zombie staying MQTT-subscribed
# and able to fire duplicate hass.bus events alongside the eventual live
# coordinator.
# ---------------------------------------------------------------------------


class _SetupFakeHass:
    """Minimal hass for driving async_setup_entry up to the first-refresh
    call. Executor jobs run synchronously (mirrors the pattern in
    test_unload_lifecycle.py's _FakeHass)."""

    def __init__(self) -> None:
        self.data: dict = {}
        self.executor_jobs: list = []
        self.config = SimpleNamespace(path=lambda *parts: "/fake/" + "/".join(parts))

    async def async_add_executor_job(self, func, *args):
        self.executor_jobs.append(func)
        return func(*args)


def _make_failing_coordinator(*, has_mqtt: bool = True, has_cloud: bool = True):
    """A coordinator stand-in whose first refresh raises ConfigEntryNotReady,
    with optional partially-initialised transports (accessor-guard coverage:
    a real coordinator could have _mqtt set without _cloud, or vice versa,
    depending on exactly where _init_cloud/_init_mqtt got to).

    P3.2: `__init__.py` now reads `coordinator.mqtt` / `coordinator.cloud`
    (the typed, hasattr-tolerant accessors on the real coordinator class)
    instead of `getattr(coordinator, "_mqtt"/"_cloud", None)`. This
    SimpleNamespace stand-in is not a real coordinator instance, so it
    can't inherit that property — it must model the accessor's RESOLVED
    value directly (`None` when the transport was never initialised) via
    always-present `mqtt`/`cloud` attributes. The private `_mqtt`/`_cloud`
    attrs stay conditionally absent so the `hasattr(..., "_cloud")`
    assertions below (pinning the underlying attr's absence) still mean
    something.
    """
    mqtt_mock = MagicMock() if has_mqtt else None
    cloud_mock = MagicMock() if has_cloud else None
    kwargs = {}
    if has_mqtt:
        kwargs["_mqtt"] = mqtt_mock
    if has_cloud:
        kwargs["_cloud"] = cloud_mock
    coordinator = SimpleNamespace(
        async_config_entry_first_refresh=AsyncMock(
            side_effect=ConfigEntryNotReady("cloud blip")
        ),
        mqtt=mqtt_mock,
        cloud=cloud_mock,
        **kwargs,
    )
    return coordinator


def _run_setup_with_failing_coordinator(coordinator):
    """Drive async_setup_entry with the coordinator/WifiArchiveStore
    construction points patched out, so the test exercises only the
    first-refresh failure branch. Returns the hass used, for assertions."""
    from custom_components.dreame_a2_mower import async_setup_entry

    hass = _SetupFakeHass()
    entry = SimpleNamespace(entry_id="entry-1")

    wifi_store_instance = MagicMock()
    wifi_store_instance.load_index.return_value = {}

    with (
        patch(
            "custom_components.dreame_a2_mower.wifi_archive_store.WifiArchiveStore",
            return_value=wifi_store_instance,
        ),
        patch(
            "custom_components.dreame_a2_mower.coordinator.DreameA2MowerCoordinator",
            return_value=coordinator,
        ),
    ):
        with pytest.raises(ConfigEntryNotReady):
            asyncio.run(async_setup_entry(hass, entry))

    return hass


def test_first_refresh_not_ready_disconnects_both_transports():
    """TDD target: before the fix, __init__.py's async_setup_entry awaits
    async_config_entry_first_refresh() with no try/except, so a
    ConfigEntryNotReady propagates immediately and neither transport is
    disconnected — this must fail against the pre-fix code."""
    coordinator = _make_failing_coordinator(has_mqtt=True, has_cloud=True)

    _run_setup_with_failing_coordinator(coordinator)

    coordinator._mqtt.disconnect.assert_called_once()
    coordinator._cloud.disconnect.assert_called_once()


def test_first_refresh_not_ready_still_propagates():
    """The exception must still surface to HA after teardown (HA needs it
    to schedule the setup retry with backoff)."""
    coordinator = _make_failing_coordinator(has_mqtt=True, has_cloud=True)

    # _run_setup_with_failing_coordinator already asserts
    # pytest.raises(ConfigEntryNotReady) internally; a second explicit
    # assertion here documents the "still propagates" requirement directly
    # at the call site the reviewer named.
    from custom_components.dreame_a2_mower import async_setup_entry

    hass = _SetupFakeHass()
    entry = SimpleNamespace(entry_id="entry-1")
    wifi_store_instance = MagicMock()
    wifi_store_instance.load_index.return_value = {}

    with (
        patch(
            "custom_components.dreame_a2_mower.wifi_archive_store.WifiArchiveStore",
            return_value=wifi_store_instance,
        ),
        patch(
            "custom_components.dreame_a2_mower.coordinator.DreameA2MowerCoordinator",
            return_value=coordinator,
        ),
        pytest.raises(ConfigEntryNotReady, match="cloud blip"),
    ):
        asyncio.run(async_setup_entry(hass, entry))


def test_first_refresh_not_ready_guards_partial_transports():
    """A coordinator that only got as far as _init_mqtt (no _cloud attr
    yet) must not crash the teardown — mirrors the getattr-guard in
    async_unload_entry's transport teardown."""
    coordinator = _make_failing_coordinator(has_mqtt=True, has_cloud=False)

    _run_setup_with_failing_coordinator(coordinator)

    coordinator._mqtt.disconnect.assert_called_once()
    assert not hasattr(coordinator, "_cloud")


def test_first_refresh_not_ready_guards_no_transports_at_all():
    """A coordinator that failed before _init_cloud/_init_mqtt ran at all
    (neither attribute set) must not crash the teardown."""
    coordinator = _make_failing_coordinator(has_mqtt=False, has_cloud=False)

    # Must not raise anything other than the expected ConfigEntryNotReady.
    _run_setup_with_failing_coordinator(coordinator)
