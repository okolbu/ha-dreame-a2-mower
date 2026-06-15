from custom_components.dreame_a2_mower.const import (
    CONF_MESSAGES_KEEP,
    DEFAULT_MESSAGES_KEEP,
)
from custom_components.dreame_a2_mower.config_flow import DreameA2MowerOptionsFlow


class _FakeEntry:
    options: dict = {}


def _flow():
    flow = DreameA2MowerOptionsFlow()
    flow.config_entry = _FakeEntry()  # type: ignore[attr-defined]
    return flow


def test_default_messages_keep_is_100():
    assert DEFAULT_MESSAGES_KEEP == 100


def test_schema_includes_messages_keep_with_default():
    schema = _flow()._build_schema()
    markers = {str(k): k for k in schema.schema}
    assert CONF_MESSAGES_KEEP in markers
    assert markers[CONF_MESSAGES_KEEP].default() == DEFAULT_MESSAGES_KEEP
