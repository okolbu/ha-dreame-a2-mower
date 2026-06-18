from custom_components.dreame_a2_mower.mower.state_machine import MowerStateMachine


def test_fault_code_latches_into_errors():
    m = MowerStateMachine()
    m.handle_mqtt_property(siid=2, piid=2, value=5, now_unix=1000)  # right wheel
    assert 5 in m.snapshot().errors


def test_non_fault_code_does_not_latch():
    m = MowerStateMachine()
    m.handle_mqtt_property(siid=2, piid=2, value=50, now_unix=1000)  # mow started
    assert m.snapshot().errors == frozenset()


def test_non_fault_does_not_evict_latched_fault():
    m = MowerStateMachine()
    m.handle_mqtt_property(siid=2, piid=2, value=5, now_unix=1000)
    m.handle_mqtt_property(siid=2, piid=2, value=47, now_unix=1001)  # 47 = task cancelled (alert), not a fault; 50 clears errors via mow-start path
    # A non-fault code must not disturb the already-latched fault 5.
    assert m.snapshot().errors == frozenset({5})


def test_two_real_faults_accumulate():
    m = MowerStateMachine()
    m.handle_mqtt_property(siid=2, piid=2, value=5, now_unix=1000)   # right wheel
    m.handle_mqtt_property(siid=2, piid=2, value=2, now_unix=1001)   # trapped
    assert m.snapshot().errors == frozenset({2, 5})


def test_same_fault_twice_does_not_re_latch():
    m = MowerStateMachine()
    m.handle_mqtt_property(siid=2, piid=2, value=5, now_unix=1000)
    snap1 = m.snapshot()
    m.handle_mqtt_property(siid=2, piid=2, value=5, now_unix=2000)
    snap2 = m.snapshot()
    assert snap2.errors == frozenset({5})
    # Re-firing the same fault must not re-stamp the errors freshness.
    assert snap2.field_freshness.get("errors") == snap1.field_freshness.get("errors") == 1000


def test_latched_fault_survives_persist_roundtrip():
    from custom_components.dreame_a2_mower.mower.state_snapshot import StateSnapshot
    m = MowerStateMachine()
    m.handle_mqtt_property(siid=2, piid=2, value=5, now_unix=1000)
    restored = StateSnapshot.from_dict(m.snapshot().to_dict())
    assert 5 in restored.errors


def test_movement_clears_faults():
    m = MowerStateMachine()
    m.handle_mqtt_property(siid=2, piid=2, value=5, now_unix=1000)
    m.handle_position(x_m=0.0, y_m=0.0, north_m=None, east_m=None, now_unix=1001)
    # Mower physically moves > 0.3 m → recovery proof per design.
    m.handle_position(x_m=1.0, y_m=0.0, north_m=None, east_m=None, now_unix=1002)
    assert m.snapshot().errors == frozenset()


def test_tiny_jitter_does_not_clear_faults():
    m = MowerStateMachine()
    m.handle_mqtt_property(siid=2, piid=2, value=5, now_unix=1000)
    m.handle_position(x_m=0.0, y_m=0.0, north_m=None, east_m=None, now_unix=1001)
    m.handle_position(x_m=0.05, y_m=0.0, north_m=None, east_m=None, now_unix=1002)
    assert 5 in m.snapshot().errors  # 5 cm jitter is not recovery


def test_undock_clears_faults():
    m = MowerStateMachine()
    # Seed a docked prior state (s2p1=6 charging) then latch a fault.
    m.handle_mqtt_property(siid=2, piid=1, value=6, now_unix=1000)
    m.handle_mqtt_property(siid=2, piid=2, value=5, now_unix=1001)  # right wheel error (error-tier)
    assert 5 in m.snapshot().errors
    # Undock: s2p1 → 1 (working) from docked while BETWEEN_SESSIONS.
    m.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=1002)
    assert m.snapshot().errors == frozenset()


def test_mow_start_clears_faults():
    m = MowerStateMachine()
    m.handle_mqtt_property(siid=2, piid=2, value=5, now_unix=1000)
    m.handle_mqtt_property(siid=2, piid=2, value=50, now_unix=1001)  # mowing_started
    assert m.snapshot().errors == frozenset()


def test_newly_classified_error_code_latches():
    # 73 (top-cover-open, FAULT/malfunction) was NOT in the old FAULT_CODES;
    # the app-derived error tier now latches it.
    m = MowerStateMachine()
    m.handle_mqtt_property(siid=2, piid=2, value=73, now_unix=1000)
    assert 73 in m.snapshot().errors


def test_alert_code_does_not_latch():
    # 31 (back-charge-failed) is ALERT in the app -> alert tier, not error.
    m = MowerStateMachine()
    m.handle_mqtt_property(siid=2, piid=2, value=31, now_unix=1000)
    assert m.snapshot().errors == frozenset()
