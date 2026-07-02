"""CI golden gate: the committed corpus excerpt must replay to the
blessed digest. A mismatch means decode/state semantics changed — either
a regression (fix it) or an intentional change (re-bless:
`python -m tools.replay.corpus_replay --corpus-dir tests/fixtures/corpus
 --glob 'replay_excerpt.jsonl' --out tests/fixtures/corpus/replay_excerpt.golden.json`
and justify in the commit message)."""
from __future__ import annotations

import json
from pathlib import Path

from tools.replay.corpus_replay import digest_diff, replay

_FIX = Path(__file__).parent.parent / "fixtures" / "corpus"
_EXCERPT = _FIX / "replay_excerpt.jsonl"
_GOLDEN = _FIX / "replay_excerpt.golden.json"


def test_excerpt_replays_to_golden():
    digest = replay([_EXCERPT])
    golden = json.loads(_GOLDEN.read_text())
    assert digest_diff(golden, digest) == []


def test_excerpt_is_sanitized_and_meaningful():
    text = _EXCERPT.read_text()
    golden = json.loads(_GOLDEN.read_text())
    # sanitizer replaced the real device id everywhere
    assert "SANITIZED" in text
    # excerpt exercises a real mow: heartbeats + task-state + telemetry
    for slot in ("s1p1", "s2p1", "s1p4"):
        assert golden["per_slot"].get(slot, {"count": 0})["count"] > 0, slot
    assert golden["sm_transitions"] > 10
