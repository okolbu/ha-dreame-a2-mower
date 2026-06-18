from custom_components.dreame_a2_mower.mower import fault_catalog as fc


def test_fault_text_picks_first_nonempty_and_localizes():
    assert fc.fault_text(27, "en").startswith("Human entry into the mapped area")
    assert fc.fault_text(27, "nb")
    assert fc.fault_text(27, "nb") != fc.fault_text(27, "en")
    assert fc.fault_text(0, "en")


def test_fault_text_unknown_lang_falls_back_to_en():
    assert fc.fault_text(27, "xx") == fc.fault_text(27, "en")


def test_fault_text_unknown_code_is_none():
    assert fc.fault_text(99999, "en") is None


def test_metadata_helpers():
    assert fc.fault_name(27) == "FAULT_HUMAN_DETECTED"
    assert fc.fault_category(27) == "FAULT"
    assert fc.fault_category(72) == "INFO"
    assert fc.can_suppress(27) is True
    assert fc.fault_severity(72) == "work_message"
    assert 27 in fc.known_codes("iot")
    assert fc.can_suppress(99999) is False


def test_detail_has_real_newlines():
    d = fc.fault_detail(0, "en")
    assert d and "\\n" not in d


def test_resolve_lang():
    assert fc.resolve_lang("nb") == "nb"
    assert fc.resolve_lang("zh-Hans") == "zh"
    assert fc.resolve_lang("en-GB") == "en"
    assert fc.resolve_lang("ja") == "en"
    assert fc.resolve_lang(None) == "en"
    assert "en" in fc.SUPPORTED_LANGS and len(fc.SUPPORTED_LANGS) == 21


def test_fault_tier_maps_category_and_severity():
    assert fc.fault_tier(4) == "error"        # FAULT + malfunction
    assert fc.fault_tier(0) == "error"        # FAULT + anomaly
    assert fc.fault_tier(73) == "error"       # FAULT + malfunction (top cover)
    assert fc.fault_tier(27) == "attention"   # FAULT + work_message (human)
    assert fc.fault_tier(28) == "attention"   # FAULT + consumable (blade worn)
    assert fc.fault_tier(31) == "alert"       # ALERT
    assert fc.fault_tier(48) == "info"        # INFO
    assert fc.fault_tier(99999) is None       # unknown


def test_error_tier_codes_is_the_pinned_26():
    assert fc.error_tier_codes("iot") == frozenset(
        {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17,
         20, 21, 22, 23, 24, 26, 37, 59, 73}
    )
    assert 31 not in fc.error_tier_codes("iot")  # ALERT, not error
