"""Tests for the unknown-field watchdog.

The watchdog dedupes novelty detections so that an unmapped (siid, piid)
pair observed during active mowing — where it would otherwise fire once
every 5 s via the s1p4 cadence — only logs once per HA process lifetime.
"""

from __future__ import annotations

from protocol.unknown_watchdog import UnknownFieldWatchdog


def test_first_property_observation_is_novel():
    watchdog = UnknownFieldWatchdog()
    assert watchdog.saw_property(1, 99) is True


def test_repeat_property_observation_is_not_novel():
    watchdog = UnknownFieldWatchdog()
    watchdog.saw_property(1, 99)
    assert watchdog.saw_property(1, 99) is False


def test_different_property_is_novel():
    watchdog = UnknownFieldWatchdog()
    watchdog.saw_property(1, 99)
    assert watchdog.saw_property(2, 99) is True
    assert watchdog.saw_property(1, 100) is True


def test_first_method_observation_is_novel():
    watchdog = UnknownFieldWatchdog()
    assert watchdog.saw_method("action_invoked") is True


def test_repeat_method_observation_is_not_novel():
    watchdog = UnknownFieldWatchdog()
    watchdog.saw_method("action_invoked")
    assert watchdog.saw_method("action_invoked") is False


def test_first_event_observation_is_novel():
    watchdog = UnknownFieldWatchdog()
    assert watchdog.saw_event(4, 1, (1, 2, 3, 9)) is True


def test_event_with_new_piid_in_same_eiid_is_novel():
    """If we see siid=4, eiid=1 with piids {1,2,3} then later {1,2,99},
    the 99 should trigger a new-piid alert even though the (siid, eiid)
    pair itself has been seen."""
    watchdog = UnknownFieldWatchdog()
    watchdog.saw_event(4, 1, (1, 2, 3))
    assert watchdog.saw_event(4, 1, (1, 2, 99)) is True


def test_event_with_known_piids_is_not_novel():
    watchdog = UnknownFieldWatchdog()
    watchdog.saw_event(4, 1, (1, 2, 3))
    assert watchdog.saw_event(4, 1, (1, 2)) is False
    assert watchdog.saw_event(4, 1, (3,)) is False


def test_property_and_method_tracking_are_independent():
    watchdog = UnknownFieldWatchdog()
    watchdog.saw_method("properties_changed")
    assert watchdog.saw_property(2, 1) is True


def test_method_observation_with_empty_string_is_tracked():
    """An empty or None method is still worth flagging — means the
    message didn't carry one at all, which is itself novel."""
    watchdog = UnknownFieldWatchdog()
    assert watchdog.saw_method("") is True
    assert watchdog.saw_method("") is False
