"""T1/T2: a live patrol must surface a first-class PATROL activity, not sit at
REPOSITIONING for the whole run.

Observed 2026-06-03 (op=107 point patrol): the computed-activity sensor stayed
at `repositioning` the entire patrol because the state machine had no patrol
state and patrol is blades-up (area never grows). The s2p50 op echo
distinguishes edge (108) from point (107), so the activity should read
PATROL_EDGE / PATROL_POINT accordingly — and must NOT enter a mow_session.
"""
from __future__ import annotations

from custom_components.dreame_a2_mower.mower.state_machine import MowerStateMachine
from custom_components.dreame_a2_mower.mower.state_snapshot import (
    CurrentActivity,
    MowSession,
)

T0 = 1_748_700_000


def _s2p50_envelope(op: int, status: bool = True) -> dict:
    return {"d": {"o": op, "status": status}}


def test_op108_echo_yields_patrol_edge():
    sm = MowerStateMachine()
    snap = sm.handle_mqtt_property(siid=2, piid=50, value=_s2p50_envelope(op=108), now_unix=T0)
    assert snap.current_activity == CurrentActivity.PATROL_EDGE
    # Patrol is blades-up — it must NOT open a mow_session.
    assert snap.mow_session != MowSession.IN_SESSION


def test_op107_echo_yields_patrol_point():
    sm = MowerStateMachine()
    snap = sm.handle_mqtt_property(siid=2, piid=50, value=_s2p50_envelope(op=107), now_unix=T0)
    assert snap.current_activity == CurrentActivity.PATROL_POINT
    assert snap.mow_session != MowSession.IN_SESSION


def test_s2p1_1_during_patrol_does_not_clobber_to_mowing():
    """The firmware emits s2p1=1 ("working") during the patrol; it must keep the
    patrol activity, not downgrade to MOWING (the op=109 clobber-guard analogue)."""
    for op, expected in ((107, CurrentActivity.PATROL_POINT), (108, CurrentActivity.PATROL_EDGE)):
        sm = MowerStateMachine()
        sm.handle_mqtt_property(siid=2, piid=50, value=_s2p50_envelope(op=op), now_unix=T0)
        snap = sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0 + 1)
        assert snap.current_activity == expected, (
            f"s2p1=1 after op={op} must keep {expected!r}, got {snap.current_activity!r}"
        )
        assert snap.mow_session != MowSession.IN_SESSION


def test_patrol_exits_to_returning_then_idle_at_end():
    """Full point-patrol tail: op=107 → PATROL_POINT; s2p1=5 → RETURNING;
    s2p1=2 → IDLE. Patrol exits via the normal s2p1 transitions like a mow."""
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=50, value=_s2p50_envelope(op=107), now_unix=T0)
    assert sm.snapshot().current_activity == CurrentActivity.PATROL_POINT

    snap = sm.handle_mqtt_property(siid=2, piid=1, value=5, now_unix=T0 + 100)
    assert snap.current_activity == CurrentActivity.RETURNING

    snap = sm.handle_mqtt_property(siid=2, piid=1, value=2, now_unix=T0 + 110)
    assert snap.current_activity == CurrentActivity.IDLE
