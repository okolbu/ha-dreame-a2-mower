from custom_components.dreame_a2_mower.mower.state_machine import MowerStateMachine
from custom_components.dreame_a2_mower.mower import fault_catalog as fc
from custom_components.dreame_a2_mower.entities.sensor.device import _active_fault_text


def _machine_with(*codes, now=1000):
    m = MowerStateMachine()
    for i, c in enumerate(codes):
        m.handle_mqtt_property(siid=2, piid=2, value=c, now_unix=now + i)
    return m


def test_error_sensor_none_when_no_fault():
    m = _machine_with(50)  # mow started, not a fault
    assert _active_fault_text(m.snapshot()) is None


def test_error_sensor_shows_latched_fault():
    m = _machine_with(5)  # right wheel
    assert _active_fault_text(m.snapshot()) == fc.fault_text(5, "en")


def test_error_sensor_joins_multiple_faults():
    m = _machine_with(5, 2)  # right wheel + trapped
    text = _active_fault_text(m.snapshot())
    assert fc.fault_text(5, "en") in text
    assert fc.fault_text(2, "en") in text


def test_error_sensor_persists_when_status_overwrites_raw():
    # The key bug: a non-fault status (71) arriving AFTER a fault must NOT
    # blank the Error sensor — the latch persists until recovery.
    m = _machine_with(5, 71)  # wheel error then standby-return
    assert _active_fault_text(m.snapshot()) == fc.fault_text(5, "en")
