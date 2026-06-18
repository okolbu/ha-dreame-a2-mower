import json
from pathlib import Path

from custom_components.dreame_a2_mower.mower import fault_catalog as fc

_DATA = Path(fc.__file__).parent / "data" / "fault_catalog.json"
_CATEGORIES = {"FAULT", "ALERT", "INFO"}
_SEVERITIES = {"anomaly", "malfunction", "work_message", "consumable", "unknown"}


def test_bundled_file_parses_and_has_both_channels():
    d = json.loads(_DATA.read_text(encoding="utf-8"))
    assert d["iot"] and d["heartbeat"]
    assert len(d["meta"]["langs"]) == 21


def test_every_entry_well_formed():
    d = json.loads(_DATA.read_text(encoding="utf-8"))
    for channel in ("iot", "heartbeat"):
        for code, e in d[channel].items():
            assert e["fault_name"], f"{channel} {code} missing fault_name"
            assert e["category"] in _CATEGORIES, f"{channel} {code} category={e['category']}"
            assert e["severity"] in _SEVERITIES, f"{channel} {code} severity={e['severity']}"
            assert isinstance(e["can_suppress"], bool)
            assert "en" in e["lang"], f"{channel} {code} missing en"


def test_covers_wire_confirmed_codes():
    iot = fc.known_codes("iot")
    for c in (0, 4, 5, 27, 72):
        assert c in iot, f"iot code {c} missing from catalog"
        assert fc.fault_text(c, "en"), f"iot code {c} has no en display text"


def test_event_slug_strips_prefix_and_lowercases():
    assert fc.event_slug(27) == "human_detected"   # FAULT_HUMAN_DETECTED
    assert fc.event_slug(31) == "back_charge_failed"  # ALERT_BACK_CHARGE_FAILED (was wrong)
    assert fc.event_slug(48) == "task_finish"      # INFO_TASK_FINISH
    assert fc.event_slug(75) == "go_to_cleanpoint_success"  # FAULT_GO_TO_CLEANPOINT_SUCCESS


def test_event_slug_none_for_absent_code():
    assert fc.event_slug(47) is None   # not in the catalog
    assert fc.event_slug(9999) is None


def test_event_slug_covers_every_iot_code():
    for c in fc.known_codes("iot"):
        assert fc.event_slug(c), f"code {c} has no slug"
