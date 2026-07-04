"""Command-time session-start: activity at the op echo, for ALL task types.

Location is now driven solely by s2p1 (dock cluster {6,13,15,16} → AT_DOCK;
leaving → ON_LAWN). The s2p50 echo no longer sets location; these tests verify
activity/session correctness at echo-time and through the reorientation window.

Test sections:
  (A) Echo sets activity + session immediately, per op type. location=ON_LAWN
      is set by the preceding s2p1 undock (not by s2p50 itself).
  (B) Activity is STICKY through simulated reorientation heartbeats.
  (C) The reconcile rule IN_SESSION+MOWING+AT_DOCK→CHARGE_RESUME fires correctly
      when the mower actually docks mid-session (s2p1 AT_DOCK).
  (D) Mow regression: mow still enters IN_SESSION + MOWING; mid-run + end unchanged.
"""
from __future__ import annotations

from custom_components.dreame_a2_mower.state.machine import MowerStateMachine
from custom_components.dreame_a2_mower.state.snapshot import (
    CurrentActivity,
    Location,
    MowSession,
)

T0 = 1_748_900_000  # arbitrary baseline unix (approx 2026-06-01)


def _s2p50_envelope(op: int, status: bool = True) -> dict:
    """Minimal s2p50 TASK envelope as the firmware emits it."""
    return {"d": {"o": op, "status": status}}


# ---------------------------------------------------------------------------
# (A) Echo sets activity + session at command-time
# ---------------------------------------------------------------------------


def test_op100_echo_sets_mowing_and_session():
    """op=100 (all-areas mow): echo must set current_activity=MOWING and
    mow_session=IN_SESSION immediately."""
    sm = MowerStateMachine()

    snap = sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=100), now_unix=T0
    )
    assert snap.current_activity == CurrentActivity.MOWING, (
        f"op=100 echo must set MOWING immediately, got {snap.current_activity!r}"
    )
    assert snap.mow_session == MowSession.IN_SESSION, (
        f"op=100 must enter mow_session=IN_SESSION, got {snap.mow_session!r}"
    )


def test_op101_echo_sets_mowing():
    """op=101 (edge mow): echo must set current_activity=MOWING."""
    sm = MowerStateMachine()
    snap = sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=101), now_unix=T0
    )
    assert snap.current_activity == CurrentActivity.MOWING


def test_op102_echo_sets_mowing():
    """op=102 (zone mow): echo must set current_activity=MOWING."""
    sm = MowerStateMachine()
    snap = sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=102), now_unix=T0
    )
    assert snap.current_activity == CurrentActivity.MOWING


def test_op103_echo_sets_mowing():
    """op=103 (spot mow): echo must set current_activity=MOWING."""
    sm = MowerStateMachine()
    snap = sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=103), now_unix=T0
    )
    assert snap.current_activity == CurrentActivity.MOWING


def test_op108_echo_does_not_enter_session():
    """op=108 (patrol): echo does NOT enter mow_session=IN_SESSION.

    Patrol (108) is NOT a mow op (not in MOW_MODE_CODES), so it does not
    enter mow_session. Location is set by s2p1, not by the echo.
    """
    sm = MowerStateMachine()
    snap = sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=108), now_unix=T0
    )
    # Patrol does NOT enter mow_session
    assert snap.mow_session == MowSession.BETWEEN_SESSIONS


def test_op109_echo_sets_cruising_to_point():
    """op=109 (cruise-to-point): echo must set CRUISING_TO_POINT.

    This is the primary case from the 2026-05-31 to-point trace.
    """
    sm = MowerStateMachine()
    snap = sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=109), now_unix=T0
    )
    assert snap.current_activity == CurrentActivity.CRUISING_TO_POINT, (
        f"op=109 echo must set CRUISING_TO_POINT, got {snap.current_activity!r}"
    )
    assert snap.mow_session == MowSession.BETWEEN_SESSIONS


