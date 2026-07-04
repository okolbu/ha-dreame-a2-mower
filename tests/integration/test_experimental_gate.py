"""P4.1: experimental-features opt-in gate mechanism (R-52).

Pins the MECHANISM only — no production entity/service is experimental yet
(that's P4.4). These tests exercise:

  * ``experimental_features_enabled`` — reads the ``experimental_features``
    option, defaults off, honours the LEGACY ``debug_services`` option;
  * ``filter_experimental`` — a descriptor with an ``experimental`` tier is
    NOT created when the gate is off, and IS created (forced
    ``entity_registry_enabled_default=False``) when on; a plain descriptor is
    always created;
  * the descriptor bases carry the ``experimental`` field (default None);
  * ``experimental_service`` — a gated service RAISES ServiceValidationError
    with a clear message when off, and runs when on;
  * the unified debug-service gate now keys on ``experimental_features`` while
    staying backward-compatible with a pre-P4 ``debug_services`` option.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.dreame_a2_mower._experimental import (
    experimental_features_enabled,
    filter_experimental,
)
from custom_components.dreame_a2_mower.const import (
    CONF_DEBUG_SERVICES,
    CONF_EXPERIMENTAL_FEATURES,
    EXPERIMENTAL_T1_SPECULATIVE,
    EXPERIMENTAL_T2_WIRE_UNEXERCISED,
    EXPERIMENTAL_T3_FAIL_CLOSED,
)


# ---------------------------------------------------------------------------
# experimental_features_enabled
# ---------------------------------------------------------------------------
def test_gate_defaults_off_with_no_entry():
    assert experimental_features_enabled(None) is False


def test_gate_defaults_off_with_empty_options():
    assert experimental_features_enabled(SimpleNamespace(options={})) is False


def test_gate_on_when_option_true():
    entry = SimpleNamespace(options={CONF_EXPERIMENTAL_FEATURES: True})
    assert experimental_features_enabled(entry) is True


def test_gate_off_when_option_false():
    entry = SimpleNamespace(options={CONF_EXPERIMENTAL_FEATURES: False})
    assert experimental_features_enabled(entry) is False


def test_gate_honours_legacy_debug_services_option():
    """A pre-P4 entry that only carries debug_services=True still enables the
    unified gate (graceful migration; no re-configure needed)."""
    entry = SimpleNamespace(options={CONF_DEBUG_SERVICES: True})
    assert experimental_features_enabled(entry) is True


def test_gate_does_not_crash_on_missing_options_attr():
    """An object without an ``options`` attribute is treated as off, not a crash."""
    assert experimental_features_enabled(SimpleNamespace()) is False


# ---------------------------------------------------------------------------
# filter_experimental
# ---------------------------------------------------------------------------
def _entity(tier):
    """Fake entity carrying an entity_description with an experimental tier."""
    desc = SimpleNamespace(experimental=tier)
    return SimpleNamespace(entity_description=desc)


def _plain_entity():
    """Fake entity with no experimental tier."""
    return SimpleNamespace(entity_description=SimpleNamespace(experimental=None))


def test_filter_keeps_plain_entities_regardless_of_gate():
    plain = _plain_entity()
    off = filter_experimental(None, [plain])
    on = filter_experimental(SimpleNamespace(options={CONF_EXPERIMENTAL_FEATURES: True}), [plain])
    assert off == [plain]
    assert on == [plain]


def test_filter_skips_experimental_when_off():
    plain = _plain_entity()
    exp = _entity(EXPERIMENTAL_T1_SPECULATIVE)
    out = filter_experimental(None, [plain, exp])
    assert out == [plain]  # experimental one dropped entirely


def test_filter_creates_experimental_disabled_when_on():
    plain = _plain_entity()
    exp = _entity(EXPERIMENTAL_T1_SPECULATIVE)
    entry = SimpleNamespace(options={CONF_EXPERIMENTAL_FEATURES: True})
    out = filter_experimental(entry, [plain, exp])
    assert out == [plain, exp]
    # Experimental entity is forced disabled-by-default even when the gate is on.
    assert exp._attr_entity_registry_enabled_default is False
    # Plain entity is untouched.
    assert not hasattr(plain, "_attr_entity_registry_enabled_default")


def test_filter_handles_entity_without_description():
    """An entity with no entity_description is treated as plain (created)."""
    e = SimpleNamespace()
    assert filter_experimental(None, [e]) == [e]


# ---------------------------------------------------------------------------
# descriptor bases carry the experimental field
# ---------------------------------------------------------------------------
def test_descriptor_bases_have_experimental_field_default_none():
    from custom_components.dreame_a2_mower.entities.sensor.base import (
        DreameA2DiagnosticSensorEntityDescription,
        DreameA2SensorEntityDescription,
    )
    from custom_components.dreame_a2_mower.entities.switch.base import (
        DreameA2SwitchEntityDescription,
    )
    from custom_components.dreame_a2_mower.entities.select.base import (
        DreameA2SettingsSelectDescription,
    )
    from custom_components.dreame_a2_mower.number import (
        DreameA2NumberEntityDescription,
    )
    from custom_components.dreame_a2_mower.binary_sensor import (
        DreameA2BinarySensorEntityDescription,
    )
    from custom_components.dreame_a2_mower.time import (
        DreameA2TimeEntityDescription,
    )

    # value_fn is required on some; supply a trivial one where needed.
    d1 = DreameA2SensorEntityDescription(key="k", value_fn=lambda s: None)
    assert d1.experimental is None
    d2 = DreameA2DiagnosticSensorEntityDescription(key="k", value_fn=lambda c: None)
    assert d2.experimental is None
    d3 = DreameA2SwitchEntityDescription(key="k", value_fn=lambda s: None)
    assert d3.experimental is None
    d4 = DreameA2SettingsSelectDescription(key="k", value_fn=lambda s: None)
    assert d4.experimental is None
    d5 = DreameA2NumberEntityDescription(key="k", value_fn=lambda s: None)
    assert d5.experimental is None
    d6 = DreameA2BinarySensorEntityDescription(key="k", value_fn=lambda c: None)
    assert d6.experimental is None
    d7 = DreameA2TimeEntityDescription(key="k", minutes_fn=lambda s: None)
    assert d7.experimental is None

    # And a tier value is accepted.
    d8 = DreameA2SensorEntityDescription(
        key="k", value_fn=lambda s: None, experimental=EXPERIMENTAL_T2_WIRE_UNEXERCISED
    )
    assert d8.experimental == EXPERIMENTAL_T2_WIRE_UNEXERCISED


def test_tier_constants_are_distinct():
    tiers = {
        EXPERIMENTAL_T1_SPECULATIVE,
        EXPERIMENTAL_T2_WIRE_UNEXERCISED,
        EXPERIMENTAL_T3_FAIL_CLOSED,
    }
    assert len(tiers) == 3


# ---------------------------------------------------------------------------
# experimental_service — raise-when-off gate for functional services
# ---------------------------------------------------------------------------
async def test_experimental_service_raises_when_off(monkeypatch):
    from homeassistant.exceptions import ServiceValidationError

    from custom_components.dreame_a2_mower import services

    ran = False

    async def _body(coordinator, call):
        nonlocal ran
        ran = True

    gated = services.experimental_service(_body)
    coord = SimpleNamespace(entry=SimpleNamespace(options={CONF_EXPERIMENTAL_FEATURES: False}))
    monkeypatch.setattr(services, "_coordinator_from_call", lambda hass, call: coord)
    call = SimpleNamespace(hass=SimpleNamespace(), data={})
    with pytest.raises(ServiceValidationError):
        await gated(call)
    assert ran is False


async def test_experimental_service_runs_when_on(monkeypatch):
    from custom_components.dreame_a2_mower import services

    ran = False

    async def _body(coordinator, call):
        nonlocal ran
        ran = True

    gated = services.experimental_service(_body)
    coord = SimpleNamespace(entry=SimpleNamespace(options={CONF_EXPERIMENTAL_FEATURES: True}))
    monkeypatch.setattr(services, "_coordinator_from_call", lambda hass, call: coord)
    call = SimpleNamespace(hass=SimpleNamespace(), data={})
    await gated(call)
    assert ran is True


async def test_experimental_service_short_circuits_without_coordinator(monkeypatch):
    """No coordinator → no-op (no raise), mirroring service_handler."""
    from custom_components.dreame_a2_mower import services

    async def _body(coordinator, call):
        raise AssertionError("body must not run")

    gated = services.experimental_service(_body)
    monkeypatch.setattr(services, "_coordinator_from_call", lambda hass, call: None)
    call = SimpleNamespace(hass=SimpleNamespace(), data={})
    assert await gated(call) is None
