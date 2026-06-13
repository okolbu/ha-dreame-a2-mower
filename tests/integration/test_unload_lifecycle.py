"""P1.5 lifecycle: async_unload_entry must tear down BOTH transports.

Before P1.5, ``async_unload_entry`` only disconnected the MQTT client; the
cloud client's async API worker + ``requests.Session`` leaked on every reload.
The fix mirrors the mqtt teardown: ``await hass.async_add_executor_job(
cloud.disconnect)`` for ``coordinator._cloud``. Both run in the executor because
``disconnect()`` blocks (it joins the worker).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower import async_unload_entry
from custom_components.dreame_a2_mower.const import DOMAIN


class _FakeHass:
    """Minimal hass: records executor jobs and reports a successful unload."""

    def __init__(self, coordinator) -> None:
        self.data = {DOMAIN: {"entry-1": coordinator}}
        self.executor_jobs: list = []
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
        return True


def test_async_unload_disconnects_both_transports() -> None:
    mqtt = MagicMock()
    cloud = MagicMock()
    coordinator = SimpleNamespace(_mqtt=mqtt, _cloud=cloud, _novel_log_handler=None)
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
    coordinator = SimpleNamespace(_mqtt=mqtt, _novel_log_handler=None)
    hass = _FakeHass(coordinator)
    entry = SimpleNamespace(entry_id="entry-1")

    ok = asyncio.run(async_unload_entry(hass, entry))

    assert ok is True
    mqtt.disconnect.assert_called_once()
    # No cloud → only the mqtt teardown ran.
    assert hass.executor_jobs == [mqtt.disconnect]
