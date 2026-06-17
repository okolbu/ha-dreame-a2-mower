"""self_shutdown fires on the s2p57 rising edge into 1 (firmware low-battery
self-shutdown). Mirrors test_charging_events.py."""
from __future__ import annotations


class _FakeLifecycle:
    def __init__(self):
        self.fired = []

    def trigger(self, event_type, data):
        self.fired.append((event_type, data))


def _coord():
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    c = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    c._prev_shutdown_trigger = None
    lc = _FakeLifecycle()
    c._lifecycle_event = lc
    c._notification_event = None
    return c, lc


def test_self_shutdown_fires_on_edge_into_1():
    c, lc = _coord()
    # first observation primes _prev (set by the caller in _on_state_update)
    c._fire_self_shutdown_if_edge(old=None, new=0, now_unix=100)
    c._prev_shutdown_trigger = 0
    assert lc.fired == []
    c._fire_self_shutdown_if_edge(old=0, new=1, now_unix=200)
    assert lc.fired == [
        ("self_shutdown", {"at_unix": 200, "reason": "low_battery", "value": 1})
    ]


def test_value_already_1_at_first_observation_does_not_fire():
    c, lc = _coord()
    # value already 1 at boot: old=None primes only, no fire
    c._fire_self_shutdown_if_edge(old=None, new=1, now_unix=100)
    assert lc.fired == []


def test_no_refire_while_held_at_1():
    c, lc = _coord()
    c._fire_self_shutdown_if_edge(old=0, new=1, now_unix=100)
    lc.fired.clear()
    c._fire_self_shutdown_if_edge(old=1, new=1, now_unix=110)
    assert lc.fired == []
