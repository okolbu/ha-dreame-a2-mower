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
# mqtt_is_fresh is a TRANSPORT check (todo8 #1): available while the broker
# link is up OR the cloud poll succeeds — NOT gated on heartbeat freshness.
# The device backs its radio off to a multi-minute/-hour cadence whenever it is
# not actively mowing (docked OR erroring on the lawn at full battery), so
# heartbeat silence must never flip the entity to unavailable.
# ---------------------------------------------------------------------------

class _FakeMqtt:
    """Stand-in for ``DreameA2MqttClient``.

    ``is_connected`` MUST be a ``@property`` here, matching the real class
    (``mqtt_client.py``) exactly — see R-4 / T3-1 / T7-1. A hand-rolled
    ``def is_connected(self)`` (a callable method) is the mock-mask that hid
    the production bug: ``coordinator/_core.py`` called
    ``mqtt.is_connected()`` (parens) against the real property, raising
    ``TypeError: 'bool' object is not callable`` that a bare ``except`` then
    swallowed — so ``mqtt_is_fresh`` silently degraded to ``cloud_is_fresh``
    forever. Against a hand-rolled *method* fake, the same call site is a
    normal, successful function call, so the bug never surfaced here. The
    permanent guard against this exact shape mismatch recurring is
    ``tests/audit/test_mock_shape_census.py``.
    """

    def __init__(self, connected: bool):
        self._c = connected

    @property
    def is_connected(self) -> bool:
        return self._c


def _coord(*, mqtt_connected=None, cloud_failures=0):
    """Build a bare coordinator exposing just the availability inputs."""
    coord = object.__new__(DreameA2MowerCoordinator)
    if mqtt_connected is not None:
        coord._mqtt = _FakeMqtt(mqtt_connected)
    coord._consecutive_cloud_failures = cloud_failures
    return coord


def test_mqtt_is_fresh_true_when_broker_connected():
    # Connected broker → available regardless of heartbeat silence.
    assert _coord(mqtt_connected=True, cloud_failures=99).mqtt_is_fresh is True


def test_mqtt_is_fresh_true_when_broker_down_but_cloud_ok():
    # Broker dropped but the cloud poll still succeeds → still available
    # (we can still receive state); avoids flapping on a paho reconnect blip.
    assert _coord(mqtt_connected=False, cloud_failures=0).mqtt_is_fresh is True


def test_mqtt_is_fresh_false_when_both_links_down():
    # Genuine total outage: broker disconnected AND cloud failing → unavailable.
    assert _coord(mqtt_connected=False, cloud_failures=5).mqtt_is_fresh is False


def test_mqtt_is_fresh_handles_missing_mqtt_client():
    # Before the MQTT client is wired (early setup), fall back to cloud freshness.
    assert _coord(mqtt_connected=None, cloud_failures=0).mqtt_is_fresh is True
    assert _coord(mqtt_connected=None, cloud_failures=5).mqtt_is_fresh is False


def test_mqtt_is_fresh_true_with_real_client_when_broker_connected():
    """Regression (R-4 / T3-1 / T7-1): use the REAL ``DreameA2MqttClient``,
    not a fake, so this proves the actual attribute shape.

    ``DreameA2MqttClient.is_connected`` is a ``@property``
    (``mqtt_client.py``). The bug was ``coordinator/_core.py`` calling it as
    a method (``mqtt.is_connected()``), which raises ``TypeError`` against
    the real property; the bare ``except Exception: pass`` swallowed that
    and fell through to ``cloud_is_fresh`` — so a connected broker was
    reported fresh ONLY because the cloud poll happened to also be fresh,
    never because the broker itself was live. With cloud failing (stale)
    but the broker genuinely connected, the pre-fix code returns False here;
    it must return True.
    """
    from custom_components.dreame_a2_mower.mqtt_client import DreameA2MqttClient

    coord = object.__new__(DreameA2MowerCoordinator)
    mqtt = DreameA2MqttClient()
    mqtt._connected = True  # broker has acked the connection
    coord._mqtt = mqtt
    coord._consecutive_cloud_failures = 99  # cloud link is stale/failing

    assert coord.mqtt_is_fresh is True