def test_rejected_echo_does_not_change_activity():
    """status=False (firmware rejected task): echo must NOT change activity.

    A rejected task command does not leave the dock — the mower stays parked.
    """
    sm = MowerStateMachine()
    assert sm.snapshot().location == Location.AT_DOCK

    snap = sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=100, status=False), now_unix=T0
    )
    # Rejected echo must not change location or activity
    assert snap.location == Location.AT_DOCK, (
        f"Rejected echo (status=False) must not change location, "
        f"got {snap.location!r}"
    )
    assert snap.current_activity == CurrentActivity.IDLE


def test_s2p1_undock_sets_on_lawn():
    """Location=ON_LAWN is set by s2p1 undock (from _DOCKED_STATES → working(1)),
    not by the s2p50 echo. Verify the undock path works."""
    sm = MowerStateMachine()
    # Seed docked state
    sm.handle_mqtt_property(siid=2, piid=1, value=13, now_unix=T0 - 10)
    assert sm.snapshot().location == Location.AT_DOCK

    # Undock: s2p1 transitions FROM docked(13) TO working(1) while BETWEEN_SESSIONS
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0)
    assert snap.location == Location.ON_LAWN, (
        f"s2p1 undock (13→1) must set ON_LAWN, got {snap.location!r}"
    )


# ---------------------------------------------------------------------------
# (B) Activity is STICKY through reorientation window
#     (no new s2p1 push, no s1p4 position frames)
# ---------------------------------------------------------------------------


def test_mow_op100_activity_sticky_through_reorientation():
    """After op=100 echo, heartbeats without s2p1/s1p4 must NOT revert activity.

    Simulates the ~45s reorientation window where only heartbeats + tick() arrive.
    """
    sm = MowerStateMachine()

    # s2p1=1 fires BEFORE the command (while still docked)
    sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0 - 45)

    # Command echo: op=100 starts the session
    snap_after_echo = sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=100), now_unix=T0
    )
    assert snap_after_echo.current_activity == CurrentActivity.MOWING

    # Simulate 6 ticks (60s) with NO s2p1 or s1p4 pushes
    for tick in range(6):
        snap = sm.tick(now_unix=T0 + (tick + 1) * 10)
        assert snap.current_activity == CurrentActivity.MOWING, (
            f"Tick {tick}: current_activity reverted to {snap.current_activity!r}. "
            "Activity must be STICKY from echo-time during reorientation window."
        )


def test_op109_activity_sticky_through_reorientation():
    """After op=109 echo, ticks without s1p4 must keep CRUISING_TO_POINT.

    Mirrors the real trace: echo at T0, then s2p1=1 at T0+1 (BUG2 fix),
    then ~4s of silence until first s1p4 arrives.
    """
    sm = MowerStateMachine()

    # s2p1=1 BEFORE the echo (mower was docked and already showed s2p1=1)
    sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0 - 42)

    # Echo: op=109 cruise
    snap = sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=109), now_unix=T0
    )
    assert snap.current_activity == CurrentActivity.CRUISING_TO_POINT

    # s2p1=1 fires AGAIN after echo (firmware confirms working)
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0 + 1)
    # BUG2 fix: s2p1=1 with last_task_op=109 → CRUISING_TO_POINT (not MOWING)
    assert snap.current_activity == CurrentActivity.CRUISING_TO_POINT, (
        f"s2p1=1 after op=109 must stay CRUISING_TO_POINT, got {snap.current_activity!r}"
    )

    # Reorientation silence: 4 more ticks (40s), no s1p4
    for tick in range(4):
        snap = sm.tick(now_unix=T0 + 10 + tick * 10)
        assert snap.current_activity == CurrentActivity.CRUISING_TO_POINT, (
            f"Tick {tick}: activity reverted to {snap.current_activity!r}"
        )


# ---------------------------------------------------------------------------
# (C) The reconcile rule IN_SESSION+MOWING+AT_DOCK→CHARGE_RESUME
#     fires correctly when the mower genuinely docks mid-session
# ---------------------------------------------------------------------------


