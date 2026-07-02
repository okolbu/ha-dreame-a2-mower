"""CI golden gate: every committed corpus excerpt must replay to its
blessed digest. A mismatch means decode/state semantics changed — either
a regression (fix it) or an intentional change (re-bless the ONE excerpt
that changed:
`python -m tools.replay.corpus_replay --corpus-dir tests/fixtures/corpus
 --glob '<name>.jsonl' --out tests/fixtures/corpus/<name>.golden.json`
and justify in the commit message).

Excerpts are sanitized windows of real probe-log wire traffic (R-59/OQ-3),
each chosen to maximize NEW slot/value diversity vs. the others:

- replay_excerpt: plain full mow (2026-05-20 20:40-21:26) — s1p1/s1p4/
  s2p1/s3p1/s3p2 heavy heartbeat+telemetry baseline.
- replay_excerpt_settings: settings-write echo window
  (probe_log_20260608_193515.jsonl, 2026-06-09 17:00-19:00) — s2p51
  multiplexed_config heavy (98 pushes), including the undecoded
  {'type': 0|1} and {'result': 0, 'time': 0} payload shapes (both trigger a
  [NOVEL/property] decode-failed warning on replay — expected, documents
  the gap rather than hiding it).
- replay_excerpt_faults: fault/notification-dense window
  (probe_log_20260419_130434.jsonl, 2026-04-30 18:30-20:30) — 9 distinct
  s2p2 values in ~2h, including the rain-protection code (56).
- replay_excerpt_task_envelope: TASK envelope traffic
  (probe_log_20260419_130434.jsonl, 2026-04-26 20:30-22:00) — heavy s2p50
  (map-edit CRUD: save-geometry o=234, delete o=218, confirm o=201/204,
  abort o=-1) and s2p56 (task_state) multiplexed pushes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.replay.corpus_replay import digest_diff, replay

_FIX = Path(__file__).parent.parent / "fixtures" / "corpus"

# Per-excerpt "this excerpt actually exercises its theme" expectations:
# stem -> {per_slot key -> minimum count the blessed golden must exceed}.
_THEME_SLOT_MINIMUMS: dict[str, dict[str, int]] = {
    "replay_excerpt": {"s1p1": 0, "s2p1": 0, "s1p4": 0},  # baseline full mow
    "replay_excerpt_settings": {"s2p51": 0, "s2p50": 0},  # settings-write echoes
    "replay_excerpt_faults": {"s2p2": 5},  # fault-dense (9 distinct values incl. rain)
    "replay_excerpt_task_envelope": {"s2p50": 0, "s2p56": 0},  # TASK envelopes
}


def _excerpt_pairs() -> list[tuple[str, Path, Path]]:
    pairs = []
    for jsonl in sorted(_FIX.glob("replay_excerpt*.jsonl")):
        golden = jsonl.with_suffix("").with_suffix(".golden.json")
        pairs.append((jsonl.stem, jsonl, golden))
    return pairs


_PAIRS = _excerpt_pairs()
_IDS = [stem for stem, _, _ in _PAIRS]


@pytest.mark.parametrize("stem,excerpt,golden_path", _PAIRS, ids=_IDS)
def test_excerpt_replays_to_golden(stem, excerpt, golden_path):
    assert golden_path.exists(), f"missing golden for {excerpt.name}: {golden_path}"
    digest = replay([excerpt])
    golden = json.loads(golden_path.read_text())
    assert digest_diff(golden, digest) == []


@pytest.mark.parametrize("stem,excerpt,golden_path", _PAIRS, ids=_IDS)
def test_excerpt_is_sanitized(stem, excerpt, golden_path):
    text = excerpt.read_text()
    # sanitizer replaced the real device id everywhere it appeared
    assert "SANITIZED" in text


@pytest.mark.parametrize("stem,excerpt,golden_path", _PAIRS, ids=_IDS)
def test_excerpt_is_meaningful(stem, excerpt, golden_path):
    golden = json.loads(golden_path.read_text())
    thresholds = _THEME_SLOT_MINIMUMS[stem]
    for slot, minimum in thresholds.items():
        count = golden["per_slot"].get(slot, {"count": 0})["count"]
        assert count > minimum, f"{stem}: {slot} count {count} !> {minimum}"
    assert golden["sm_transitions"] > 10, stem


def test_all_fixture_excerpts_have_theme_expectations():
    """Guard against a fixture being added without a theme-slot expectation."""
    assert set(_IDS) == set(_THEME_SLOT_MINIMUMS), (
        "add a _THEME_SLOT_MINIMUMS entry for every replay_excerpt*.jsonl fixture"
    )
