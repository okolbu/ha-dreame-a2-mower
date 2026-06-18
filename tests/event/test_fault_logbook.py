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


def test_logbook_notification_prefers_payload_text():
    from custom_components.dreame_a2_mower.logbook import _format
    msg = _format("event.x_notification", "human_detected", {"text": "A person was detected"})
    assert msg == "A person was detected"


def test_logbook_notification_no_text_falls_back_to_slug_words():
    from custom_components.dreame_a2_mower.logbook import _format
    msg = _format("event.x_notification", "back_charge_failed", {})
    assert msg == "back charge failed"


def test_logbook_notification_messages_table_removed():
    import custom_components.dreame_a2_mower.logbook as lb
    assert not hasattr(lb, "_NOTIFICATION_MESSAGES")
