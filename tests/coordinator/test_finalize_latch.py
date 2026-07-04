"""P3e.4 — single finalize latch.

Two concurrent finalize triggers for the SAME session must result in
SessionArchive.archive running exactly once; the second entry is a no-op.

The latch (asyncio.Lock + _finalizing_start_ts on _CoreMixin.__init__)
serializes all finalize entries and de-dupes by session start_ts, subsuming
the old ad-hoc _non_mow_finalize_in_progress bool. This test drives the
terminal writer (_run_finalize_incomplete) directly with two concurrent tasks
so the latch is exercised at the natural yield point (the executor archive
write).
"""
from __future__ import annotations

import asyncio
import tempfile

import pytest
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.coordinator._session import _SessionMixin
from custom_components.dreame_a2_mower.archive.session import SessionArchive
from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.state import MowerState

T0 = 1_700_000_000


def _build_latch_coord():
    """Coordinator stub wired for the terminal-writer latch test."""
    c = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    c.live_map = LiveMapState()
    c.data = MowerState()
    c._active_map_id = 0
    c._rain_delay_started_at = None
    c._lifecycle_event = None
    c._notification_event = None

    # The latch this test exercises — normally seeded by _CoreMixin.__init__,
    # but this stub builds via __new__ so seed it manually.
    c._finalize_lock = asyncio.Lock()
    c._finalizing_start_ts = None

    c._run_finalize_incomplete = _SessionMixin._run_finalize_incomplete.__get__(c)
    c._merge_recorder_into_payload = (
        _SessionMixin._merge_recorder_into_payload.__get__(c)
    )
    c._post_archive_reset = _SessionMixin._post_archive_reset.__get__(c)
    c._resolve_finalize_map_id = _SessionMixin._resolve_finalize_map_id.__get__(c)
    c._clear_pending_op = MagicMock()
    c._inject_live_map_into_raw_dict = MagicMock()
    c._fire_mowing_ended = MagicMock()

    tmpdir = tempfile.mkdtemp()
    c.session_archive = SessionArchive(tmpdir)

    hass = MagicMock()

    async def _executor(fn, *args):
        return fn(*args)

    hass.async_add_executor_job.side_effect = _executor
    c.hass = hass

    def _set_data(new):
        c.data = new

    c.async_set_updated_data = _set_data

    c.cloud_state = MagicMock()
    c.cloud_state.maps_by_id = {}
    return c


async def test_concurrent_finalize_archives_once():
    """Two concurrent _run_finalize_incomplete for the same session →
    SessionArchive.archive runs once; the second is a no-op."""
    c = _build_latch_coord()
    now = T0 + 41

    c.live_map.begin_session(T0)
    c.live_map.last_task_op = 109
    c.live_map.append_point(t=T0 + 1, x_m=1.0, y_m=1.0, area_m2=0.0, heading_deg=0.0)

    archive_calls: list[tuple] = []
    real_archive = c.session_archive.archive

    def _counting_archive(*args, **kwargs):
        archive_calls.append(args)
        return real_archive(*args, **kwargs)

    c.session_archive.archive = _counting_archive

    # Force a true interleave: the executor for the FIRST archive write blocks
    # on a barrier until the second task has had a chance to run. Without the
    # latch, both tasks pass the live_map.is_active() check (the session is
    # still active because end_session() only runs AFTER the archive write),
    # so both reach the archive call → double archive. With the latch the
    # second task no-ops before archiving.
    first_archive_started = asyncio.Event()
    release_first_archive = asyncio.Event()

    base_executor = c.hass.async_add_executor_job.side_effect

    async def _barrier_executor(fn, *args):
        if fn is c.session_archive.archive and not first_archive_started.is_set():
            first_archive_started.set()
            await release_first_archive.wait()
        return await base_executor(fn, *args)

    c.hass.async_add_executor_job.side_effect = _barrier_executor

    task_a = asyncio.create_task(c._run_finalize_incomplete(now))
    # Let task_a advance to (and block inside) the first archive executor call.
    await first_archive_started.wait()
    task_b = asyncio.create_task(c._run_finalize_incomplete(now))
    # Give task_b a chance to run up to its own guard / latch.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    # Release task_a's archive write; both now run to completion.
    release_first_archive.set()
    await asyncio.gather(task_a, task_b)

    assert len(archive_calls) == 1, (
        f"SessionArchive.archive must run exactly ONCE; ran {len(archive_calls)} "
        f"time(s). Finalize latch failed to de-dupe the concurrent same-session "
        f"finalize."
    )
    assert not c.live_map.is_active(), "live_map must be inactive after finalize"
    assert len(c.session_archive.list_sessions()) == 1