def test_mqtt_is_fresh_false_with_real_client_when_broker_and_cloud_down():
    """Same real-client proof, negative case: broker down AND cloud stale
    must still be a genuine unavailable."""
    from custom_components.dreame_a2_mower.mqtt_client import DreameA2MqttClient

    coord = object.__new__(DreameA2MowerCoordinator)
    mqtt = DreameA2MqttClient()
    mqtt._connected = False
    coord._mqtt = mqtt
    coord._consecutive_cloud_failures = 99

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


# ===========================================================================
# Entity-level tagging tests (Phase 1.1 application).
#
# These construct REAL entity classes against a coordinator whose freshness
# flags we toggle, and assert each entity goes unavailable when ITS source
# is stale. The base CoordinatorEntity.available check reads
# coordinator.last_update_success — a MagicMock coordinator returns a truthy
# value there by default, so the freshness gate is the deciding factor.
# ===========================================================================

from unittest.mock import MagicMock  # noqa: E402

from custom_components.dreame_a2_mower.cloud_state import (  # noqa: E402
    CloudState,
    ScheduleData,
    SettingsRoot,
)
from custom_components.dreame_a2_mower.mower.state import MowerState  # noqa: E402
from custom_components.dreame_a2_mower.mower.state_machine import (  # noqa: E402
    MowerStateMachine,
)


def _entity_coord(*, mqtt: bool = True, cloud: bool = True):
    """A MagicMock coordinator with explicit freshness flags.

    ``last_update_success`` stays a truthy MagicMock so the HA base
    ``available`` passes; only the per-source freshness flag decides.
    """
    coord = MagicMock()
    coord.mqtt_is_fresh = mqtt
    coord.cloud_is_fresh = cloud
    coord.entry.entry_id = "fake"
    return coord


# --- Group 1: an mqtt entity (DreameA2LawnMower) --------------------------

def test_mqtt_entity_lawn_mower_unavailable_when_mqtt_stale():
    from custom_components.dreame_a2_mower.lawn_mower import DreameA2LawnMower

    coord = _entity_coord(mqtt=True, cloud=True)
    coord.state_machine = MowerStateMachine()
    ent = DreameA2LawnMower(coord)
    assert ent._availability_source == "mqtt"
    assert ent.available is True

    coord.mqtt_is_fresh = False
    assert ent.available is False
    # A pure cloud outage must NOT take an mqtt entity down.
    coord.mqtt_is_fresh = True
    coord.cloud_is_fresh = False
    assert ent.available is True


# --- Group 2: a cloud entity (per-map settings number) --------------------

