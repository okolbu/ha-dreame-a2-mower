from custom_components.dreame_a2_mower.protocol.cruise_config import parse_cruise_config


def test_parses_per_map_per_point():
    raw = (
        '[{"version":3,"settings":{"3":{"num":3,"ap":true}}},'
        '{"version":-1,"settings":{}}]'
    )
    out = parse_cruise_config(raw)
    assert out == {0: {3: {"cycles": 3, "auto_capture": True}}}


def test_accepts_already_parsed_list():
    raw = [{"version": 1, "settings": {"5": {"num": 1, "ap": False}}}]
    assert parse_cruise_config(raw) == {0: {5: {"cycles": 1, "auto_capture": False}}}


def test_skips_comma_key_and_bad_entries():
    raw = [{"version": 2, "settings": {
        "3": {"num": 2, "ap": True},
        "1,0": {"num": 1, "ap": True},
        "7": {"ap": True},
        "9": "garbage",
    }}]
    assert parse_cruise_config(raw) == {0: {3: {"cycles": 2, "auto_capture": True}}}


def test_tolerates_garbage():
    assert parse_cruise_config(None) == {}
    assert parse_cruise_config("not json") == {}
    assert parse_cruise_config("{}") == {}
    assert parse_cruise_config("[]") == {}
