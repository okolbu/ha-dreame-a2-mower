"""T7-20 (P3 Task 1): setup → unload → re-setup lifecycle tests.

Previously impossible against the bare HA stub (T7-20: ``async_setup_entry``
had ZERO tests; timer unsubscription was structurally unassertable because
``async_track_time_interval`` was a shared no-op lambda). These tests drive
the REAL ``async_setup_entry`` / ``async_unload_entry`` from
``custom_components/dreame_a2_mower/__init__.py``, with the REAL coordinator
``__init__`` + ``_async_update_data`` first-boot block (timer registration,
transport init order, ``entry.async_on_unload`` wiring), mocking ONLY:

- the two transports at the CLIENT boundary (fake ``DreameA2CloudClient`` /
  ``DreameA2MqttClient`` classes patched into ``coordinator._core`` — the
  exact seam production uses),
- the cloud-data refreshers on a test subclass (no-op bodies; their internals
  are covered by their own suites — here they'd need a full fake cloud API),
- ``async_track_time_interval`` in ``coordinator._core`` with a recorder that
  returns a DISTINCT unsubscribe per timer (the cancel-identity observable).

The three previously-impossible T7-20 assertions:
1. per-timer cancel identity — every scheduled interval timer's OWN
   unsubscribe runs exactly once on unload;
2. reload idempotency — setup→unload→setup yields a fresh coordinator,
   re-forwards platforms, keeps services registered, and does not
   accumulate update-listeners or leave first-generation timers alive;
3. no thread leak on reload — every transport client ever constructed is
   disconnected except the live generation (the client owns its worker
   thread, so an undisconnected client IS the leaked thread).
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components import dreame_a2_mower as integration
from custom_components.dreame_a2_mower.const import DOMAIN, PLATFORMS
from custom_components.dreame_a2_mower.coordinator import (
    DreameA2MowerCoordinator,
)
from custom_components.dreame_a2_mower.coordinator import _core as _core_mod
from custom_components.dreame_a2_mower.domain import boot as _boot_mod

from tests.factories import make_entry, make_hass


# ---------------------------------------------------------------------------
# Client-boundary fakes (transports)
# ---------------------------------------------------------------------------


class _FakeCloudClient:
    """Stands in for DreameA2CloudClient at the _init_cloud seam.

    Owns the "worker thread" in production — so connected-vs-disconnected on
    these instances is the thread-leak observable.
    """

    instances: list["_FakeCloudClient"] = []

    device_id = "did-1"
    model = "dreame.mower.g2408"
    serial_number = "G2408000TESTSN0000"
    _did = "did-1"
    _uid = "uid-1"
    _model = "dreame.mower.g2408"

    def __init__(self, *, username, password, country) -> None:
        self.username = username
        self.password = password
        self.country = country
        self.connected = True
        self.disconnect_calls = 0
        _FakeCloudClient.instances.append(self)

    def login(self) -> bool:
        return True

    def select_first_g2408(self) -> None:
        pass

    def get_device_info(self) -> None:
        pass

    def mqtt_host_port(self) -> tuple[str, int]:
        return ("mqtt.example.com", 8883)

    def mqtt_credentials(self) -> tuple[str, str]:
        return ("uid-1", "token-1")

    def mqtt_client_id(self) -> str:
        return "client-1"

    def mqtt_topic(self) -> str:
        return "/status/did-1/uid-1/dreame.mower.g2408/eu/"

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False


class _FakeMqttClient:
    """Stands in for DreameA2MqttClient at the _init_mqtt seam."""

    instances: list["_FakeMqttClient"] = []

    def __init__(self) -> None:
        self.connected = False
        self.disconnect_calls = 0
        self.subscribed_topic = None
        self._on_first_message = None
        _FakeMqttClient.instances.append(self)

    @property
    def is_connected(self) -> bool:
        return self.connected

    def register_callback(self, cb) -> None:
        self.message_cb = cb

    def register_connected_callback(self, cb) -> None:
        self.connected_cb = cb

    def register_auth_error_callback(self, cb) -> None:
        self.auth_error_cb = cb

    def connect(self, **kwargs) -> None:
        self.connect_kwargs = kwargs
        self.connected = True

    def subscribe(self, topic) -> None:
        self.subscribed_topic = topic

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False


# ---------------------------------------------------------------------------
# Timer recorder (cancel-identity observable)
# ---------------------------------------------------------------------------


class _TimerRegistry:
    """Recording replacement for _core.async_track_time_interval: each call
    returns a DISTINCT unsubscribe that counts its own invocations."""

    def __init__(self) -> None:
        self.timers: list[SimpleNamespace] = []

    def track(self, hass, action, interval: timedelta):
        record = SimpleNamespace(
            action=action, interval=interval, cancel_calls=0
        )

        def _unsub() -> None:
            record.cancel_calls += 1

        record.unsub = _unsub
        self.timers.append(record)
        return _unsub


# ---------------------------------------------------------------------------
# Coordinator test subclass: cloud-data refreshers no-op'd
# ---------------------------------------------------------------------------


class _LifecycleCoordinator(DreameA2MowerCoordinator):
    """REAL __init__ + REAL _async_update_data wiring; only the cloud-data
    refresher BODIES are stubbed (each is one network round-trip against the
    fake cloud API this test deliberately doesn't build — their behaviour is
    pinned by their own suites). Timer registration, transport init, restore,
    archive-index loads, and entry.async_on_unload wiring all run for real.
    """

    async def _refresh_cloud_state(self) -> None:
        # First-refresh contract: cloud_state must land or setup raises
        # ConfigEntryNotReady (see _refresh_cloud_state_or_raise).
        self.cloud_state = MagicMock(maps_by_id={})

    async def _establish_notification_baseline(self) -> None:
        pass

    async def _refresh_gps(self) -> None:
        pass

    async def _refresh_aiobs(self) -> None:
        pass

    async def _refresh_remote(self) -> None:
        pass

    async def _refresh_messages(self) -> None:
        pass

    async def _refresh_oss_gallery(self, max_pages: int | None = None) -> None:
        pass

    async def _refresh_dev(self) -> None:
        pass

    async def _refresh_net(self) -> None:
        pass

    async def _refresh_dock(self) -> None:
        pass

    async def refresh_wifi_archive(self) -> None:
        pass

    async def _render_base(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@pytest.fixture()
def lifecycle(monkeypatch, tmp_path):
    """Patched-seam environment + drive helpers for setup/unload cycles."""
    _FakeCloudClient.instances = []
    _FakeMqttClient.instances = []
    timers = _TimerRegistry()

    monkeypatch.setattr(_core_mod, "DreameA2CloudClient", _FakeCloudClient)
    monkeypatch.setattr(_core_mod, "DreameA2MqttClient", _FakeMqttClient)
    # P3.9e: the first-refresh timer registration moved to domain/boot.py, so
    # the async_track_time_interval seam is patched there now (the transport
    # clients stay on _core, exercised by _init_cloud/_init_mqtt).
    monkeypatch.setattr(_boot_mod, "async_track_time_interval", timers.track)
    # async_setup_entry resolves the coordinator class at call time via
    # `from .coordinator import DreameA2MowerCoordinator` — patch the package
    # attribute so the real setup path constructs the lifecycle subclass.
    monkeypatch.setattr(
        "custom_components.dreame_a2_mower.coordinator.DreameA2MowerCoordinator",
        _LifecycleCoordinator,
    )

    hass = make_hass(tmp_path)
    entry = make_entry()

    async def setup() -> bool:
        return await integration.async_setup_entry(hass, entry)

    async def unload() -> bool:
        ok = await integration.async_unload_entry(hass, entry)
        if ok:
            # Mirror real HA: the config-entry manager runs the entry's
            # on_unload callbacks (timer unsubs, update-listener removers)
            # after the component unload succeeds.
            entry.run_on_unload()
        return ok

    return SimpleNamespace(
        hass=hass, entry=entry, timers=timers, setup=setup, unload=unload
    )


# ---------------------------------------------------------------------------
# 1. Per-timer cancel identity
# ---------------------------------------------------------------------------


async def test_unload_cancels_each_timer_exactly_once(lifecycle):
    assert await lifecycle.setup() is True

    created = lifecycle.timers.timers
    # The first-boot block schedules the full refresher/persist/tick set —
    # don't pin the exact roster (that's _core's business), but it must be
    # a real population and none may be cancelled while the entry is loaded.
    assert len(created) >= 10
    assert all(t.cancel_calls == 0 for t in created)

    assert await lifecycle.unload() is True

    # CANCEL IDENTITY: every timer's OWN unsubscribe ran exactly once —
    # not "some cancel ran N times", and no timer double-cancelled.
    uncancelled = [t.interval for t in created if t.cancel_calls == 0]
    assert not uncancelled, f"timers left running after unload: {uncancelled}"
    double = [t.interval for t in created if t.cancel_calls > 1]
    assert not double, f"timers cancelled more than once: {double}"


async def test_failed_platform_unload_keeps_timers_and_transports(lifecycle):
    """T3-13 contract at the lifecycle level: when platform unload fails, HA
    keeps the entry loaded and does NOT run on_unload callbacks — transports
    must stay connected and timers must keep running."""
    assert await lifecycle.setup() is True
    lifecycle.hass.config_entries.unload_result = False

    assert await lifecycle.unload() is False

    assert all(t.cancel_calls == 0 for t in lifecycle.timers.timers)
    assert _FakeMqttClient.instances[-1].connected is True
    assert _FakeCloudClient.instances[-1].connected is True
    # Entry still registered so the retry can find the coordinator.
    assert lifecycle.entry.entry_id in lifecycle.hass.data[DOMAIN]


# ---------------------------------------------------------------------------
# 2. Reload idempotency
# ---------------------------------------------------------------------------


async def test_reload_is_idempotent(lifecycle):
    assert await lifecycle.setup() is True
    coord_1 = lifecycle.hass.data[DOMAIN][lifecycle.entry.entry_id]
    gen_1 = list(lifecycle.timers.timers)
    assert isinstance(coord_1, DreameA2MowerCoordinator)
    assert len(lifecycle.entry.update_listeners) == 1

    assert await lifecycle.unload() is True
    assert lifecycle.entry.entry_id not in lifecycle.hass.data.get(DOMAIN, {})
    # Options-update listener removed with the entry (registered via
    # async_on_unload(add_update_listener(...))).
    assert lifecycle.entry.update_listeners == []

    assert await lifecycle.setup() is True
    coord_2 = lifecycle.hass.data[DOMAIN][lifecycle.entry.entry_id]

    # Fresh coordinator, not the torn-down one.
    assert coord_2 is not coord_1
    # Platforms re-forwarded on every setup (same roster).
    forwards = lifecycle.hass.config_entries.forward_calls
    assert [platforms for _e, platforms in forwards] == [
        tuple(PLATFORMS),
        tuple(PLATFORMS),
    ]
    # Services survive the cycle: unregistered when the last entry unloads,
    # re-registered by the next setup.
    assert lifecycle.hass.services.has_service(DOMAIN, "mow_zone")
    # No listener accumulation across reloads.
    assert len(lifecycle.entry.update_listeners) == 1
    # First-generation timers are all dead; second generation all alive.
    gen_2 = [t for t in lifecycle.timers.timers if t not in gen_1]
    assert gen_2, "re-setup must schedule a fresh timer generation"
    assert all(t.cancel_calls == 1 for t in gen_1)
    assert all(t.cancel_calls == 0 for t in gen_2)


# ---------------------------------------------------------------------------
# 3. No thread leak on reload
# ---------------------------------------------------------------------------


async def test_setup_warms_archive_indexes_and_records_timing(lifecycle):
    """Setup must warm the photo/video archive indexes off the loop BEFORE
    platforms are forwarded (so entity count value_fns don't do a blocking
    disk read on the loop), and record a per-step boot-timing breakdown."""
    assert await lifecycle.setup() is True
    coord = lifecycle.hass.data[DOMAIN][lifecycle.entry.entry_id]

    # Both archive indexes were loaded during setup (idempotent guard flipped).
    assert coord._photo_archive._index_loaded is True
    assert coord._video_archive._index_loaded is True

    # Boot-timing breakdown was populated (the diagnostic surface used to
    # attribute a slow setup to the right step).
    assert coord._boot_timings  # non-empty
    assert {"init_cloud", "init_mqtt", "cloud_state"} <= set(coord._boot_timings)


async def test_reload_leaks_no_transport_threads(lifecycle):
    """The cloud client owns a requests.Session + API worker thread and the
    MQTT client owns the paho network thread. A client instance that never
    got disconnect() IS a leaked thread (P1.5 regression class). After a
    full unload → re-setup cycle, every historical instance must be
    disconnected and only the live generation connected."""
    assert await lifecycle.setup() is True
    assert await lifecycle.unload() is True
    assert await lifecycle.setup() is True

    assert [c.disconnect_calls for c in _FakeCloudClient.instances] == [1, 0]
    assert [m.disconnect_calls for m in _FakeMqttClient.instances] == [1, 0]
    assert [c.connected for c in _FakeCloudClient.instances] == [False, True]
    assert [m.connected for m in _FakeMqttClient.instances] == [False, True]

    # And the second unload tears the second generation down too (no
    # one-shot fluke): every instance ever constructed ends disconnected.
    assert await lifecycle.unload() is True
    assert all(not c.connected for c in _FakeCloudClient.instances)
    assert all(not m.connected for m in _FakeMqttClient.instances)