def test_mow_reconcile_does_not_convert_to_charge_resume_when_on_lawn():
    """After s2p1 undock sets ON_LAWN + op echo sets IN_SESSION+MOWING,
    reconcile must NOT flip MOWING→CHARGE_RESUME while location is ON_LAWN.

    The reconcile rule (state_machine.py _reconcile_mow_activity) fires:
      IN_SESSION + MOWING + AT_DOCK → CHARGE_RESUME
    It must NOT fire when location is ON_LAWN.
    """
    sm = MowerStateMachine()

    # Full undock sequence: s2p1 docked → working, then op=100 echo
    sm.handle_mqtt_property(siid=2, piid=1, value=13, now_unix=T0 - 50)
    assert sm.snapshot().location == Location.AT_DOCK
    sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0 - 45)
    assert sm.snapshot().location == Location.ON_LAWN

    sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=100), now_unix=T0
    )
    assert sm.snapshot().location == Location.ON_LAWN
    assert sm.snapshot().current_activity == CurrentActivity.MOWING
    assert sm.snapshot().mow_session == MowSession.IN_SESSION

    # Reconcile with live_map_active=True, area_mowed=0 (early reorientation window)
    snap = sm.reconcile_from_telemetry(
        live_map_active=True,
        area_mowed_m2=0.0,
        now_unix=T0 + 5,
    )
    assert snap.current_activity == CurrentActivity.MOWING, (
        f"Reconcile must NOT convert MOWING→CHARGE_RESUME while ON_LAWN. "
        f"Got {snap.current_activity!r}."
    )
    assert snap.location == Location.ON_LAWN


def test_reconcile_charge_resume_rule_still_works_when_docked_mid_session():
    """Regression check: IN_SESSION+MOWING+AT_DOCK→CHARGE_RESUME STILL fires
    when the mower has genuinely returned to the dock mid-session (recharge stop).
    """
    sm = MowerStateMachine()

    # Full undock: docked(13) → working(1), then echo
    sm.handle_mqtt_property(siid=2, piid=1, value=13, now_unix=T0 - 50)
    sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0 - 45)
    sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=100), now_unix=T0
    )
    assert sm.snapshot().location == Location.ON_LAWN
    assert sm.snapshot().mow_session == MowSession.IN_SESSION

    # Mower returns to dock — s2p1=6 (charging) sets AT_DOCK via s2p1 authority
    sm.handle_mqtt_property(siid=2, piid=1, value=6, now_unix=T0 + 600)
    assert sm.snapshot().location == Location.AT_DOCK, (
        "s2p1=6 (charging) must set AT_DOCK via location authority"
    )
    assert sm.snapshot().mow_session == MowSession.IN_SESSION, (
        "Session is still active (mid-mow charge stop)"
    )

    # Now reconcile fires: IN_SESSION + MOWING + AT_DOCK → CHARGE_RESUME
    snap = sm.reconcile_from_telemetry(
        live_map_active=True,
        area_mowed_m2=50.0,     # definitely mowing (area > 0)
        now_unix=T0 + 610,
    )
    assert snap.current_activity == CurrentActivity.CHARGE_RESUME, (
        f"Legitimate mid-session dock must still produce CHARGE_RESUME. "
        f"Got {snap.current_activity!r}."
    )


# ---------------------------------------------------------------------------
# (D) Mow regression: full mow lifecycle unchanged
# ---------------------------------------------------------------------------


