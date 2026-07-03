"""Error sensor (sensor.error_description): slug-state contract, capped <=255.

Bug (live-verified 2026-07-02 HA restart): with >=3 concurrent latched faults
the OLD state (localized text joined with "; ") exceeded HA's 255-char state
limit and HA silently fell the entity back to `unknown`. Live evidence: 5
concurrent faults -- "State Robot tilted...; Right drive wheel error...;
Emergency stop...; Low battery...; Top cover... for sensor.dreame_a2_mower_error
is longer than 255, falling back to unknown".

New contract: state = comma-joined fault event-slugs (mower/fault_catalog.py
event_slug), hard-guaranteed <=255 chars (truncates with a trailing "+N" if
even the slug join would overflow). Full localized text moves to the `faults`
attribute (list of {code, slug, text}); single-fault case: state is that one
slug, not the text.
"""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.dreame_a2_mower.entities.sensor.device import (
    _active_fault_slugs,
    _error_attrs,
)
from custom_components.dreame_a2_mower.mower import fault_catalog as fc
from custom_components.dreame_a2_mower.mower.state_machine import MowerStateMachine

# The live 2026-07-02 incident's 5 concurrent fault codes: tilted, right_wheel,
# emergency_stop, battery_low, top_cover_open (all fault_tier == "error").
_LIVE_INCIDENT_CODES = (1, 5, 23, 24, 73)


def _machine_with(*codes, now=1000):
    m = MowerStateMachine()
    for i, c in enumerate(codes):
        m.handle_mqtt_property(siid=2, piid=2, value=c, now_unix=now + i)
    return m


def _coord(errors):
    return SimpleNamespace(
        hass=SimpleNamespace(config=SimpleNamespace(language="en")),
        state_machine=SimpleNamespace(
            snapshot=lambda: SimpleNamespace(errors=set(errors))
        ),
    )


def test_live_incident_localized_text_join_would_have_overflowed_255():
    """Pins the bug: the OLD text-joined form for these 5 codes is >255 chars."""
    text = "; ".join(fc.fault_text(c, "en") for c in _LIVE_INCIDENT_CODES)
    assert len(text) > 255


def test_error_sensor_state_is_slug_join_not_text():
    m = _machine_with(*_LIVE_INCIDENT_CODES)
    state = _active_fault_slugs(m.snapshot())
    assert state == ",".join(fc.event_slug(c) for c in sorted(_LIVE_INCIDENT_CODES))
    assert len(state) <= 255


def test_error_sensor_single_fault_state_is_the_slug_not_text():
    m = _machine_with(5)  # right_wheel
    assert _active_fault_slugs(m.snapshot()) == fc.event_slug(5)


def test_error_sensor_state_none_when_no_fault():
    m = _machine_with(50)  # mow started, not a fault
    assert _active_fault_slugs(m.snapshot()) is None


def test_error_sensor_slug_state_hard_truncates_on_pathological_overflow():
    """Even an absurd number of latched faults must never exceed 255 chars."""
    snap = SimpleNamespace(errors=set(range(100000, 100060)))  # 60 unknown codes
    state = _active_fault_slugs(snap)
    assert state is not None
    assert len(state) <= 255
    assert "+" in state  # some codes were dropped and counted


def test_error_attrs_faults_list_carries_full_text_for_every_code():
    c = _coord(_LIVE_INCIDENT_CODES)
    attrs = _error_attrs(c)
    faults = attrs["faults"]
    assert len(faults) == len(_LIVE_INCIDENT_CODES)
    by_code = {f["code"]: f for f in faults}
    for code in _LIVE_INCIDENT_CODES:
        assert by_code[code]["slug"] == fc.event_slug(code)
        assert by_code[code]["text"] == fc.fault_text(code, "en")


def test_error_attrs_empty_when_no_errors_still_has_no_faults_key():
    assert _error_attrs(_coord(())) == {}
