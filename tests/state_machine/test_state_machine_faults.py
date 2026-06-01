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
    m.handle_mqtt_property(siid=2, piid=2, value=73, now_unix=1001)  # 73 is NOT in FAULT_CODES
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
