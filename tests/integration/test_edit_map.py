import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

from custom_components.dreame_a2_mower.coordinator._writes import _WritesMixin


def _make_coord(results=None):
    c = _WritesMixin()
    calls = []
    seq = iter(results) if results else None

    def _routed(op, extra=None, *, p=0):
        calls.append((op, extra, p))
        return None if (seq is not None and not next(seq)) else {"ok": True}

    c._cloud = SimpleNamespace(routed_action=_routed)
    c._chunked_write_lock = asyncio.Lock()
    c._refresh_cloud_state = AsyncMock()

    async def _exec(fn, *a, **k):
        return fn(*a, **k)
    c.hass = SimpleNamespace(async_add_executor_job=AsyncMock(side_effect=_exec))
    return c, calls


@pytest.mark.asyncio
async def test_edit_map_transaction_order_and_commit_p():
    c, calls = _make_coord()
    ok = await c.edit_map(1, [(219, {"region": 1, "name": "X"})])
    assert ok is True
    ops = [(op, p) for (op, _e, p) in calls]
    assert ops == [(200, 0), (204, 0), (219, 0), (201, 1)]
    assert calls[0][1] == {"idx": 1}        # select map
    assert calls[2][1] == {"region": 1, "name": "X"}
    c._refresh_cloud_state.assert_awaited()


@pytest.mark.asyncio
async def test_edit_map_always_commits_and_reports_failure(monkeypatch):
    # mutation (3rd call) fails -> overall False, but commit (o=201) still sent.
    c, calls = _make_coord(results=[True, True, False, True])
    ok = await c.edit_map(0, [(218, {"id": 101, "type": 0})])
    assert ok is False
    assert (201, 1) in [(op, p) for (op, _e, p) in calls]


@pytest.mark.asyncio
async def test_rename_and_delete_wrappers_build_mutations():
    c, calls = _make_coord()
    await c.rename_zone(2, 3, "Lawn")
    await c.delete_map_object(0, 102, 4)
    muts = [(op, e) for (op, e, _p) in calls]
    assert (219, {"region": 3, "name": "Lawn"}) in muts
    assert (218, {"id": 102, "type": 4}) in muts
