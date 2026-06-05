"""get_interim_file_url short-circuits on an empty object_name (no cloud round
trip, no WARNING — the cloud would reply error 40020)."""
from __future__ import annotations

from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient


def test_empty_object_name_returns_none_without_api_call():
    c = DreameA2CloudClient.__new__(DreameA2CloudClient)
    # _api_call would AttributeError on this bare instance — proving the guard
    # returns before any transport call.
    assert c.get_interim_file_url("") is None
    assert c.get_interim_file_url() is None
