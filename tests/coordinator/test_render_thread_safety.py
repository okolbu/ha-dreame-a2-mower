"""_schedule_render_base must hop to the event loop (HA 2026.6 raises if
async_create_task is called off-loop, which aborts the MQTT callback)."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator


def _coord():
    c = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    hass = MagicMock()
    c._scheduled = []
    hass.loop.call_soon_threadsafe = lambda cb, *a: c._scheduled.append(cb)
    c.hass = hass
    c._render_base = lambda: "coro"  # stub: returns a non-coroutine sentinel
    return c, hass


def test_schedule_render_base_does_not_call_async_create_task_directly():
    c, hass = _coord()
    c._schedule_render_base()
    # Off-loop async_create_task would raise in HA 2026.6 — must be deferred.
    hass.async_create_task.assert_not_called()
    assert len(c._scheduled) == 1


def test_schedule_render_base_creates_task_when_loop_callback_runs():
    c, hass = _coord()
    c._schedule_render_base()
    # Invoke the scheduled loop callback (simulating the event loop) — NOW the
    # task is created (on the loop, safely).
    c._scheduled[0]()
    hass.async_create_task.assert_called_once()


def test_schedule_render_base_no_hass_is_noop():
    c = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    c.hass = None
    # Must not raise.
    c._schedule_render_base()
