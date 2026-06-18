"""Error code → human description map per apk fault index."""
from __future__ import annotations

from custom_components.dreame_a2_mower.mower.error_codes import (
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

    Semantic checks: keywords verified against the real fault_catalog.json text
    (apk:g2408-plugin-ext1423).  Each assert confirms the catalog says something
    sensible *per code*, not just that describe_error() delegates (which is trivial).
    """
    # Each code must be present in the catalog.
    for code in (0, 1, 9, 23, 24, 27, 56, 73):
        assert _fc.fault_text(code, "en") is not None, f"catalog missing code {code}"

    # Per-code semantic checks — keywords come from the real catalog text.
    # code 0: "Robot lifted. Place it back on the ground..."
    assert "lifted" in _fc.fault_text(0, "en").lower()
    # code 1: "Robot tilted. Place it back on the ground..."
    assert "tilted" in _fc.fault_text(1, "en").lower()
    # code 9: "Bumper error. Please check."
    assert "bumper" in _fc.fault_text(9, "en").lower()
    # code 23: "Emergency stop is activated. Enter PIN code on the robot to unlock it."
    assert "pin" in _fc.fault_text(23, "en").lower()
    # code 24: "Low battery. The robot will shut down soon."
    assert "battery" in _fc.fault_text(24, "en").lower()
    # code 27: "Human entry into the mapped area is detected. Please be alert."
    assert "human" in _fc.fault_text(27, "en").lower()
    # code 56: "Water is detected on the lidar. Rain Protection is activated..."
    assert "rain" in _fc.fault_text(56, "en").lower()
    # code 73: "Top cover of the robot is not closed. Please check."
    assert "cover" in _fc.fault_text(73, "en").lower()


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


def test_genuine_faults_are_error_tier():
    # error-tier (FAULT + anomaly|malfunction) → latches
    for code in (0, 1, 2, 4, 5, 7, 23, 73):
        assert is_fault(code), f"expected {code} to be an error-tier fault"
    # 31/36 are ALERT in the app → NO LONGER error-tier
    assert not is_fault(31)
    assert not is_fault(36)


def test_non_error_tier_codes_do_not_latch():
    from custom_components.dreame_a2_mower.mower import fault_catalog as fc
    for code in (27, 28, 30, 31, 36, 47, 48, 50, 51, 54, 56, 70, 71, 74, 75, 76):
        assert fc.fault_tier(code) != "error"
        assert not is_fault(code), f"{code} (tier={fc.fault_tier(code)}) must not latch"


def test_error_tier_codes_all_have_catalog_text():
    from custom_components.dreame_a2_mower.mower import fault_catalog as fc
    codes = fc.error_tier_codes("iot")
    assert len(codes) == 26
    for code in codes:
        assert fc.fault_text(code, "en"), f"error code {code} missing catalog text"


def test_is_fault_handles_none_and_unknown():
    assert is_fault(None) is False
    assert is_fault(999) is False


def test_s2p2_72_authoritative_text_and_slug():
    """Catalog EN for 72 = "Automatically return to the station after prolonged pause."
    (apk:g2408-plugin-ext1423). The cloud push wording ("Task paused for too long.
    Automatically returning to the station to wait.") is a wire observation, not the
    display string — display is catalog-sourced (describe_error delegates to fault_catalog).
    """
    from custom_components.dreame_a2_mower.mower.error_codes import S2P2_EVENT_TYPES
    # Semantic check: catalog EN must mention "station" (stable keyword from apk text).
    assert "station" in _fc.fault_text(72, "en").lower(), (
        f"catalog EN for 72 changed unexpectedly: {_fc.fault_text(72, 'en')!r}"
    )
    # Catalog EN must also mention "pause" (the distinguishing word from code 71's "standby").
    assert "pause" in _fc.fault_text(72, "en").lower(), (
        f"catalog EN for 72 missing 'pause': {_fc.fault_text(72, 'en')!r}"
    )
    # Localization must differ (proves describe_error uses the multi-language catalog).
    assert describe_error(72, "nb") != describe_error(72, "en")
    # Event slug must match the catalog-derived value (was "paused_too_long_returning"
    # before the hand dict was replaced with the catalog-derived table in T2).
    assert S2P2_EVENT_TYPES[72] == _fc.event_slug(72)


def test_s2p2_71_unchanged():
    # code 71: "Automatically return to the station after prolonged standby."
    from custom_components.dreame_a2_mower.mower.error_codes import S2P2_EVENT_TYPES
    # Slug is now catalog-derived (was "standby_outside_station_too_long" in hand dict;
    # catalog slug is "idle_timeout_returning" from ALERT_IDLE_TIMEOUT_RETURNING).
    assert S2P2_EVENT_TYPES[71] == _fc.event_slug(71)
    assert "standby" in _fc.fault_text(71, "en").lower()
    # Debunked mislabel must not appear (was once called "positioning failed").
    assert "positioning failed" not in _fc.fault_text(71, "en").lower()


def test_describe_error_localizes_and_falls_back():
    from custom_components.dreame_a2_mower.mower.error_codes import describe_error
    from custom_components.dreame_a2_mower.mower import fault_catalog as fc
    assert describe_error(27, "en") == fc.fault_text(27, "en")
    assert describe_error(27, "nb") == fc.fault_text(27, "nb")
    assert describe_error(27, "nb") != describe_error(27, "en")
    assert describe_error(123456) == "Unknown error 123456"


def test_s2p2_event_types_derived_from_catalog():
    from custom_components.dreame_a2_mower.mower.error_codes import S2P2_EVENT_TYPES
    from custom_components.dreame_a2_mower.mower import fault_catalog as fc
    assert S2P2_EVENT_TYPES[31] == "back_charge_failed"
    assert S2P2_EVENT_TYPES[33] == "locating_failed_with_map"
    assert S2P2_EVENT_TYPES[50] == "task_start"
    assert S2P2_EVENT_TYPES[47] == "task_cancelled"   # supplement (catalog-absent)
    for c in fc.known_codes("iot"):
        assert S2P2_EVENT_TYPES[c] == fc.event_slug(c)
    assert len(S2P2_EVENT_TYPES) == 70
    assert S2P2_EVENT_TYPES[11] == S2P2_EVENT_TYPES[42] == "battery_overheat"
    assert S2P2_EVENT_TYPES[43] == S2P2_EVENT_TYPES[59] == "battery_temp_low"


def test_notification_event_types_derived_and_deduped():
    from custom_components.dreame_a2_mower.mower.error_codes import (
        NOTIFICATION_EVENT_TYPES, S2P2_EVENT_TYPES, S2P2_UNKNOWN_EVENT_TYPE,
    )
    assert NOTIFICATION_EVENT_TYPES == tuple(
        sorted(set(S2P2_EVENT_TYPES.values())) + [S2P2_UNKNOWN_EVENT_TYPE]
    )
    assert NOTIFICATION_EVENT_TYPES.count("battery_overheat") == 1
    assert NOTIFICATION_EVENT_TYPES[-1] == "unknown_s2p2"


def test_const_reexports_same_notification_event_types():
    from custom_components.dreame_a2_mower import const
    from custom_components.dreame_a2_mower.mower.error_codes import (
        NOTIFICATION_EVENT_TYPES as SRC,
    )
    assert const.NOTIFICATION_EVENT_TYPES is SRC
