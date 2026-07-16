"""Tests for the novel-observation registry."""

from __future__ import annotations

from custom_components.dreame_a2_mower.observability.registry import (
    NovelObservation,
    NovelObservationRegistry,
)


def test_registry_starts_empty():
    reg = NovelObservationRegistry()
    snap = reg.snapshot()
    assert snap.count == 0
    assert snap.observations == []


def test_record_property_adds_observation():
    reg = NovelObservationRegistry()
    fired = reg.record_property(siid=99, piid=42, now_unix=1700000000)
    assert fired is True
    snap = reg.snapshot()
    assert snap.count == 1
    obs = snap.observations[0]
    assert obs.category == "property"
    assert obs.detail == "siid=99 piid=42"
    assert obs.first_seen_unix == 1700000000


def test_record_property_dedupes():
    reg = NovelObservationRegistry()
    assert reg.record_property(siid=99, piid=42, now_unix=1700000000) is True
    assert reg.record_property(siid=99, piid=42, now_unix=1700000005) is False
    assert reg.snapshot().count == 1


def test_record_value_for_known_property():
    reg = NovelObservationRegistry()
    fired = reg.record_value(siid=2, piid=2, value=99, now_unix=1700000000)
    assert fired is True
    obs = reg.snapshot().observations[0]
    assert obs.category == "value"
    assert "siid=2 piid=2" in obs.detail
    assert "value=99" in obs.detail


def test_record_key_uses_namespace():
    reg = NovelObservationRegistry()
    fired = reg.record_key(namespace="session_summary", key="weird_field", now_unix=1700000000)
    assert fired is True
    obs = reg.snapshot().observations[0]
    assert obs.category == "key"
    assert obs.detail == "session_summary.weird_field"


def test_observations_sorted_oldest_first():
    reg = NovelObservationRegistry()
    reg.record_property(siid=1, piid=1, now_unix=1700000010)
    reg.record_property(siid=2, piid=2, now_unix=1700000005)
    reg.record_property(siid=3, piid=3, now_unix=1700000020)
    seen = [o.first_seen_unix for o in reg.snapshot().observations]
    # Insertion order, NOT sorted-by-time. Matches "first sighting" semantics.
    assert seen == [1700000010, 1700000005, 1700000020]


import asyncio

import pytest

from custom_components.dreame_a2_mower.observability.novel_store import (
    PersistentNovelStore,
)


def test_attach_store_is_optional():
    """A registry without an attached store behaves exactly as today:
    record_* returns True/False based on watchdog state, no I/O happens."""
    reg = NovelObservationRegistry()
    assert reg.record_value(siid=2, piid=2, value=28, now_unix=1700000000) is True
    assert reg.record_value(siid=2, piid=2, value=28, now_unix=1700000100) is False


@pytest.mark.asyncio
async def test_attach_store_appends_on_novel(tmp_path):
    """After attach_store, every True return appends one line."""
    path = tmp_path / "novel_observations.jsonl"
    store = PersistentNovelStore(path)
    reg = NovelObservationRegistry()
    reg.attach_store(store)

    reg.record_value(siid=2, piid=2, value=28, now_unix=1700000000)
    reg.record_value(siid=2, piid=2, value=28, now_unix=1700000100)  # dup
    reg.record_value(siid=2, piid=2, value=70, now_unix=1700000200)

    # The append calls are fire-and-forget asyncio tasks; let the loop run.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert path.exists()
    lines = path.read_text().splitlines()
    assert len(lines) == 2  # two distinct values, the dup is filtered


@pytest.mark.asyncio
async def test_load_then_attach_does_not_re_echo(tmp_path):
    """load() runs BEFORE attach_store, so replayed entries don't write back."""
    path = tmp_path / "novel_observations.jsonl"
    path.write_text(
        '{"ts": 1, "category": "value", "siid": 6, "piid": 1, "value": 200}\n'
    )
    store = PersistentNovelStore(path)
    reg = NovelObservationRegistry()

    # 1. Load (no store attached yet — replays into watchdog only).
    n = await store.load(reg)
    assert n == 1

    # 2. Attach store.
    reg.attach_store(store)

    # 3. Trigger the same observation again — watchdog says non-novel,
    #    no append happens.
    fired = reg.record_value(siid=6, piid=1, value=200, now_unix=1700000000)
    assert fired is False
    await asyncio.sleep(0)

    # File still has its original single line — no echo.
    assert path.read_text().count("\n") == 1


# --- user-visible filtering (novel-observation flood suppression) ----------
#
# The registry records EVERY first-seen value for a mapped slot. For a
# continuous-int slot that is a flood: s3p1 battery_level fires once per new
# percentage (~100 entries), s5p107 energy_index up to the per-slot cap. That
# is a useful log/research signal but noise on the user-facing sensor, which
# is supposed to mean "unrecognised wire shapes worth a look".
#
# The split: a "value" observation is user-visible only if its slot HAS a
# value_catalog in the inventory — i.e. the firmware emitted a value the
# catalog does not enumerate (a real protocol gap). A slot with no catalog
# has no enumerable vocabulary, so "new value" says nothing.


def test_record_value_carries_structured_slot():
    # The filter needs the slot as data; parsing it back out of `detail`
    # would couple the sensor to a human-readable string's format.
    reg = NovelObservationRegistry()
    reg.record_value(siid=3, piid=1, value=57, now_unix=1700000000)
    obs = reg.snapshot().observations[0]
    assert (obs.siid, obs.piid) == (3, 1)


def test_visible_observations_drops_uncatalogued_value_flood():
    from custom_components.dreame_a2_mower.observability.registry import (
        visible_observations,
    )
    # s3p1 (battery_level) has no value_catalog -> flood, hidden.
    obs = [
        NovelObservation(category="value", detail="siid=3 piid=1 value=57",
                         first_seen_unix=1, siid=3, piid=1),
        NovelObservation(category="value", detail="siid=3 piid=1 value=58",
                         first_seen_unix=2, siid=3, piid=1),
    ]
    assert visible_observations(obs) == []


def test_visible_observations_keeps_catalog_miss():
    from custom_components.dreame_a2_mower.observability.registry import (
        visible_observations,
    )
    # s1p2 (ota_state) HAS a value_catalog -> an unenumerated value is a real
    # protocol gap and must stay visible.
    obs = [
        NovelObservation(category="value", detail="siid=1 piid=2 value=99",
                         first_seen_unix=1, siid=1, piid=2),
    ]
    assert visible_observations(obs) == obs


def test_visible_observations_keeps_non_value_categories():
    from custom_components.dreame_a2_mower.observability.registry import (
        visible_observations,
    )
    # An unmapped slot / unknown event / unknown blob key is ALWAYS actionable
    # regardless of catalogs — that's the signal the sensor exists for.
    obs = [
        NovelObservation(category="property", detail="siid=99 piid=42",
                         first_seen_unix=1, siid=99, piid=42),
        NovelObservation(category="event", detail="siid=9 eiid=1 piids=[]",
                         first_seen_unix=2),
        NovelObservation(category="key", detail="summary.mystery_field",
                         first_seen_unix=3),
    ]
    assert visible_observations(obs) == obs


def test_visible_observations_keeps_value_with_unknown_slot():
    from custom_components.dreame_a2_mower.observability.registry import (
        visible_observations,
    )
    # Defensive: an observation with no slot recorded cannot be proven to be
    # a flood, so it must NOT be silently hidden.
    obs = [NovelObservation(category="value", detail="legacy", first_seen_unix=1)]
    assert visible_observations(obs) == obs
