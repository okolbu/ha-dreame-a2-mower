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