def _coord_with_settings(map_id=0, value=5, *, mqtt=True, cloud=True):
    coord = _entity_coord(mqtt=mqtt, cloud=cloud)
    coord.cloud_state = CloudState(
        cfg={},
        maps_by_id={map_id: MagicMock(name="map")},
        mow_paths_by_map_id={},
        settings=SettingsRoot(
            raw=[], by_map_id_canonical={map_id: {"mowingHeight": value}}
        ),
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
    return coord


def test_cloud_entity_per_map_number_unavailable_when_cloud_stale():
    from custom_components.dreame_a2_mower.number import (
        DreameA2PerMapMowingHeightNumber,
    )

    coord = _coord_with_settings(value=5, mqtt=True, cloud=True)
    ent = DreameA2PerMapMowingHeightNumber(coord, map_id=0)
    assert ent._availability_source == "cloud"
    # Value present + cloud fresh → available.
    assert ent.native_value == 5.0
    assert ent.available is True

    coord.cloud_is_fresh = False
    assert ent.available is False
    # An mqtt outage must NOT take a cloud entity down.
    coord.cloud_is_fresh = True
    coord.mqtt_is_fresh = False
    assert ent.available is True


# --- Group 3: a none entity (refresh button — no mixin, untouched) --------

def test_none_entity_button_unaffected_by_freshness():
    from custom_components.dreame_a2_mower.button import (
        DreameA2RefreshCloudStateButton,
    )

    coord = _entity_coord(mqtt=False, cloud=False)
    ent = DreameA2RefreshCloudStateButton(coord)
    # No freshness gating — the button never goes unavailable on link loss.
    assert not isinstance(ent, _FreshnessAvailableMixin)
    assert ent.available is True


def test_none_sourced_sensor_row_unaffected_by_freshness():
    """A DreameA2Sensor on a None-source descriptor row is NOT gated."""
    from custom_components.dreame_a2_mower.sensor_device import (
        SENSORS,
        DreameA2Sensor,
    )

    none_desc = next(d for d in SENSORS if d.key == "first_mowing_date")
    assert none_desc.availability_source is None
    coord = _entity_coord(mqtt=False, cloud=False)
    coord.data = MowerState()
    ent = DreameA2Sensor(coord, none_desc)
    assert ent._availability_source is None
    assert ent.available is True


# --- Group 4: DreameA2MowerGpsTracker (Pattern C bare-override edit) -------

def test_gps_tracker_unavailable_when_cloud_stale_even_with_coords():
    from custom_components.dreame_a2_mower.device_tracker import (
        DreameA2MowerGpsTracker,
    )

    coord = _entity_coord(mqtt=True, cloud=True)
    coord.data = MowerState(position_lat=59.9, position_lon=10.7)
    ent = DreameA2MowerGpsTracker(coord)
    # Coords present + cloud fresh → available.
    assert ent.latitude == 59.9 and ent.longitude == 10.7
    assert ent.available is True

    # Pattern C: the bare override ANDs in cloud_is_fresh directly, so a
    # cloud outage marks it unavailable EVEN THOUGH lat/lon are present.
    coord.cloud_is_fresh = False
    assert ent.available is False

    # No coords → unavailable regardless of freshness.
    coord.cloud_is_fresh = True
    coord.data = MowerState()
    ent2 = DreameA2MowerGpsTracker(coord)
    assert ent2.available is False


# --- Group 5: descriptor path — mqtt-row vs cloud-row vs none-row ---------

def _diag_coord(*, mqtt=True, cloud=True):
    coord = _entity_coord(mqtt=mqtt, cloud=cloud)
    coord.state_machine = MowerStateMachine()
    coord.data = MowerState()
    return coord


def test_diagnostic_sensor_rows_behave_per_availability_source():
    """A mqtt-row, a cloud-row, and a none-row of the SAME generic class
    (DreameA2DiagnosticSensor) gate differently — proving the descriptor
    bridge property resolves the per-row source via MRO."""
    from custom_components.dreame_a2_mower.sensor_device import (
        DIAGNOSTIC_SENSORS,
        DreameA2DiagnosticSensor,
    )

    mqtt_desc = next(d for d in DIAGNOSTIC_SENSORS if d.key == "battery_level")
    cloud_desc = next(d for d in DIAGNOSTIC_SENSORS if d.key == "cfg_version")
    none_desc = next(d for d in DIAGNOSTIC_SENSORS if d.key == "hardware_serial")

    assert mqtt_desc.availability_source == "mqtt"
    assert cloud_desc.availability_source == "cloud"
    assert none_desc.availability_source is None

    # MQTT row: down on mqtt-stale, up on cloud-stale.
    coord = _diag_coord(mqtt=False, cloud=True)
    assert DreameA2DiagnosticSensor(coord, mqtt_desc).available is False
    coord = _diag_coord(mqtt=True, cloud=False)
    assert DreameA2DiagnosticSensor(coord, mqtt_desc).available is True

    # Cloud row: down on cloud-stale, up on mqtt-stale.
    coord = _diag_coord(mqtt=True, cloud=False)
    assert DreameA2DiagnosticSensor(coord, cloud_desc).available is False
    coord = _diag_coord(mqtt=False, cloud=True)
    assert DreameA2DiagnosticSensor(coord, cloud_desc).available is True

    # None row: unaffected by either.
    coord = _diag_coord(mqtt=False, cloud=False)
    assert DreameA2DiagnosticSensor(coord, none_desc).available is True


def test_mqtt_connectivity_sensor_overrides_base_to_none():
    """The MQTT-connectivity link reporter subclasses _SnapshotEnumSensorBase
    (mqtt) but must stay visible — its source is overridden back to None."""
    from custom_components.dreame_a2_mower.sensor_device import (
        DreameA2MqttConnectivitySensor,
    )

    coord = _entity_coord(mqtt=False, cloud=False)
    coord.state_machine = MowerStateMachine()
    ent = DreameA2MqttConnectivitySensor(coord)
    assert ent._availability_source is None
    # Even with mqtt stale, the reporter itself stays available.
    assert ent.available is True
