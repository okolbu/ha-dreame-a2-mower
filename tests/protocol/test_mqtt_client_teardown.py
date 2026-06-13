"""P1.5 lifecycle: MQTT client teardown ordering + in-flight-callback guard.

Two defects fixed:
  1. ``_on_message`` (runs on the paho network thread) had no "stopping" guard,
     so an in-flight message during teardown still wrote the archive and
     dispatched into a coordinator being torn down (use-after-teardown).
  2. ``disconnect()`` called ``loop_stop()`` BEFORE ``disconnect()`` and never
     nulled paho's ``on_message``, so paho could still dispatch during teardown.

The fix: a ``_stopping`` flag checked at the very top of ``_on_message``, and a
``disconnect()`` that sets ``_stopping``, nulls ``on_message``, then
``disconnect()`` -> ``loop_stop()`` (the latter joins the net thread on
paho>=2.0). ``connect()`` re-arms ``_stopping=False`` so a reconnect works.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.mqtt_client import DreameA2MqttClient


class _RecordingPahoClient:
    """Records the ORDER of attribute-sets and method-calls during teardown.

    A plain ``MagicMock`` silently swallows ``on_message = None`` without
    recording it, so we use a real object whose ``__setattr__`` logs into a
    shared event list — that's how we prove ``on_message`` was nulled BEFORE
    ``loop_stop()`` rather than just that it ended up None.
    """

    def __init__(self) -> None:
        object.__setattr__(self, "events", [])
        object.__setattr__(self, "on_message", "sentinel")

    def __setattr__(self, name, value) -> None:
        self.events.append(("set", name, value))
        object.__setattr__(self, name, value)

    def disconnect(self) -> None:
        self.events.append(("call", "disconnect"))

    def loop_stop(self) -> None:
        self.events.append(("call", "loop_stop"))


def test_disconnect_nulls_on_message_before_loop_stop() -> None:
    client = DreameA2MqttClient()
    paho = _RecordingPahoClient()
    client._client = paho

    assert client._stopping is False
    client.disconnect()

    # _stopping flips True; client ref dropped; flags cleared.
    assert client._stopping is True
    assert client._client is None
    assert client.is_connected is False
    assert client._callback is None
    assert client._connected_callback is None

    events = paho.events

    def _index(predicate) -> int:
        for i, e in enumerate(events):
            if predicate(e):
                return i
        return 10**6

    idx_null = _index(lambda e: e == ("set", "on_message", None))
    idx_disconnect = _index(lambda e: e == ("call", "disconnect"))
    idx_loopstop = _index(lambda e: e == ("call", "loop_stop"))

    # All three happened.
    assert idx_null < 10**6, "on_message was never nulled"
    assert idx_disconnect < 10**6, "disconnect() was never called"
    assert idx_loopstop < 10**6, "loop_stop() was never called"
    # Ordering: on_message nulled AND disconnect() issued BEFORE loop_stop().
    assert idx_null < idx_loopstop, "on_message must be nulled before loop_stop()"
    assert idx_disconnect < idx_loopstop, "disconnect() must precede loop_stop()"


def test_disconnect_without_client_is_noop() -> None:
    client = DreameA2MqttClient()
    assert client._client is None
    client.disconnect()  # must not raise
    assert client._stopping is True
    assert client._client is None


def test_on_message_early_returns_when_stopping() -> None:
    """When _stopping is True, _on_message writes NO archive and dispatches NO callback."""
    client = DreameA2MqttClient()

    archive = MagicMock()
    callback = MagicMock()
    client.attach_archive(archive)
    client.register_callback(callback)
    client._stopping = True

    message = SimpleNamespace(
        topic="/status/x", payload=b'{"data": {"method": "m"}}'
    )
    # paho delivers `self` via userdata=self; the static callback signature is
    # (client, self, message).
    DreameA2MqttClient._on_message(object(), client, message)

    archive.write.assert_not_called()
    callback.assert_not_called()
    # The first-topics diagnostic must also not fire during teardown.
    assert client._first_topics == []


def test_on_message_dispatches_when_not_stopping() -> None:
    """Sanity: the guard does not break the normal (not-stopping) path."""
    client = DreameA2MqttClient()
    archive = MagicMock()
    callback = MagicMock()
    client.attach_archive(archive)
    client.register_callback(callback)
    assert client._stopping is False

    message = SimpleNamespace(
        topic="/status/x", payload=b'{"data": {"method": "m"}}'
    )
    DreameA2MqttClient._on_message(object(), client, message)

    archive.write.assert_called_once()
    callback.assert_called_once_with("/status/x", {"method": "m"})


def test_connect_rearms_stopping_flag(monkeypatch) -> None:
    """connect() must reset _stopping=False so a reconnect after disconnect works."""
    client = DreameA2MqttClient()
    client.disconnect()
    assert client._stopping is True

    # Stub the lazily-imported paho client so connect() doesn't need real paho.
    import sys
    import types

    fake_client_obj = MagicMock()
    fake_mqtt = types.ModuleType("paho.mqtt.client")
    fake_mqtt.CallbackAPIVersion = SimpleNamespace(VERSION1="v1")
    fake_mqtt.Client = MagicMock(return_value=fake_client_obj)
    monkeypatch.setitem(sys.modules, "paho", types.ModuleType("paho"))
    monkeypatch.setitem(sys.modules, "paho.mqtt", types.ModuleType("paho.mqtt"))
    monkeypatch.setitem(sys.modules, "paho.mqtt.client", fake_mqtt)

    client.connect("host", 8883, "u", "p", "cid")
    assert client._stopping is False
