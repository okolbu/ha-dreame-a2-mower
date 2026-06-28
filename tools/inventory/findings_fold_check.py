#!/usr/bin/env python3
"""Fold-time check: are the wire facts in the ACTIVE FINDING docs in inventory yet?

Dev-box only. Scans the ACTIVE (un-archived) capture findings — a new session's
``findings/`` dir plus top-level ``FINDING-*.md`` in the parent tree — and flags
any whose distinctive wire identifiers (endpoint paths / camelCase API names,
routed-action opcodes ``o=N``, routed ``t=KEY`` keys, ``sNpM`` properties) are
ABSENT from ``inventory.yaml`` + ``entity-inventory.yaml``.

WHY: findings arrive from the MITM rig (often another server) and the fold into
inventory is a manual, deferred step. When the fold is skipped or half-done, the
integration code can ship ahead of the protocol SoT (the getDeiviceFile / OTA /
schedule drift class). Run this when processing findings from a new capture,
BEFORE archiving those docs to OLD/ — per the documentation-canonicity rule:
fold first, then move out of tree.

IT DELIBERATELY DOES NOT SCAN ``OLD/``. Those docs are folded + archived; grepping
them as truth is the resurfacing-debunked-info failure this whole regime exists to
prevent. The tool only looks at the live queue.

A finding is EXEMPT (skipped) if its body contains a line matching
``FOLD-CHECK: exempt`` or a ``Status:`` line containing 'open' / 'unresolved' /
'UNVERIFIED' / 'not captured' — for intentionally-unfolded threads (e.g. the
getDeviceFile signer, BT-gated manual-drive/live-video).

Exit non-zero (with --strict) if any non-exempt finding has absent wire tokens.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PARENT = REPO.parent  # /data/claude/homeassistant
INVENTORY = REPO / "custom_components/dreame_a2_mower/inventory.yaml"
ENTITY_INVENTORY = REPO / "custom_components/dreame_a2_mower/entity-inventory.yaml"

TOOL_META = {
    "domain": "inventory",
    "run_by": "owner",
    "when": "When processing FINDING docs from a new capture/MITM session, before "
            "archiving them to OLD/ — verifies their wire facts reached inventory.yaml.",
    "summary": "Flag ACTIVE finding docs whose wire identifiers (endpoints/opcodes/"
               "t-keys/sNpM) are not yet in inventory (the OTA/getDeiviceFile drift guard).",
}

# Active finding locations (NEVER OLD/). Globs are relative to PARENT.
ACTIVE_GLOBS = [
    "cloud/captures/*/findings/*.md",
    "FINDING-*.md",
    "artifacts/*/FINDING-*.md",
]

EXEMPT_RE = re.compile(
    r"FOLD-CHECK:\s*exempt|\bUNVERIFIED\b|\bfail-?closed\b|"
    r"response\s+NOT\s+captured|not\s+yet\s+captured|still\s+(open|uncaptured)|"
    r"Status:[^\n]*(open|unresolved|in review|TODO)",
    re.IGNORECASE,
)

# Precise wire identifiers only — extracted from WIRE-CONTEXT lines (HTTP calls,
# routed actions), never from prose. Precision over recall: catch a clearly-named
# unfolded endpoint/key, never cry wolf on every camelCase word.
WIRE_LINE = re.compile(
    r"POST |GET |://|:13267|iotuserbind|iotfile|file-bridge|sendCommand|"
    r"action\(|\{\s*[\"']?m[\"']?\s*[=:]|\bt\s*[=:]\s*[\"']?[A-Z]|\bo\s*[=:]\s*\d",
    re.IGNORECASE,
)
# A line carrying an actual API URL (so endpoint verbs come from real endpoints,
# not source-file paths in build/tooling docs).
URL_LINE = re.compile(r"://|:13267|iotuserbind|iotfile|file-bridge|/dreame-")
# endpoint verb = last camelCase segment of an API path (/.../<verb>)
ENDPOINT = re.compile(r"/(?:[\w-]+/)*([a-z][a-zA-Z]*[A-Z][a-zA-Z]+)\b")
OPCODE = re.compile(r"\bo\s*[=:]\s*(\d{1,3})\b")
TKEY = re.compile(r"\bt\s*[=:]\s*[\"']?([A-Z][A-Z0-9_]{1,12})\b")
PROP = re.compile(r"\bs\d{1,2}p\d{1,3}\b")

# Generic transport verbs that are always present — never a "fold" signal.
STOPWORDS = {
    "getDeviceData", "setDeviceData", "getBatchDeviceDatas", "setBatchDeviceDatas",
    "sendCommand", "getProperties", "setProperties", "getDownloadUrl",
}


def extract_tokens(text: str) -> set[str]:
    toks: set[str] = set()
    for line in text.splitlines():
        if not WIRE_LINE.search(line):
            continue
        if URL_LINE.search(line):  # endpoint verbs only from real API-URL lines
            toks |= {m.group(1) for m in ENDPOINT.finditer(line)}
        toks |= {"o=" + m.group(1) for m in OPCODE.finditer(line)}
        toks |= {"t=" + m.group(1) for m in TKEY.finditer(line)}
        toks |= {m.group(0) for m in PROP.finditer(line)}
    return {t for t in toks if t not in STOPWORDS and len(t) >= 3}


def present(token: str, hay: str) -> bool:
    if token.startswith("o="):
        n = token[2:]
        # opcode present if "o=N" / "o:N" / "routed_o.*N" / op==N appears
        return bool(re.search(rf"o\s*[=:]\s*{n}\b|routed_o[^\n]*\b{n}\b|op[^\n]*==\s*{n}\b", hay))
    if token.startswith("t="):
        key = token[2:]
        return bool(re.search(rf'\b{re.escape(key)}\b', hay))
    return token in hay  # camelCase / path / sNpM are case-sensitive distinctive


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--parent", default=str(PARENT), help="tree root holding the active findings")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any non-exempt finding has absent tokens")
    ap.add_argument("--min-absent", type=int, default=1, help="flag a finding if >= this many key tokens are absent")
    args = ap.parse_args(argv)

    parent = Path(args.parent)
    # SoT files a finding's wire facts may legitimately fold into: the two
    # inventories + the bundled fault catalog (the authoritative fault-text SoT,
    # per CLAUDE.md). Integration CODE is deliberately NOT a fold target — the
    # getDeiviceFile drift was code-present-but-SoT-absent, exactly what we catch.
    sot = [INVENTORY, ENTITY_INVENTORY,
           REPO / "custom_components/dreame_a2_mower/mower/data/fault_catalog.json"]
    hay = "\n".join(p.read_text(encoding="utf-8") for p in sot if p.exists())

    findings: list[Path] = []
    for g in ACTIVE_GLOBS:
        findings += [p for p in parent.glob(g) if "/OLD/" not in str(p)]
    findings = sorted(set(findings))

    flagged = []
    for f in findings:
        text = f.read_text(encoding="utf-8", errors="replace")
        if EXEMPT_RE.search(text):
            continue
        toks = extract_tokens(text)
        absent = sorted(t for t in toks if not present(t, hay))
        if len(absent) >= args.min_absent:
            flagged.append((f, absent))

    print(f"scanned {len(findings)} active finding docs (OLD/ excluded)")
    if not flagged:
        print("ok: every active finding's wire identifiers are present in inventory.")
        return 0
    print(f"\n⚠ {len(flagged)} finding(s) with wire identifiers NOT in inventory "
          f"(possibly un-folded — fold before archiving to OLD/):\n")
    for f, absent in flagged:
        rel = f.relative_to(parent)
        print(f"  {rel}")
        print(f"      absent: {', '.join(absent[:12])}{' …' if len(absent) > 12 else ''}")
        print("      → fold the wire facts into inventory.yaml, or add a 'FOLD-CHECK: exempt'"
              " / 'Status: open' line if intentionally unfolded.")
    return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
