"""CI gate: every s2p2 code that error_codes.py describes must be backed by an
inventory state_codes row with decoded ∈ {confirmed, partial}. A code that is
hypothesized/unknown/missing in the inventory must NOT carry a confident name
in the code. This stops apk/vacuum-lineage names from creeping back."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2] / "custom_components" / "dreame_a2_mower"


def _state_code_confidence() -> dict[int, str]:
    inv = yaml.safe_load((ROOT / "inventory.yaml").read_text())
    out: dict[int, str] = {}

    def walk(o):
        if isinstance(o, dict):
            rid = o.get("id")
            if isinstance(rid, str):
                m = re.fullmatch(r"s2p2_(\d+)", rid)
                if m:
                    dec = o.get("decoded") or (o.get("status") or {}).get("decoded")
                    out[int(m.group(1))] = dec
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(inv)
    return out


def _described_codes(var: str) -> list[int]:
    src = (ROOT / "mower" / "error_codes.py").read_text()
    # Anchor on the dict ASSIGNMENT (`<VAR>: dict[int, str] = {`), not any
    # earlier comment/docstring mention of the name (e.g. a comment inside
    # ERROR_CODE_DESCRIPTIONS references S2P2_EVENT_TYPES).
    body = src.split(f"\n{var}: dict", 1)[1]
    body = re.split(r"\ndef |\nS2P2_UNKNOWN_EVENT_TYPE", body)[0]
    return sorted(int(x) for x in re.findall(r"^\s+(\d+):", body, re.M))


def test_described_s2p2_codes_are_confirmed_or_partial():
    conf = _state_code_confidence()
    offenders: dict[int, str | None] = {}
    for var in ("ERROR_CODE_DESCRIPTIONS", "S2P2_EVENT_TYPES"):
        for code in _described_codes(var):
            if conf.get(code) not in ("confirmed", "partial"):
                offenders.setdefault(code, conf.get(code))
    assert not offenders, (
        "error_codes.py describes s2p2 codes that the inventory does NOT back "
        "as confirmed/partial — either add wire/cloud evidence to "
        "inventory.yaml state_codes (s2p2_<code>) or remove the description. "
        f"Offenders {{code: inventory_status}}: {offenders}"
    )


def test_gate_parses_full_s2p2_event_types_table():
    # Guards the parser anchor: code 33 lives ONLY in S2P2_EVENT_TYPES (not in
    # ERROR_CODE_DESCRIPTIONS). If the slice anchored on a comment mention it
    # would miss it. These must be present in the parsed table.
    codes = _described_codes("S2P2_EVENT_TYPES")
    for c in (0, 5, 33, 50):
        assert c in codes, f"parser missed S2P2_EVENT_TYPES code {c}: {codes}"
