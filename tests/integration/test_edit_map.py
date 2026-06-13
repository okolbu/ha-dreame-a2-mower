import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

from custom_components.dreame_a2_mower.cloud_client import WriteResult
from custom_components.dreame_a2_mower.coordinator._writes import _WritesMixin

_ACCEPTED = WriteResult(delivered=True, accepted=True, code=0)
_REJECTED = WriteResult(delivered=True, accepted=False, code=-3, msg="bad id")


def _make_coord(results=None):
    """Build a _WritesMixin with a fake routed_action.

    ``results`` (optional) is a per-leg sequence of truthy/falsy flags: a falsy
    entry makes that leg a delivered-but-REJECTED WriteResult (accepted=False),
    mirroring the real device replying r!=0; a truthy entry is accepted.
    """
    c = _WritesMixin()
    calls = []
    seq = iter(results) if results else None

    def _routed(op, extra=None, *, p=0):
        calls.append((op, extra, p))
        if seq is not None and not next(seq):
            return _REJECTED
        return _ACCEPTED

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
    # mutation (3rd call) is device-rejected (accepted=False) -> overall False,
    # but commit (o=201) is still sent so the device exits edit mode.
    c, calls = _make_coord(results=[True, True, False, True])
    ok = await c.edit_map(0, [(218, {"id": 101, "type": 0})])
    assert ok is False
    assert (201, 1) in [(op, p) for (op, _e, p) in calls]


@pytest.mark.asyncio
async def test_edit_map_rejected_leg_returns_falsy():
    """A delivered-but-rejected leg (out[0].r != 0) makes edit_map return False.

    This is the Task-A gate: routed_action returns a WriteResult whose truthiness
    is `accepted`, so a leg the device rejected (not just a transport drop) now
    correctly fails the transaction — the pre-fix code only caught None.
    """
    # Select (200) accepted, begin (204) accepted, mutation REJECTED, commit OK.
    c, calls = _make_coord(results=[True, True, False, True])
    ok = await c.edit_map(2, [(219, {"region": 9, "name": "Nope"})])
    assert ok is False
    # Every leg, including the rejected one, was still dispatched.
    ops = [op for (op, _e, _p) in calls]
    assert ops == [200, 204, 219, 201]


@pytest.mark.asyncio
async def test_edit_map_all_accepted_returns_true():
    """All legs accepted → edit_map returns True."""
    c, _calls = _make_coord()
    ok = await c.edit_map(1, [(219, {"region": 1, "name": "X"})])
    assert ok is True


@pytest.mark.asyncio
async def test_rename_and_delete_wrappers_build_mutations():
    c, calls = _make_coord()
    await c.rename_zone(2, 3, "Lawn")
    await c.delete_map_object(0, 102, 4)
    muts = [(op, e) for (op, e, _p) in calls]
    assert (219, {"region": 3, "name": "Lawn"}) in muts
    assert (218, {"id": 102, "type": 4}) in muts
