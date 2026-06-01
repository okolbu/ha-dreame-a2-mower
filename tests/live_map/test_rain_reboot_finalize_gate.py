"""FAILING repro (TDD red): a freshly-restored rain-paused session is
prematurely finalized on the seeded prev_task_state.

Incident (2026-05-31): a scheduled all-area MOW hit rain protection,
docked + charging. HA was REBOOTED. _restore_in_progress rehydrates the
session, calls state_machine.seed_in_session() (→ IN_SESSION), and seeds
self._prev_task_state = 0 ("running"). On the first finalize tick,
finalize.decide() sees prev ∈ {0,4} and the docked-charging-rain mower's
task_state (2 or None) and returns FINALIZE_INCOMPLETE — archiving +
deleting in_progress.json even though the mower is merely waiting out the
rain timer at the dock.

This file pins defect #3 (premature finalize on restore) and, by proxy,
defect #2 (rain context is in-memory only — _rain_delay_started_at is
lost on reboot, so coordinator.rain_delay_active reads False and there is
no signal to suppress the finalize).

The desired behaviour: a session freshly restored from disk that is
rain-paused at the dock must NOT be finalized merely because restore
seeded prev_task_state=0. finalize.decide() (or a coordinator-level guard
wrapping it) must veto the FINALIZE_INCOMPLETE on the seeded prev.

These tests assert the desired (currently-failing) behaviour. They are
EXPECTED TO FAIL until the restore+finalize path stops finalizing a
rain-paused restored session on the seeded prev_task_state.
"""
from __future__ import annotations

import pytest

from custom_components.dreame_a2_mower.live_map.finalize import (
    FinalizeAction,
    decide,
)
from custom_components.dreame_a2_mower.mower.state import MowerState

NOW = 1_700_000_000  # arbitrary baseline unix


# ---------------------------------------------------------------------------
# Baseline (PASSES today): documents the premature-finalize mechanism.
# These two are the diagnostic anchor — they show decide() finalizing on the
# seeded prev=0 for both docked task_state codes a rain-paused mower reports.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("docked_task_state", [2, None])
def test_decide_currently_finalizes_on_seeded_prev_zero(docked_task_state):
    """DIAGNOSTIC: with the restore-seeded prev_task_state=0 and a docked
    mower's task_state (2 = complete/at-dock, or None = idle), decide()
    returns FINALIZE_INCOMPLETE today. This is the mechanism of the bug."""
    state = MowerState(
        task_state_code=docked_task_state,
        pending_session_object_name=None,
    )
    action = decide(state, prev_task_state=0, now_unix=NOW)
    assert action == FinalizeAction.FINALIZE_INCOMPLETE, (
        f"docked task_state={docked_task_state!r}, seeded prev=0 → "
        f"got {action!r} (documents the premature-finalize trigger)"
    )


# ---------------------------------------------------------------------------
# Desired behaviour (FAILS today): a freshly-restored rain-paused session
# must NOT be finalized on the seeded prev_task_state alone.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("docked_task_state", [2, None])
def test_restored_rain_paused_session_is_not_prematurely_finalized(
    docked_task_state,
):
    """A session freshly restored from in_progress.json while the mower is
    rain-paused at the dock must NOT be finalized on the first tick.

    The seeded prev_task_state=0 is an artefact of restore (it represents
    "we re-entered IN_SESSION", not a genuine running→docked transition that
    just happened on the wire), so it must not, by itself, drive a
    FINALIZE_INCOMPLETE while the rain timer is active.

    decide() is a pure function; the desired contract is that the
    restore+finalize path supplies the rain/just-restored context and
    suppresses finalize. This test asserts the desired NON-finalize outcome
    and is RED until that guard exists.
    """
    # NOTE (harness constraint / defect #2): MowerState has NO field that
    # records "rain delay currently active" — only rain_protection_enabled
    # (a setting) and rain_protection_resume_hours. The live rain context
    # lives ONLY in the coordinator's in-memory _rain_delay_started_at, which
    # is lost on reboot. So decide(), a pure function of MowerState, cannot
    # today be handed the rain signal it would need to veto the finalize.
    # This test therefore asserts the desired outcome with the state a docked
    # rain-paused mower actually reports; making it pass requires either a
    # persisted/derived rain-or-just-restored signal reaching this gate, or a
    # coordinator-level guard around it.
    state = MowerState(
        task_state_code=docked_task_state,
        pending_session_object_name=None,
        rain_protection_enabled=True,
    )
    action = decide(state, prev_task_state=0, now_unix=NOW)
    assert action != FinalizeAction.FINALIZE_INCOMPLETE, (
        "A rain-paused session restored from disk must NOT be finalized on "
        f"the seeded prev_task_state=0 (docked task_state={docked_task_state!r}); "
        f"decide() returned {action!r}. The mower is waiting out the rain "
        "timer at the dock, not ending its session."
    )
