"""T3-9: MQTT rc=5 (auth-rejected) recovery wiring.

``mqtt_client.py`` has carried ``register_auth_error_callback`` /
``update_credentials`` since 2026-05-x but nothing ever called them — a
broker reconnect after the cloud session token rotated would loop on rc=5
forever with no self-heal short of an HA reload (T3-9 in
track-3-correctness.md). These tests pin the fix: ``_init_mqtt`` registers a
callback that re-logins the cloud client and refreshes the MQTT client's
credentials, with a cooldown/in-flight guard against a tight relogin loop.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from custom_components.dreame_a2_mower.coordinator import _core as _core_mod

from tests.factories import make_coordinator


def _make_coord(monkeypatch, *, fake_mqtt_cls=None):
    """A REAL coordinator (P3 Task 1: factory-built through the real
    __init__, which owns the rc=5 guard state ``_rc5_relogin_in_progress`` /
    ``_rc5_last_attempt_unix``). The cloud client is a MagicMock at the
    client boundary; ``_mqtt_host``/``_mqtt_port`` are seeded exactly as
    ``_init_cloud`` would set them. The factory's hass runs executor jobs
    inline (swappable ``.side_effect``) and hops ``call_soon_threadsafe``
    synchronously (the paho-thread → loop hop)."""
    cloud = MagicMock()
    cloud.mqtt_credentials.return_value = ("uid-1", "token-1")
    cloud.mqtt_client_id.return_value = "client-1"
    cloud.mqtt_topic.return_value = "/status/did/uid/model/eu/"
    cloud._did = "did-1"
    cloud._uid = "uid-1"
    cloud._model = "dreame.mower.g2408"

    coord = make_coordinator(
        cloud=cloud,
        _mqtt_host="mqtt.example.com",
        _mqtt_port=8883,
        _on_mqtt_message=MagicMock(),
    )

    if fake_mqtt_cls is not None:
        monkeypatch.setattr(_core_mod, "DreameA2MqttClient", fake_mqtt_cls)
    return coord


class _FakeMqttClient:
    """Records the callbacks _init_mqtt registers; connect()/subscribe() are
    no-ops so the real paho import is never touched."""

    instances: list["_FakeMqttClient"] = []

    def __init__(self) -> None:
        self.auth_error_cb = None
        self.connected_cb = None
        self.message_cb = None
        self.connect_kwargs = None
        self.subscribed_topic = None
        self.update_credentials_calls: list[tuple] = []
        _FakeMqttClient.instances.append(self)

    def register_callback(self, cb):
        self.message_cb = cb

    def register_connected_callback(self, cb):
        self.connected_cb = cb

    def register_auth_error_callback(self, cb):
        self.auth_error_cb = cb

    def connect(self, **kwargs):
        self.connect_kwargs = kwargs

    def subscribe(self, topic):
        self.subscribed_topic = topic

    def update_credentials(self, username, password):
        self.update_credentials_calls.append((username, password))


def test_init_mqtt_registers_auth_error_callback(monkeypatch):
    """T3-9: _init_mqtt must wire an auth-error callback — previously nothing
    called register_auth_error_callback at all."""
    _FakeMqttClient.instances.clear()
    coord = _make_coord(monkeypatch, fake_mqtt_cls=_FakeMqttClient)

    coord._init_mqtt()

    fake = _FakeMqttClient.instances[-1]
    assert fake.auth_error_cb is not None


def test_rc5_triggers_relogin_and_refreshed_credentials(monkeypatch):
    """Firing the registered auth-error callback (simulating rc=5) re-logins
    the cloud client (via the executor — it's a blocking requests call) and
    pushes the refreshed credentials into the MQTT client."""
    _FakeMqttClient.instances.clear()
    coord = _make_coord(monkeypatch, fake_mqtt_cls=_FakeMqttClient)
    coord._init_mqtt()
    fake_mqtt = _FakeMqttClient.instances[-1]
    coord._mqtt = fake_mqtt

    coord._cloud.login.return_value = True
    coord._cloud.mqtt_credentials.return_value = ("uid-1", "refreshed-token")

    async def _run():
        # Simulate paho's on_disconnect(rc=5) invoking the registered callback.
        fake_mqtt.auth_error_cb()
        # _handle_mqtt_auth_error schedules _async_recover_mqtt_auth via
        # hass.async_create_task; let it run to completion.
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(_run())

    coord._cloud.login.assert_called_once()
    assert fake_mqtt.update_credentials_calls == [("uid-1", "refreshed-token")]
    # The in-flight guard clears after completion so a LATER genuine rc=5
    # (past the cooldown) can trigger another recovery.
    assert coord._rc5_relogin_in_progress is False


def test_rc5_does_not_loop_tightly_within_cooldown(monkeypatch):
    """A second rc=5 signal arriving before _RC5_RELOGIN_COOLDOWN_S elapses
    must NOT trigger a second cloud login (the tight-loop guard)."""
    _FakeMqttClient.instances.clear()
    coord = _make_coord(monkeypatch, fake_mqtt_cls=_FakeMqttClient)
    coord._init_mqtt()
    fake_mqtt = _FakeMqttClient.instances[-1]
    coord._mqtt = fake_mqtt
    coord._cloud.login.return_value = True

    async def _run():
        fake_mqtt.auth_error_cb()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        # Immediately signal rc=5 again — well within the cooldown window.
        fake_mqtt.auth_error_cb()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(_run())

    coord._cloud.login.assert_called_once()


def test_rc5_ignores_reentrant_signal_while_relogin_in_flight(monkeypatch):
    """A second rc=5 arriving WHILE a relogin is still executing (not yet
    resolved) must not spawn a second recovery task."""
    coord = _make_coord(monkeypatch)
    coord._mqtt = MagicMock()
    coord._cloud.login = MagicMock(side_effect=lambda: True)

    # Make async_add_executor_job actually take a moment, so the in-progress
    # flag is observably True while it's pending.
    async def _slow_exec(fn, *args):
        await asyncio.sleep(0.05)
        return fn(*args)

    coord.hass.async_add_executor_job = AsyncMock(side_effect=_slow_exec)

    async def _run():
        coord._handle_mqtt_auth_error()
        await asyncio.sleep(0)  # let _async_recover_mqtt_auth start
        assert coord._rc5_relogin_in_progress is True
        # Re-entrant rc=5 while the first recovery is still in flight.
        coord._handle_mqtt_auth_error()
        await asyncio.sleep(0.1)

    asyncio.run(_run())

    coord._cloud.login.assert_called_once()


def test_rc5_cooldown_escalates_on_consecutive_failures(monkeypatch):
    """P2-inherit: consecutive relogin failures escalate the cooldown so a
    broker that keeps rejecting fresh creds is retried less aggressively."""
    coord = _make_coord(monkeypatch)
    coord._mqtt = MagicMock()
    coord._cloud.login.return_value = False  # keeps failing

    fake_now = [1000.0]
    monkeypatch.setattr(_core_mod.time, "time", lambda: fake_now[0])

    async def _fire():
        coord._handle_mqtt_auth_error()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    async def _run():
        # 1st rc=5 → attempt; login fails → failures=1.
        await _fire()
        assert coord._cloud.login.call_count == 1
        assert coord._rc5_consecutive_failures == 1
        # After 1 failure the cooldown is base*2 = 60s. An rc=5 at +31s (past
        # the base 30 but within the escalated 60) must be SKIPPED — the old
        # fixed-30s cooldown would have retried here.
        fake_now[0] += 31
        await _fire()
        assert coord._cloud.login.call_count == 1
        # Past the escalated 60s window → attempt again; fails → failures=2.
        fake_now[0] += 30  # now +61 from the first attempt
        await _fire()
        assert coord._cloud.login.call_count == 2
        assert coord._rc5_consecutive_failures == 2

    asyncio.run(_run())


def test_rc5_success_resets_escalation(monkeypatch):
    """P2-inherit: a successful re-login resets the failure counter so the next
    rc=5 gets the base cooldown again."""
    coord = _make_coord(monkeypatch)
    coord._mqtt = MagicMock()

    fake_now = [1000.0]
    monkeypatch.setattr(_core_mod.time, "time", lambda: fake_now[0])

    async def _fire():
        coord._handle_mqtt_auth_error()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    async def _run():
        coord._cloud.login.return_value = False
        await _fire()
        assert coord._rc5_consecutive_failures == 1
        # Advance well past the escalated window and succeed.
        fake_now[0] += 1000
        coord._cloud.login.return_value = True
        coord._cloud.mqtt_credentials.return_value = ("uid-1", "fresh")
        await _fire()
        assert coord._rc5_consecutive_failures == 0

    asyncio.run(_run())


def test_rc5_recovery_failure_logs_and_does_not_update_credentials(monkeypatch):
    """A failed cloud re-login must not push stale/None credentials into the
    MQTT client — the next genuine rc=5 (after cooldown) retries."""
    coord = _make_coord(monkeypatch)
    mqtt = MagicMock()
    coord._mqtt = mqtt
    coord._cloud.login.return_value = False

    async def _run():
        coord._handle_mqtt_auth_error()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(_run())

    coord._cloud.login.assert_called_once()
    mqtt.update_credentials.assert_not_called()
    assert coord._rc5_relogin_in_progress is False