def test_mow_lifecycle_unchanged():
    """Full mow op=100 lifecycle: still correct from echo through end.

    Location is set by s2p1 undock (13→1), not by op echo.
    """
    sm = MowerStateMachine()

    # Step 0: idle at dock
    assert sm.snapshot().mow_session == MowSession.BETWEEN_SESSIONS
    assert sm.snapshot().location == Location.AT_DOCK

    # Step 0b: s2p1 undock sets ON_LAWN (s2p1 is location authority)
    sm.handle_mqtt_property(siid=2, piid=1, value=13, now_unix=T0 - 50)
    sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0 - 45)
    assert sm.snapshot().location == Location.ON_LAWN

    # Step 1: op=100 echo → IN_SESSION + MOWING
    snap = sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=100), now_unix=T0
    )
    assert snap.mow_session == MowSession.IN_SESSION
    assert snap.current_activity == CurrentActivity.MOWING
    assert snap.location == Location.ON_LAWN

    # Step 2: s2p1=1 → still MOWING (no change since already MOWING)
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0 + 2)
    assert snap.current_activity == CurrentActivity.MOWING
    assert snap.location == Location.ON_LAWN

    # Step 3: mid-mow pause s2p1=4 (charge required)
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=4, now_unix=T0 + 300)
    # Note: task_state=4 (paused) is not mapped in activity_map so stays MOWING
    assert snap.mow_session == MowSession.IN_SESSION

    # Step 4: resume s2p1=1
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0 + 400)
    assert snap.current_activity == CurrentActivity.MOWING

    # Step 5: returning s2p1=5
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=5, now_unix=T0 + 600)
    assert snap.current_activity == CurrentActivity.RETURNING

    # Step 6: s2p1=2 → IDLE + BETWEEN_SESSIONS
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=2, now_unix=T0 + 700)
    assert snap.current_activity == CurrentActivity.IDLE
    assert snap.mow_session == MowSession.BETWEEN_SESSIONS


def test_mow_ops_all_set_mowing_at_echo():
    """All mow ops (100-103) must set current_activity=MOWING + IN_SESSION at echo-time."""
    from custom_components.dreame_a2_mower.protocol.mode_enum import MOW_MODE_CODES

    for op in sorted(MOW_MODE_CODES):
        sm = MowerStateMachine()
        snap = sm.handle_mqtt_property(
            siid=2, piid=50, value=_s2p50_envelope(op=op), now_unix=T0
        )
        assert snap.current_activity == CurrentActivity.MOWING, (
            f"op={op}: echo must set MOWING, got {snap.current_activity!r}"
        )
        assert snap.mow_session == MowSession.IN_SESSION, (
            f"op={op}: echo must enter IN_SESSION, got {snap.mow_session!r}"
        )


def test_at_point_set_after_arrival_not_at_echo():
    """op=109 echo sets CRUISING_TO_POINT; AT_POINT is set LATER by s2p56 stage=2.
    The echo must NOT prematurely set AT_POINT.
    """
    sm = MowerStateMachine()

    snap = sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=109), now_unix=T0
    )
    assert snap.current_activity == CurrentActivity.CRUISING_TO_POINT

    # s2p56 stage=2 arrives → AT_POINT (via activity)
    sm.handle_mqtt_property(
        siid=2, piid=56, value={"status": [[1, 2]]}, now_unix=T0 + 40
    )
    assert sm.snapshot().current_activity == CurrentActivity.AT_POINT

    # s2p2=75 → location AT_POINT
    sm.handle_mqtt_property(siid=2, piid=2, value=75, now_unix=T0 + 41)
    assert sm.snapshot().location == Location.AT_POINT, (
        f"s2p2=75 must set location=AT_POINT, got {sm.snapshot().location!r}"
    )


def test_rejected_echo_stays_at_dock():
    """Sanity: rejected echo (status=False) and op=10 don't change location."""
    sm = MowerStateMachine()

    # op with status=False (rejected): no location change
    sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=100, status=False), now_unix=T0
    )
    assert sm.snapshot().location == Location.AT_DOCK, (
        "Rejected echo must not change location"
    )

    # op=10 (fast mapping) sets FAST_MAPPING activity but location unchanged
    sm2 = MowerStateMachine()
    sm2.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=10), now_unix=T0
    )
    assert sm2.snapshot().current_activity == CurrentActivity.FAST_MAPPING
    # Location stays AT_DOCK (op=10 is not in _DOCKED_STATES → undock path)
    assert sm2.snapshot().location == Location.AT_DOCK
