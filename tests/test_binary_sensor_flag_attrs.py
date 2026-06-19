"""P4: s1p1 heartbeat-flag sensors carry catalog fault_text/tier/detail attrs.

Tests are at the function / descriptor level so they don't depend on HA
bootstrap (CoordinatorEntity setup is irrelevant here). The entity-property
test uses __new__ + object.__setattr__ to inject the coordinator shallowly.
"""
import types

from custom_components.dreame_a2_mower import binary_sensor as bs
from custom_components.dreame_a2_mower.mower import fault_catalog as fc


def _coord(lang="en"):
    return types.SimpleNamespace(
        hass=types.SimpleNamespace(config=types.SimpleNamespace(language=lang)),
    )


def test_flag_fault_code_map():
    assert bs._S1P1_FLAG_FAULT_CODE == {
        "bumper": 9, "drop_tilt": 1, "lift": 0,
        "emergency_stop": 23, "battery_temp_low": 43,
    }
    assert fc.fault_tier(9) == "error"
    assert fc.fault_tier(43) == "alert"


def test_flag_fault_attrs_localized_and_complete():
    a = bs._flag_fault_attrs(_coord("en"), 9)
    assert a["fault_code"] == 9
    assert a["tier"] == "error"
    assert a["fault_text"] == fc.fault_text(9, "en")
    assert a["fault_detail"] == fc.fault_detail(9, "en")
    anb = bs._flag_fault_attrs(_coord("nb"), 9)
    assert anb["fault_text"] == fc.fault_text(9, "nb")
    assert fc.fault_text(9, "nb") != fc.fault_text(9, "en")


def test_enriched_descriptions_expose_attrs_and_safety_alert_does_not():
    by_key = {d.key: d for d in bs.BINARY_SENSORS}
    for key, code in bs._S1P1_FLAG_FAULT_CODE.items():
        d = by_key[key]
        assert d.extra_state_attributes_fn is not None, f"{key} missing attrs fn"
        attrs = d.extra_state_attributes_fn(_coord("en"))
        assert attrs["fault_code"] == code
        assert attrs["tier"] == fc.fault_tier(code)
    assert by_key["safety_alert_active"].extra_state_attributes_fn is None


def test_entity_extra_state_attributes_property():
    by_key = {d.key: d for d in bs.BINARY_SENSORS}
    ent = bs.DreameA2BinarySensor.__new__(bs.DreameA2BinarySensor)
    ent.entity_description = by_key["bumper"]
    object.__setattr__(ent, "coordinator", _coord("en"))
    attrs = ent.extra_state_attributes
    assert attrs["fault_code"] == 9 and attrs["tier"] == "error"
    ent2 = bs.DreameA2BinarySensor.__new__(bs.DreameA2BinarySensor)
    ent2.entity_description = by_key["safety_alert_active"]
    object.__setattr__(ent2, "coordinator", _coord("en"))
    assert ent2.extra_state_attributes is None
