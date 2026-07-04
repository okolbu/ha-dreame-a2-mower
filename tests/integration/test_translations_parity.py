"""strings.json <-> translations/en.json parity (R-46 / T4-7).

For a custom integration with English-only translations, ``strings.json``
(the authored source) and ``translations/en.json`` (what HA's runtime
translation loader actually reads) should be byte-identical — any drift
between them means someone edited one file and not the other, and the next
hand-authored key silently never reaches a real HA instance (or vice versa:
a dead orphan lingers in en.json referencing an entity that no longer needs
it). T4-7 found a 40-key drift plus a debunked ``obstacle_detected`` (D16)
remnant; this test is the guard so it can't recur silently.
"""
from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2] / "custom_components" / "dreame_a2_mower"


def _load(rel: str) -> dict:
    return json.loads((_ROOT / rel).read_text(encoding="utf-8"))


def test_strings_and_en_json_are_identical():
    strings = _load("strings.json")
    en = _load("translations/en.json")
    assert strings == en, (
        "strings.json and translations/en.json have drifted — for this "
        "English-only custom integration they must stay byte-identical "
        "(see CLAUDE.md / R-46)."
    )
