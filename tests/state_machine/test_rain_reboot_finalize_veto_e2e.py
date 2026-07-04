"""End-to-end wiring test: rain-paused session is not finalized via
_finalize_non_mow_immediate when rain_delay_active is True.

These tests pin the CHAIN:
  _rain_delay_started_at set  →  coordinator.rain_delay_active True
  →  _finalize_non_mow_immediate returns without calling _run_finalize_incomplete
  →  live_map session stays active.

The key property under test: `rain_delay_active` is NOT stubbed — the real
`_CoreMixin.rain_delay_active` property (from coordinator/_core.py) is
exercised via the `__new__`-constructed coordinator.  Because `DreameA2MowerCoordinator`
inherits `_CoreMixin`, the property resolves on `c` even though `c` was built
via `__new__`.  This means the wiring from `_rain_delay_started_at` through
`data.rain_protection_resume_hours` to the boolean gate in
`_finalize_non_mow_immediate` is genuinely exercised end-to-end.

The `__new__` harness mirrors `_build_finalize_coord` in
`tests/state_machine/test_to_point_session_end.py`, which is the established
pattern for driving `_finalize_non_mow_immediate` in isolation.

Cases:
  1. Active live_map session + rain_delay_started_at set + resume_hours=2
     (bounded window, still within it) → NOT finalized.
  2. Same but resume_hours=None (boot, pre-cloud-refresh) → NOT finalized.
     Pins the fail-safe-at-boot behaviour described in coordinator/_core.py:
     rain_delay_active returns True when resume_at is None.
  3. No rain (rain_delay_started_at=None) → DOES finalize (control case that
     proves the veto is the discriminator, not some other guard).
"""
from __future__ import annotations

import time

import pytest

# ---------------------------------------------------------------------------
# Baseline unix timestamp — arbitrary, well within the future rain window.
# ---------------------------------------------------------------------------

T0 = 1_748_800_000  # 2026-05-31 ~18:40 UTC, exact value doesn't matter


# ---------------------------------------------------------------------------
# Coordinator harness
# ---------------------------------------------------------------------------

def _build_rain_coord():
    """Minimal coordinator stub for rain-veto tests.

    Mirrors _build_finalize_coord from test_to_point_session_end.py,
    using __new__ to avoid HA imports while still exercising the real
    DreameA2MowerCoordinator property MRO (rain_delay_active lives in
    _CoreMixin which the coordinator inherits).
    """
    import asyncio
    import tempfile
    from unittest.mock import MagicMock

    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.archive.session import SessionArchive
    from custom_components.dreame_a2_mower.live_map.state import LiveMapState
    from custom_components.dreame_a2_mower.state import MowerState
    from custom_components.dreame_a2_mower.coordinator._session import _SessionMixin

    c = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    c.live_map = LiveMapState()
    c.data = MowerState()
    c._active_map_id = 0
    c._rain_delay_started_at = None          # default: no rain in progress
    c._lifecycle_event = None
    c._notification_event = None
    # Single finalize latch (P3e.4, owned by _CoreMixin.__init__).
    c._finalize_lock = asyncio.Lock()
    c._finalizing_start_ts = None

    # Bind the session-mixin methods needed for _finalize_non_mow_immediate.
    c._finalize_non_mow_immediate = _SessionMixin._finalize_non_mow_immediate.__get__(c)
    c._run_finalize_incomplete = _SessionMixin._run_finalize_incomplete.__get__(c)
    c._provisional_session_is_cloud_finalized = (
        _SessionMixin._provisional_session_is_cloud_finalized.__get__(c)
    )
    c._provisional_session_type = _SessionMixin._provisional_session_type.__get__(c)
    c._resolve_finalize_map_id = _SessionMixin._resolve_finalize_map_id.__get__(c)
    c._inject_live_map_into_raw_dict = MagicMock()  # suppress archive enrichment
    c._fire_mowing_ended = MagicMock()              # suppress event firing

    # SessionArchive backed by a real tmp dir.
    tmpdir = tempfile.mkdtemp()
    c.session_archive = SessionArchive(tmpdir)

    # Fake hass: executor jobs run inline.
    hass = MagicMock()

    async def _executor(fn, *args):
        return fn(*args)

    hass.async_add_executor_job.side_effect = _executor
    c.hass = hass

    def _set_data(new):
        c.data = new

    c.async_set_updated_data = _set_data

    # cloud_state needed by _resolve_finalize_map_id fallback.
    c.cloud_state = MagicMock()
    c.cloud_state.maps_by_id = {}

    return c


def _active_non_mow_session(c) -> None:
    """Seed `c.live_map` with a minimal active non-mow session."""
    from custom_components.dreame_a2_mower.live_map.state import LiveMapState

    c.live_map = LiveMapState()
    c.live_map.begin_session(T0)
    c.live_map.last_task_op = 109   # cruise-to-point: non-cloud-finalized
    c.live_map.append_point(
        t=T0 + 1, x_m=3.0, y_m=4.0, area_m2=0.0, heading_deg=0.0
    )
    assert c.live_map.is_active(), "precondition: session must be active"
    assert not c._provisional_session_is_cloud_finalized(), (
        "precondition: op=109 session must be non-cloud-finalized"
    )


