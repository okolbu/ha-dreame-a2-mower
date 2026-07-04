"""Tests for s2p1 as the single location authority (dock ↔ off-dock axis).

Corpus-decided facts (do NOT relitigate):
- Dock cluster = {6, 13, 15, 16}:
    6  = charging (main)
    13 = charged (main)
    16 = temp-hold (verified dock-only cycle)
    15 = charging-paused (presumed docked, unobserved)
- s2p1=2 (idle) is a LAWN state — must never set AT_DOCK.
- Off-dock s2p1 must not clobber AT_POINT / OUTSIDE_KNOWN_AREA (set by s2p2).
"""
from custom_components.dreame_a2_mower.state.machine import MowerStateMachine
from custom_components.dreame_a2_mower.state.snapshot import Location, CurrentActivity


def _sm():
    return MowerStateMachine()


def test_docked_states_set_at_dock():
    for code in (6, 13, 15, 16):
        m = _sm()
        m.handle_mqtt_property(siid=2, piid=1, value=code, now_unix=1000)
        assert m.snapshot().location == Location.AT_DOCK, code


def test_idle_does_not_set_at_dock():
    m = _sm()
    # s2p1=1 (working) establishes a known ON_LAWN state before sending idle.
    m.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=1000)   # off-dock
    assert m.snapshot().location == Location.ON_LAWN
    m.handle_mqtt_property(siid=2, piid=1, value=2, now_unix=1001)   # idle on lawn
    assert m.snapshot().location != Location.AT_DOCK


def test_undock_from_dock_sets_on_lawn_and_repositioning():
    m = _sm()
    m.handle_mqtt_property(siid=2, piid=1, value=6, now_unix=1000)   # docked/charging
    m.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=1001)   # exit
    assert m.snapshot().location == Location.ON_LAWN
    assert m.snapshot().current_activity == CurrentActivity.REPOSITIONING


def test_redock_sets_at_dock():
    m = _sm()
    m.handle_mqtt_property(siid=2, piid=1, value=6, now_unix=1000)
    m.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=1001)   # left
    assert m.snapshot().location == Location.ON_LAWN
    m.handle_mqtt_property(siid=2, piid=1, value=5, now_unix=1002)   # returning (off-dock)
    assert m.snapshot().location != Location.AT_DOCK
    m.handle_mqtt_property(siid=2, piid=1, value=6, now_unix=1003)   # re-docked / charging
    assert m.snapshot().location == Location.AT_DOCK


def test_offdock_s2p1_does_not_clobber_at_point():
    m = _sm()
    m.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=1000)   # off-dock
    m.handle_mqtt_property(siid=2, piid=2, value=75, now_unix=1001)  # arrived at point
    assert m.snapshot().location == Location.AT_POINT
    m.handle_mqtt_property(siid=2, piid=1, value=5, now_unix=1002)   # returning, still off-dock
    assert m.snapshot().location == Location.AT_POINT  # must stay AT_POINT, not AT_DOCK or ON_LAWN
    # (AT_POINT may later become ON_LAWN on movement; the point is s2p1 off-dock
    #  must not flip it to AT_DOCK.)
