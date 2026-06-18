from types import SimpleNamespace

from custom_components.dreame_a2_mower.entities.sensor.device import (
    _active_fault_text, _error_attrs,
)
from custom_components.dreame_a2_mower.mower import fault_catalog as fc


def _coord(language, errors):
    return SimpleNamespace(
        hass=SimpleNamespace(config=SimpleNamespace(language=language)),
        state_machine=SimpleNamespace(snapshot=lambda: SimpleNamespace(errors=set(errors))),
    )


def test_active_fault_text_localizes_by_hass_language():
    c = _coord("nb", {27})
    assert _active_fault_text(c.state_machine.snapshot(), c) == fc.fault_text(27, "nb")


def test_active_fault_text_no_coord_is_english():
    snap = SimpleNamespace(errors={27})
    assert _active_fault_text(snap) == fc.fault_text(27, "en")


def test_active_fault_text_none_when_no_errors():
    assert _active_fault_text(SimpleNamespace(errors=set()), _coord("nb", set())) is None


def test_error_attrs_detail_names_categories():
    c = _coord("en", {27, 4})
    a = _error_attrs(c)
    assert "FAULT_HUMAN_DETECTED" in a["fault_names"]
    assert "FAULT" in a["fault_categories"]
    assert a["error_detail"]


def test_error_attrs_empty_when_no_errors():
    assert _error_attrs(_coord("en", set())) == {}
