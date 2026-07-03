"""Lifecycle: async_unload_entry must tear down BOTH transports, in the
right order relative to platform unload, and cancel background tasks.

P1.5: ``async_unload_entry`` only disconnected the MQTT client; the cloud
client's async API worker + ``requests.Session`` leaked on every reload. The
fix mirrors the mqtt teardown: ``await hass.async_add_executor_job(
cloud.disconnect)`` for ``coordinator._cloud``. Both run in the executor
because ``disconnect()`` blocks (it joins the worker).

P2 Task 8 (T3-8/T3-13):
  - platforms must unload BEFORE transports disconnect, and a FAILED platform
    unload must leave the transports connected (T3-13) — the old order tore
    transports down unconditionally, stranding a retry-pending entry with a
    dead MQTT/cloud link.
  - background tasks (the dock-wait finalize task + any in-flight
    s2p2-notification resolver tasks) must be cancelled, and cancelled before
    the platform-unload gate (they're independent of entity teardown and
    must not survive a failed unload either).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower import async_unload_entry
from custom_components.dreame_a2_mower.const import DOMAIN


class _FakeHass:
    """Minimal hass: records executor jobs + call order, reports a
    configurable platform-unload result."""

    def __init__(self, coordinator, *, unload_platforms_ok: bool = True) -> None:
        self.data = {DOMAIN: {"entry-1": coordinator}}
        self.executor_jobs: list = []
        self.order: list[str] = []
        self._unload_platforms_ok = unload_platforms_ok
        self.config_entries = SimpleNamespace(
            async_unload_platforms=self._async_unload_platforms
        )
        # When DOMAIN's last entry is popped, async_unload_entry calls
        # async_unregister_services(hass) → hass.services.async_remove(...).
        self.services = SimpleNamespace(async_remove=lambda *a, **k: None)

    async def async_add_executor_job(self, func, *args):
        # Record the call, then actually invoke it (synchronously) so we also
        # prove the real disconnect() runs without raising.
        self.executor_jobs.append(func)
        return func(*args)

    async def _async_unload_platforms(self, entry, platforms):
        self.order.append("platforms")
        return self._unload_platforms_ok


def _ordering_coordinator() -> tuple[SimpleNamespace, _FakeHass]:
    """A coordinator + hass pair that records mqtt/cloud disconnect order."""
    mqtt = MagicMock()
    cloud = MagicMock()
    coordinator = SimpleNamespace(
        _mqtt=mqtt, _cloud=cloud, _novel_log_handler=None,
        # P3.2: __init__.py now reads coordinator.mqtt/.cloud/.novel_log_handler
        # (typed accessors on the real class) instead of getattr on the
        # private attrs. This SimpleNamespace stand-in isn't a real
        # coordinator instance, so it must carry both spellings.
        mqtt=mqtt, cloud=cloud, novel_log_handler=None,
        cancel_lifecycle_background_tasks=None,
    )
    hass = _FakeHass(coordinator)
    mqtt.disconnect.side_effect = lambda: hass.order.append("mqtt")
    cloud.disconnect.side_effect = lambda: hass.order.append("cloud")
    return coordinator, hass


def test_async_unload_disconnects_both_transports() -> None:
    mqtt = MagicMock()
    cloud = MagicMock()
    coordinator = SimpleNamespace(
        _mqtt=mqtt, _cloud=cloud, _novel_log_handler=None,
        mqtt=mqtt, cloud=cloud, novel_log_handler=None,
        cancel_lifecycle_background_tasks=None,
    )
    hass = _FakeHass(coordinator)
    entry = SimpleNamespace(entry_id="entry-1")

    ok = asyncio.run(async_unload_entry(hass, entry))

    assert ok is True
    mqtt.disconnect.assert_called_once()
    cloud.disconnect.assert_called_once()
    # Both teardowns went through the executor (blocking calls off the loop).
    assert mqtt.disconnect in hass.executor_jobs
    assert cloud.disconnect in hass.executor_jobs


def test_async_unload_guards_missing_cloud() -> None:
    """A coordinator without a _cloud attr must not blow up the unload."""
    mqtt = MagicMock()
    coordinator = SimpleNamespace(
        _mqtt=mqtt, _novel_log_handler=None,
        mqtt=mqtt, cloud=None, novel_log_handler=None,
        cancel_lifecycle_background_tasks=None,
    )
    hass = _FakeHass(coordinator)
    entry = SimpleNamespace(entry_id="entry-1")

    ok = asyncio.run(async_unload_entry(hass, entry))

    assert ok is True
    mqtt.disconnect.assert_called_once()
    # No cloud → only the mqtt teardown ran.
    assert hass.executor_jobs == [mqtt.disconnect]


# ---------------------------------------------------------------------------
# T3-13: unload order — platforms BEFORE transports; failure leaves them up.
# ---------------------------------------------------------------------------


def test_async_unload_platforms_before_transport_disconnect() -> None:
    """Platform unload must run, and succeed, BEFORE mqtt/cloud disconnect."""
    coordinator, hass = _ordering_coordinator()
    entry = SimpleNamespace(entry_id="entry-1")

    ok = asyncio.run(async_unload_entry(hass, entry))

    assert ok is True
    assert hass.order == ["platforms", "mqtt", "cloud"]


def test_async_unload_platform_failure_leaves_transports_connected() -> None:
    """T3-13: a failed platform unload must NOT tear down transports, and
    must leave the entry in hass.data (still "loaded") so HA can retry."""
    mqtt = MagicMock()
    cloud = MagicMock()
    coordinator = SimpleNamespace(
        _mqtt=mqtt, _cloud=cloud, _novel_log_handler=None,
        mqtt=mqtt, cloud=cloud, novel_log_handler=None,
        cancel_lifecycle_background_tasks=None,
    )
    hass = _FakeHass(coordinator, unload_platforms_ok=False)
    entry = SimpleNamespace(entry_id="entry-1")

    ok = asyncio.run(async_unload_entry(hass, entry))

    assert ok is False
    mqtt.disconnect.assert_not_called()
    cloud.disconnect.assert_not_called()
    # The entry was NOT popped — it stays "loaded" for HA's retry.
    assert hass.data[DOMAIN]["entry-1"] is coordinator


# ---------------------------------------------------------------------------
# T3-8: background-task cancellation.
# ---------------------------------------------------------------------------


def test_async_unload_cancels_background_tasks() -> None:
    """The coordinator's background-task canceller runs during unload."""
    mqtt = MagicMock()
    cloud = MagicMock()
    cancel_spy = MagicMock()
    coordinator = SimpleNamespace(
        _mqtt=mqtt,
        _cloud=cloud,
        _novel_log_handler=None,
        _cancel_lifecycle_background_tasks=cancel_spy,
        mqtt=mqtt,
        cloud=cloud,
        novel_log_handler=None,
        cancel_lifecycle_background_tasks=cancel_spy,
    )
    hass = _FakeHass(coordinator)
    entry = SimpleNamespace(entry_id="entry-1")

    ok = asyncio.run(async_unload_entry(hass, entry))

    assert ok is True
    cancel_spy.assert_called_once()


