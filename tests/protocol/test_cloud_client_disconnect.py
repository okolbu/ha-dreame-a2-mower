"""P1.5 lifecycle: cloud_client.disconnect() must JOIN the async API worker.

The ``_api_task`` worker is a real per-instance daemon thread. Before P1.5,
``disconnect()`` enqueued the stop sentinel ``[]`` but nulled ``self._thread``
without ever joining — so on every config-entry reload the worker thread (and
its ``requests.Session``) leaked. These tests spawn the REAL worker (no paho,
no network) and assert it is gone after ``disconnect()``.
"""
from __future__ import annotations

import time

from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient
from custom_components.dreame_a2_mower.cloud_client import _API_TASK_JOIN_TIMEOUT_S


def _make_client() -> DreameA2CloudClient:
    # Minimal ctor args (mirrors tests/protocol/test_cloud_client_* usage).
    return DreameA2CloudClient("user", "pass", "eu", "did-123")


def test_disconnect_joins_real_worker_thread() -> None:
    client = _make_client()

    calls: list[tuple] = []

    # Stub _api_call so the worker does no HTTP — just records the call and
    # returns a value the queued callback receives.
    def _fake_api_call(url, params=None, retry_count=2):
        calls.append((url, params, retry_count))
        return {"ok": True}

    client._api_call = _fake_api_call  # type: ignore[method-assign]

    results: list = []
    # Spawn the REAL daemon worker via the public-ish async path.
    client._api_call_async(results.append, "some/url", {"k": "v"}, 2)

    worker = client._thread
    assert worker is not None
    assert worker.is_alive(), "worker thread should be running after _api_call_async"

    # Let the queued work drain so we exercise the non-sentinel path too.
    deadline = time.monotonic() + 2.0
    while not results and time.monotonic() < deadline:
        time.sleep(0.01)
    assert results == [{"ok": True}]
    assert calls == [("some/url", {"k": "v"}, 2)]

    client.disconnect()

    assert client._thread is None, "_thread must be nulled AFTER the join"
    assert not worker.is_alive(), "worker thread must have exited after disconnect()"


def test_disconnect_sentinel_exits_idle_worker() -> None:
    """An IDLE worker blocked on queue.get() exits on the sentinel near-instantly."""
    client = _make_client()
    client._api_call = lambda *a, **k: None  # type: ignore[method-assign]

    # Start the worker but enqueue no real work — it blocks on queue.get().
    from threading import Thread

    client._thread = Thread(target=client._api_task, daemon=True)
    client._thread.start()
    worker = client._thread
    assert worker.is_alive()

    t0 = time.monotonic()
    client.disconnect()
    elapsed = time.monotonic() - t0

    assert client._thread is None
    assert not worker.is_alive()
    # Idle worker returns the sentinel instantly — nowhere near the 5s cap.
    assert elapsed < _API_TASK_JOIN_TIMEOUT_S


def test_disconnect_without_worker_is_a_noop() -> None:
    """disconnect() with no worker thread must not raise (guard for None)."""
    client = _make_client()
    assert client._thread is None
    client.disconnect()  # must not raise
    assert client._thread is None