# ---------------------------------------------------------------------------
# Case 1: resume_hours=2 (bounded window, still within it) → NOT finalized
# ---------------------------------------------------------------------------


async def test_rain_active_bounded_window_vetoes_finalize():
    """Rain in progress with a bounded resume window (resume_hours=2) vetoes
    _finalize_non_mow_immediate: live_map session stays active and no archive
    write is attempted.

    This pins the primary wiring: _rain_delay_started_at set + resume window
    not yet expired → rain_delay_active True → early return.

    Note: rain_delay_active uses time.time() to check whether the window has
    expired, so _rain_delay_started_at must be anchored near real wall-clock
    time (not T0, which is a past timestamp).  We use time.time() directly so
    the 2-hour window is always far from expired.
    """
    import time as _time

    from custom_components.dreame_a2_mower.state import MowerState

    c = _build_rain_coord()
    _active_non_mow_session(c)

    # Rain started 30 s ago in real wall-clock time; 2-hour window is far from
    # expired.  _finalize_non_mow_immediate's `now` arg is the coordinator's
    # logical "now" (unix) for archive metadata — it does not affect rain_delay_active.
    now = T0 + 30
    c._rain_delay_started_at = _time.time() - 30   # started 30 s before real now
    c.data = MowerState(rain_protection_resume_hours=2)

    # Confirm the real property evaluates True (not stubbed).
    assert c.rain_delay_active, (
        "precondition: rain_delay_active must be True with resume_hours=2 "
        "and delay started 30 s ago (window = 7200 s)"
    )

    # Track whether _run_finalize_incomplete is called.
    finalize_called = []
    original_run = c._run_finalize_incomplete

    async def _spy(n):
        finalize_called.append(n)
        await original_run(n)

    c._run_finalize_incomplete = _spy

    await c._finalize_non_mow_immediate(now, "task_state_edge")

    assert not finalize_called, (
        "_run_finalize_incomplete must NOT be called while rain_delay_active is True"
    )
    assert c.live_map.is_active(), (
        "live_map session must remain active when finalize is vetoed by rain guard"
    )


# ---------------------------------------------------------------------------
# Case 2: resume_hours=None (boot, pre-cloud-refresh) → NOT finalized
# ---------------------------------------------------------------------------


async def test_rain_active_resume_hours_none_vetoes_finalize():
    """rain_delay_active is True when _rain_delay_started_at is set but
    rain_protection_resume_hours is None (the mower is rain-paused and HA
    hasn't yet received the cloud refresh with the resume setting).

    In _CoreMixin.rain_delay_active:
        resume_at = rain_resume_at_unix  →  None (because hours is None/falsy)
        if resume_at is None: return True

    The veto must fire in this case too: we have durable evidence of rain
    (started_at persisted) but no bounded window yet.  If we allowed finalize
    here we'd archive the session prematurely during the boot-up cloud-refresh
    race window.
    """
    from custom_components.dreame_a2_mower.state import MowerState

    c = _build_rain_coord()
    _active_non_mow_session(c)

    now = T0 + 5
    c._rain_delay_started_at = now - 5   # rain started just before HA booted
    c.data = MowerState(rain_protection_resume_hours=None)  # pre-cloud-refresh

    # Confirm the real property evaluates True for resume_hours=None.
    assert c.rain_delay_active, (
        "precondition: rain_delay_active must be True when resume_hours=None "
        "(no bounded window yet — property returns True as fail-safe)"
    )

    finalize_called = []
    original_run = c._run_finalize_incomplete

    async def _spy(n):
        finalize_called.append(n)
        await original_run(n)

    c._run_finalize_incomplete = _spy

    await c._finalize_non_mow_immediate(now, "task_state_edge")

    assert not finalize_called, (
        "_run_finalize_incomplete must NOT be called when resume_hours=None "
        "(fail-safe: no bounded window means we cannot know the rain is over)"
    )
    assert c.live_map.is_active(), (
        "live_map session must remain active when finalize is vetoed by rain guard"
    )


# ---------------------------------------------------------------------------
# Case 3: no rain (_rain_delay_started_at=None) → DOES finalize (control)
# ---------------------------------------------------------------------------


async def test_no_rain_finalizes_normally():
    """Control case: when _rain_delay_started_at is None, rain_delay_active is
    False and _finalize_non_mow_immediate proceeds normally, ending the session.

    This proves that case 1 and 2 are discriminated by the rain veto and not
    by some other guard (session active, non-cloud-finalized, no concurrent
    finalize).
    """
    c = _build_rain_coord()
    _active_non_mow_session(c)

    now = T0 + 30
    # _rain_delay_started_at is None by default — no rain in progress.
    assert c._rain_delay_started_at is None
    assert not c.rain_delay_active, (
        "precondition: rain_delay_active must be False when "
        "_rain_delay_started_at is None"
    )

    await c._finalize_non_mow_immediate(now, "task_state_edge")

    assert not c.live_map.is_active(), (
        "live_map session must be finalized when there is no rain delay active"
    )
