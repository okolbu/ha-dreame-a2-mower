"""Tests for _DeviceSyncMixin._fire_fault_delta — fires fault_detected /
fault_cleared lifecycle events when snapshot.errors changes.

Uses the same lightweight bound-mixin harness as test_base_render_on_activity
and test_inject_live_map_meta: a SimpleNamespace carrying only the attrs the
method needs, with the mixin methods bound via types.MethodType.
"""
from __future__ import annotations

import types

from custom_components.dreame_a2_mower.coordinator._device_sync import _DeviceSyncMixin
from custom_components.dreame_a2_mower.const import (
    EVENT_TYPE_FAULT_DETECTED,
    EVENT_TYPE_FAULT_CLEARED,
)


class _RecordingLifecycle:
    """Minimal stand-in for the lifecycle EventEntity.

    Records every trigger(event_type, data) call so tests can assert on
    which events were fired and with what payloads.
    """

    def __init__(self):
        self.fired: list[tuple[str, dict]] = []

    def trigger(self, event_type: str, data: dict | None = None) -> None:
        self.fired.append((event_type, data or {}))


def _make_coord() -> types.SimpleNamespace:
    """Build the minimal namespace that _fire_fault_delta needs.

    Required by _fire_lifecycle:
      - self._lifecycle_event  (set by register_event_entities)
    _fire_fault_delta itself only calls _fire_lifecycle internally.
    """
    coord = types.SimpleNamespace()
    coord._lifecycle_event = None  # pre-set so _fire_lifecycle guard works
    coord._notification_event = None

    # Bind the two methods from the mixin.
    for name in ("_fire_lifecycle", "_fire_fault_delta", "register_event_entities"):
        setattr(
            coord,
            name,
            types.MethodType(getattr(_DeviceSyncMixin, name), coord),
        )
    return coord


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_fault_delta_fires_detected_and_cleared():
    """New fault → fault_detected; fault gone → fault_cleared."""
    coord = _make_coord()
    lc = _RecordingLifecycle()
    coord.register_event_entities(lifecycle=lc, notification=None)

    # Fault code 5 appears.
    coord._fire_fault_delta(frozenset(), frozenset({5}), now_unix=1000)
    # Fault code 5 is cleared.
    coord._fire_fault_delta(frozenset({5}), frozenset(), now_unix=1100)

    types_fired = [t for t, _ in lc.fired]
    assert EVENT_TYPE_FAULT_DETECTED in types_fired
    assert EVENT_TYPE_FAULT_CLEARED in types_fired

    detected = next(d for t, d in lc.fired if t == EVENT_TYPE_FAULT_DETECTED)
    assert detected["code"] == 5
    assert detected["description"] == "Right drive wheel error"
    assert detected["at_unix"] == 1000

    cleared = next(d for t, d in lc.fired if t == EVENT_TYPE_FAULT_CLEARED)
    assert cleared["code"] == 5
    assert cleared["at_unix"] == 1100


def test_fault_delta_noop_when_unchanged():
    """No event is fired when prev == new."""
    coord = _make_coord()
    lc = _RecordingLifecycle()
    coord.register_event_entities(lifecycle=lc, notification=None)

    coord._fire_fault_delta(frozenset({5}), frozenset({5}), now_unix=1000)
    assert lc.fired == []


def test_fault_delta_noop_when_entity_unregistered():
    """When lifecycle entity is None, _fire_lifecycle no-ops gracefully."""
    coord = _make_coord()
    # _lifecycle_event stays None — no register_event_entities call.

    # Should not raise.
    coord._fire_fault_delta(frozenset(), frozenset({5}), now_unix=1000)


def test_fault_delta_fires_multiple_codes_sorted():
    """Multiple new faults fire in sorted code order."""
    coord = _make_coord()
    lc = _RecordingLifecycle()
    coord.register_event_entities(lifecycle=lc, notification=None)

    coord._fire_fault_delta(frozenset(), frozenset({10, 5, 3}), now_unix=2000)

    assert len(lc.fired) == 3
    codes = [d["code"] for _, d in lc.fired]
    assert codes == sorted(codes)


def test_fault_delta_partial_change():
    """One fault added, one retained, one cleared."""
    coord = _make_coord()
    lc = _RecordingLifecycle()
    coord.register_event_entities(lifecycle=lc, notification=None)

    # prev={5, 10}, new={10, 20} → detected=20, cleared=5
    coord._fire_fault_delta(frozenset({5, 10}), frozenset({10, 20}), now_unix=3000)

    types_fired = [t for t, _ in lc.fired]
    assert types_fired.count(EVENT_TYPE_FAULT_DETECTED) == 1
    assert types_fired.count(EVENT_TYPE_FAULT_CLEARED) == 1

    detected = next(d for t, d in lc.fired if t == EVENT_TYPE_FAULT_DETECTED)
    assert detected["code"] == 20

    cleared = next(d for t, d in lc.fired if t == EVENT_TYPE_FAULT_CLEARED)
    assert cleared["code"] == 5