def test_async_unload_cancels_background_tasks_even_when_platform_unload_fails() -> None:
    """Background tasks (dock-wait, s2p2 resolvers) are independent of entity
    teardown — they must be cancelled regardless of the platform-unload
    outcome, unlike the transports (T3-13)."""
    mqtt = MagicMock()
    cloud = MagicMock()
    cancel_spy = MagicMock()
    coordinator = SimpleNamespace(
        _mqtt=mqtt,
        _cloud=cloud,
        _novel_log_handler=None,
        _cancel_lifecycle_background_tasks=cancel_spy,
        mqtt=mqtt,
        cloud=cloud,
        novel_log_handler=None,
        cancel_lifecycle_background_tasks=cancel_spy,
    )
    hass = _FakeHass(coordinator, unload_platforms_ok=False)
    entry = SimpleNamespace(entry_id="entry-1")

    ok = asyncio.run(async_unload_entry(hass, entry))

    assert ok is False
    cancel_spy.assert_called_once()
    mqtt.disconnect.assert_not_called()


def test_async_unload_guards_missing_background_canceller() -> None:
    """A coordinator built before this fix (no _cancel_lifecycle_background_tasks
    attribute) must not blow up the unload."""
    mqtt = MagicMock()
    coordinator = SimpleNamespace(
        _mqtt=mqtt, _cloud=None, _novel_log_handler=None,
        mqtt=mqtt, cloud=None, novel_log_handler=None,
        cancel_lifecycle_background_tasks=None,
    )
    hass = _FakeHass(coordinator)
    entry = SimpleNamespace(entry_id="entry-1")

    ok = asyncio.run(async_unload_entry(hass, entry))

    assert ok is True
    mqtt.disconnect.assert_called_once()


def test_cancel_lifecycle_background_tasks_cancels_dock_wait_and_resolvers() -> None:
    """Unit contract for _CoreMixin._cancel_lifecycle_background_tasks: it
    cancels an in-flight dock-wait task and every outstanding s2p2-resolver
    task, and tolerates already-done tasks (no exception, no re-cancel need)."""
    from custom_components.dreame_a2_mower.coordinator._core import _CoreMixin

    async def _run():
        dock_wait_task = asyncio.ensure_future(asyncio.sleep(100))
        resolver_task_a = asyncio.ensure_future(asyncio.sleep(100))
        resolver_task_b = asyncio.ensure_future(asyncio.sleep(0))
        await resolver_task_b  # let resolver_task_b actually finish
        assert resolver_task_b.done()

        coord = SimpleNamespace(
            _pending_finalize_task=dock_wait_task,
            _s2p2_resolver_tasks={resolver_task_a, resolver_task_b},
        )
        _CoreMixin._cancel_lifecycle_background_tasks(coord)

        # Give the event loop a tick to deliver the cancellation.
        for _ in range(3):
            await asyncio.sleep(0)

        assert dock_wait_task.cancelled()
        assert resolver_task_a.cancelled()
        # The already-done task was left alone (cancel() on it is a no-op;
        # asserting it stays "done" and was never touched is the contract).
        assert resolver_task_b.done() and not resolver_task_b.cancelled()

    asyncio.run(_run())
