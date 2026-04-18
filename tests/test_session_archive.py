"""Tests for custom_components.dreame_a2_mower.session_archive."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from session_archive import ArchivedSession, INDEX_NAME, SessionArchive
from protocol.session_summary import parse_session_summary


FIXTURE_PATH = (
    Path(__file__).parent / "protocol" / "fixtures" / "session_summary_2026-04-18.json"
)


@pytest.fixture
def raw_json() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


@pytest.fixture
def summary(raw_json):
    return parse_session_summary(raw_json)


def test_fresh_archive_is_empty(tmp_path):
    a = SessionArchive(tmp_path)
    assert a.count == 0
    assert a.latest() is None
    assert a.list_sessions() == []


def test_archive_writes_file_and_index(tmp_path, summary, raw_json):
    a = SessionArchive(tmp_path)
    entry = a.archive(summary, raw_json=raw_json)

    assert entry is not None
    assert a.count == 1
    file_path = tmp_path / entry.filename
    assert file_path.exists()
    # Wire payload preserved verbatim.
    assert json.loads(file_path.read_text()) == raw_json
    # Index lists the entry.
    idx = json.loads((tmp_path / INDEX_NAME).read_text())
    assert idx["version"] == 1
    assert len(idx["sessions"]) == 1
    assert idx["sessions"][0]["md5"] == summary.md5


def test_filename_shape(tmp_path, summary, raw_json):
    a = SessionArchive(tmp_path)
    entry = a.archive(summary, raw_json=raw_json)
    # Expected: YYYY-MM-DD_<end_ts>_<md5_prefix>.json
    parts = entry.filename.removesuffix(".json").split("_")
    assert len(parts) == 3
    assert parts[0].count("-") == 2           # date
    assert parts[1].isdigit()                  # end_ts
    assert parts[2] == summary.md5[:8]


def test_archive_is_idempotent_by_md5(tmp_path, summary, raw_json):
    a = SessionArchive(tmp_path)
    first = a.archive(summary, raw_json=raw_json)
    second = a.archive(summary, raw_json=raw_json)
    assert first is not None
    assert second is None
    assert a.count == 1


def test_latest_returns_highest_end_ts(tmp_path):
    a = SessionArchive(tmp_path)

    class S:
        def __init__(self, md5, end_ts):
            self.md5 = md5
            self.end_ts = end_ts
            self.start_ts = end_ts - 100
            self.duration_min = 1
            self.area_mowed_m2 = 1.0
            self.map_area_m2 = 100
            self.mode = 0
            self.result = 0
            self.stop_reason = 0
            self.start_mode = 0
            self.pre_type = 0
            self.dock = None

    a.archive(S("hash-a", 1000))
    a.archive(S("hash-b", 3000))
    a.archive(S("hash-c", 2000))
    assert a.latest().md5 == "hash-b"
    assert [s.md5 for s in a.list_sessions()] == ["hash-b", "hash-c", "hash-a"]


def test_loads_existing_index_on_reopen(tmp_path, summary, raw_json):
    a1 = SessionArchive(tmp_path)
    a1.archive(summary, raw_json=raw_json)
    # New instance should see the persisted session.
    a2 = SessionArchive(tmp_path)
    assert a2.count == 1
    assert a2.latest().md5 == summary.md5


def test_corrupt_index_is_tolerated(tmp_path):
    (tmp_path / INDEX_NAME).write_text("{not valid json")
    a = SessionArchive(tmp_path)
    assert a.count == 0  # no crash, just empty


def test_load_returns_raw_json(tmp_path, summary, raw_json):
    a = SessionArchive(tmp_path)
    entry = a.archive(summary, raw_json=raw_json)
    loaded = a.load(entry)
    assert loaded == raw_json


def test_load_missing_file_returns_none(tmp_path):
    a = SessionArchive(tmp_path)
    entry = ArchivedSession(
        filename="no-such-file.json",
        start_ts=0, end_ts=0, duration_min=0, area_mowed_m2=0.0,
        map_area_m2=0, md5="",
    )
    assert a.load(entry) is None


def test_archive_without_raw_json_falls_back(tmp_path, summary):
    a = SessionArchive(tmp_path)
    entry = a.archive(summary, raw_json=None)
    loaded = a.load(entry)
    # Fallback reconstruction contains the scalar fields with a note.
    assert loaded["md5"] == summary.md5
    assert "_note" in loaded
