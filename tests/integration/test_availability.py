"""Availability model (Phase 1.1): entities go unavailable when their
source is stale instead of freezing at the last value.

Two coordinator-level freshness signals back a per-source entity mixin:
- mqtt_is_fresh  — the device MQTT link (heartbeat) is live.
- cloud_is_fresh — the 2-min full-state cloud poll is succeeding.

See refactor-2026-06-13 plan §1.1 + the design decision: targeted hybrid,
moderate cloud gate (MQTT staleness at 90s; cloud unavailable after the
full-state poll fails ~2 consecutive cycles).
"""
from __future__ import annotations

from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator


def _bare_coord():
    """A coordinator shell with only the availability state initialised."""
    coord = object.__new__(DreameA2MowerCoordinator)
    coord._consecutive_cloud_failures = 0
    return coord


def test_cloud_is_fresh_true_initially():
    assert _bare_coord().cloud_is_fresh is True


def test_cloud_is_fresh_survives_a_single_failure():
    coord = _bare_coord()
    coord._note_cloud_fetch(ok=False)
    # One transient failure must NOT flip entities unavailable.
    assert coord.cloud_is_fresh is True


def test_cloud_is_fresh_false_after_two_consecutive_failures():
    coord = _bare_coord()
    coord._note_cloud_fetch(ok=False)
    coord._note_cloud_fetch(ok=False)
    assert coord.cloud_is_fresh is False


def test_cloud_success_resets_failure_streak():
    coord = _bare_coord()
    coord._note_cloud_fetch(ok=False)
    coord._note_cloud_fetch(ok=True)  # recovered
    coord._note_cloud_fetch(ok=False)
    # Streak reset by the success, so a lone later failure stays fresh.
    assert coord.cloud_is_fresh is True


# ---------------------------------------------------------------------------
# _refresh_cloud_state feeds the gate
# ---------------------------------------------------------------------------

class _FakeHass:
    """Minimal hass whose async_add_executor_job just calls the function."""

    async def async_add_executor_job(self, func, *args):
        return func(*args)


def _coord_with_cloud(fetch_result=None, raises=None):
    import types

    coord = object.__new__(DreameA2MowerCoordinator)
    coord._consecutive_cloud_failures = 0
    coord.hass = _FakeHass()

    def _fetch():
        if raises is not None:
            raise raises
        return fetch_result

    coord._cloud = types.SimpleNamespace(fetch_full_cloud_state=_fetch)
    return coord


def test_refresh_cloud_state_none_result_flips_after_threshold():
    import asyncio

    coord = _coord_with_cloud(fetch_result=None)
    asyncio.run(coord._refresh_cloud_state())
    assert coord.cloud_is_fresh is True  # one failure
    asyncio.run(coord._refresh_cloud_state())
    assert coord.cloud_is_fresh is False  # two consecutive failures


def test_refresh_cloud_state_exception_counts_as_failure():
    import asyncio

    coord = _coord_with_cloud(raises=RuntimeError("boom"))
    asyncio.run(coord._refresh_cloud_state())
    asyncio.run(coord._refresh_cloud_state())
    assert coord.cloud_is_fresh is False


# ---------------------------------------------------------------------------
# mqtt_is_fresh mirrors the state-machine connectivity signal
# ---------------------------------------------------------------------------

def _hb():
    """Minimal decoded-heartbeat stand-in (handle_heartbeat reads these)."""
    from types import SimpleNamespace

    return SimpleNamespace(emergency_stop=False, wifi_rssi_dbm=-50)


def _coord_with_sm():
    from custom_components.dreame_a2_mower.mower.state_machine import MowerStateMachine

    coord = object.__new__(DreameA2MowerCoordinator)
    coord.state_machine = MowerStateMachine()
    return coord


def test_mqtt_is_fresh_false_before_any_heartbeat():
    assert _coord_with_sm().mqtt_is_fresh is False


def test_mqtt_is_fresh_true_after_heartbeat():
    coord = _coord_with_sm()
    coord.state_machine.handle_heartbeat(hb=_hb(), now_unix=1000)
    assert coord.mqtt_is_fresh is True


def test_mqtt_is_fresh_false_when_heartbeat_stale():
    coord = _coord_with_sm()
    coord.state_machine.handle_heartbeat(hb=_hb(), now_unix=1000)
    # Drive the staleness check well past HB_STALENESS_S (90s).
    coord.state_machine.tick(now_unix=1000 + 200)
    assert coord.mqtt_is_fresh is False


# ---------------------------------------------------------------------------
# _FreshnessAvailableMixin gates per-source
# ---------------------------------------------------------------------------

from custom_components.dreame_a2_mower._availability import (  # noqa: E402
    _FreshnessAvailableMixin,
)


class _AvailBase:
    """Stand-in for CoordinatorEntity.available (always-True base)."""

    available = True


class _FreshSrc:
    """Fake coordinator exposing both freshness signals."""

    def __init__(self, *, mqtt: bool, cloud: bool):
        self._mqtt = mqtt
        self._cloud = cloud

    @property
    def mqtt_is_fresh(self):
        return self._mqtt

    @property
    def cloud_is_fresh(self):
        return self._cloud


def _ent(source, *, mqtt=True, cloud=True):
    class _Ent(_FreshnessAvailableMixin, _AvailBase):
        _availability_source = source

    e = _Ent()
    e.coordinator = _FreshSrc(mqtt=mqtt, cloud=cloud)
    return e


def test_untagged_entity_stays_available():
    assert _ent(None, mqtt=False, cloud=False).available is True


def test_mqtt_entity_unavailable_when_mqtt_stale():
    assert _ent("mqtt", mqtt=False, cloud=True).available is False
    assert _ent("mqtt", mqtt=True, cloud=True).available is True


def test_cloud_entity_unavailable_when_cloud_stale():
    assert _ent("cloud", mqtt=True, cloud=False).available is False
    assert _ent("cloud", mqtt=True, cloud=True).available is True


def test_mqtt_entity_independent_of_cloud():
    # An MQTT-sourced entity stays available during a pure cloud outage.
    assert _ent("mqtt", mqtt=True, cloud=False).available is True


def test_base_unavailable_overrides_source_fresh():
    class _DeadBase:
        available = False

    class _Ent(_FreshnessAvailableMixin, _DeadBase):
        _availability_source = "mqtt"

    e = _Ent()
    e.coordinator = _FreshSrc(mqtt=True, cloud=True)
    assert e.available is False
