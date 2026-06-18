"""Error code → human description map per apk fault index."""
from __future__ import annotations

from custom_components.dreame_a2_mower.mower.error_codes import (
    FAULT_CODES,
    S2P2_EVENT_TYPES,
    describe_error,
    is_fault,
)
from custom_components.dreame_a2_mower.mower import fault_catalog as _fc


def test_known_error_codes_mapped():
    """The most-confirmed error codes from protocol-doc §2.1 row s2.2 are in the catalog.

    Code 0 was previously labelled "No error / OK" (apk vacuum-derived), then
    corrected to "Bumper / hanging" on 2026-06-01 after the 2026-04-30 controlled
    test showed s2p2 1→0 co-fired with the HB bumper bit (not a steady-state idle).
    Now backed by the app catalog; descriptions are catalog-authoritative.
    """
    # Each code must exist in the catalog and describe_error must delegate to it.
    for code in (0, 1, 9, 23, 24, 27, 56, 73):
        cat_text = _fc.fault_text(code, "en")
        assert cat_text is not None, f"catalog missing code {code}"
        assert describe_error(code) == cat_text, f"describe_error({code}) diverges from catalog"


def test_describe_known_returns_description():
    assert describe_error(24) == _fc.fault_text(24, "en")


def test_describe_unknown_returns_fallback():
    """Unknown codes return a fallback description."""
    assert describe_error(9999) == "Unknown error 9999"


def test_cloud_verified_s2p2_labels_reconciled():
    """Catalog must agree with the 2026-05-26 cloud-verified s2p2→text mapping
    (inventory.yaml § s2p2). These were vacuum-derived guesses that contradicted
    verified facts — see the reconcile-with-s2p2 TODO.
    """
    # 63: was "Blocked" → cloud "Robot is working. Scheduled task cancelled."
    assert "cancel" in _fc.fault_text(63, "en").lower() and "blocked" not in _fc.fault_text(63, "en").lower()
    # 50: was "Status 50 (unnamed)" → cloud "Mowing task started."
    assert "start" in _fc.fault_text(50, "en").lower()
    # 54: was vacuum "Edge fault" → low_battery_return (TODO-flagged conflict)
    assert "batter" in _fc.fault_text(54, "en").lower() and _fc.fault_text(54, "en").lower().count("edge") == 0
    # 28: blade-wear notification (wear%-gated); off-dock-marker reading debunked
    assert "blade" in _fc.fault_text(28, "en").lower()
    # cloud-verified codes now present in the catalog:
    assert "maintenance" in _fc.fault_text(30, "en").lower()
    assert "start" in _fc.fault_text(36, "en").lower() or "retry" in _fc.fault_text(36, "en").lower()
    assert "continue" in _fc.fault_text(70, "en").lower() or "unfinished" in _fc.fault_text(70, "en").lower()


def test_descriptions_do_not_contradict_event_slugs():
    """For the cloud-verified set, each description must be compatible with its
    S2P2_EVENT_TYPES slug (the two tables are different views of the same code
    and must not disagree on meaning)."""
    expect = {48: "complete", 50: "start", 56: "rain", 63: "cancel",
              70: "continue", 30: "maintenance", 36: "start"}
    for code, kw in expect.items():
        assert code in S2P2_EVENT_TYPES, code
        assert _fc.fault_text(code, "en") is not None, code
        assert kw in _fc.fault_text(code, "en").lower(), (code, _fc.fault_text(code, "en"))


# Adding a code to FAULT_CODES requires g2408 evidence + an inventory.yaml
# § s2p2 verification entry (CLAUDE.md fact-discipline). The positive +
# negative tests below together pin the exact membership.
def test_genuine_faults_are_faults():
    # Wire/cloud-VERIFIED s2p2 faults that require user intervention.
    for code in (2, 4, 5, 23, 31, 36):
        assert is_fault(code), f"expected {code} to be a fault"


def test_status_lifecycle_and_unverified_codes_are_not_faults():
    # Lifecycle / "(not an error)" / self-recovering / maintenance codes...
    # ...plus 24/43 (battery lifecycle), 33 (owned by positioning_health),
    # 76 (auto-returns home), and the unverified vacuum-lineage codes that
    # MUST NOT latch ERROR until confirmed on g2408.
    for code in (0, 24, 28, 30, 33, 43, 47, 48, 50, 51, 53, 54, 56, 63, 70,
                 71, 74, 75, 76,
                 37, 38, 39, 40, 41, 45, 49, 57, 58, 61, 62, 73, 117):
        assert not is_fault(code), f"expected {code} to NOT be a fault"


def test_fault_codes_are_all_described():
    for code in FAULT_CODES:
        assert _fc.fault_text(code, "en") is not None, f"fault {code} missing catalog entry"


def test_is_fault_handles_none_and_unknown():
    assert is_fault(None) is False
    assert is_fault(999) is False


def test_s2p2_72_authoritative_text_and_slug():
    from custom_components.dreame_a2_mower.mower.error_codes import S2P2_EVENT_TYPES
    assert describe_error(72, "en") == _fc.fault_text(72, "en")
    assert describe_error(72, "nb") != describe_error(72, "en")
    assert S2P2_EVENT_TYPES[72] == "paused_too_long_returning"


def test_s2p2_71_unchanged():
    from custom_components.dreame_a2_mower.mower.error_codes import S2P2_EVENT_TYPES
    assert S2P2_EVENT_TYPES[71] == "standby_outside_station_too_long"
    assert _fc.fault_text(71, "en") is not None


def test_describe_error_localizes_and_falls_back():
    from custom_components.dreame_a2_mower.mower.error_codes import describe_error
    from custom_components.dreame_a2_mower.mower import fault_catalog as fc
    assert describe_error(27, "en") == fc.fault_text(27, "en")
    assert describe_error(27, "nb") == fc.fault_text(27, "nb")
    assert describe_error(27, "nb") != describe_error(27, "en")
    assert describe_error(123456) == "Unknown error 123456"
