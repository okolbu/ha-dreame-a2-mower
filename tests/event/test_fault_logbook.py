from custom_components.dreame_a2_mower.logbook import _format


def test_fault_detected_renders_description():
    msg = _format(
        "event.dreame_a2_mower_lifecycle",
        "fault_detected",
        {"code": 5, "description": "Right drive wheel error"},
    )
    assert msg == "fault: Right drive wheel error"


def test_fault_cleared_renders_recovered():
    msg = _format(
        "event.dreame_a2_mower_lifecycle",
        "fault_cleared",
        {"code": 5, "description": "Right drive wheel error"},
    )
    assert msg == "recovered: Right drive wheel error"


def test_fault_in_lifecycle_event_types():
    from custom_components.dreame_a2_mower.const import (
        LIFECYCLE_EVENT_TYPES,
        EVENT_TYPE_FAULT_DETECTED,
        EVENT_TYPE_FAULT_CLEARED,
    )
    assert EVENT_TYPE_FAULT_DETECTED in LIFECYCLE_EVENT_TYPES
    assert EVENT_TYPE_FAULT_CLEARED in LIFECYCLE_EVENT_TYPES


def test_fault_detected_falls_back_to_code_when_no_description():
    msg = _format(
        "event.dreame_a2_mower_lifecycle",
        "fault_detected",
        {"code": 5},  # no description
    )
    assert msg == "fault: error 5"
