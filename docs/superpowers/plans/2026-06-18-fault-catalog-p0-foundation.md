# Fault catalog foundation (P0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bundle the g2408 fault/notification catalog (both channels · 21 languages · all fields · FAULT/ALERT/INFO category · severity · can_suppress) into the integration as a generated JSON, with a pure access API and validation gates — no entity/behavior changes.

**Architecture:** A `tools/inventory/gen_fault_catalog.py` generator (pure `build_catalog()` + CLI) transforms the app-extracted artifact into `custom_components/dreame_a2_mower/mower/data/fault_catalog.json`. A pure `mower/fault_catalog.py` lazy-loads it and exposes lookup helpers. CI gates: a unit test of the transform on a fixture + a structural validation of the shipped file.

**Tech Stack:** Python (pure stdlib `json`); vanilla-pytest venv at `/data/claude/homeassistant/.venv-vanilla/bin/python`.

**Test command:** `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest <path> -q`. System python3 is broken. Stage by EXPLICIT path; never `git add -A` (untracked `tools/probes/oss_*` are NOT ours).

**Source artifact (dev box, outside repo):** `/data/claude/homeassistant/artifacts/g2408-plugin-extract/tables/g2408_faults_localized.json` — shape `{channel: {code: {fault_name, messageType, can_suppress, lang: {<lang>: {popup, alert, resident, detailTitle, detail}}}}}`, channels `iot` (69 codes) + `heartbeat` (45). Treat as wire-authoritative `[apk:g2408-plugin-ext1423]`.

---

### Task 1: Generator tool + bundled data file

**Files:**
- Create: `tools/inventory/gen_fault_catalog.py`
- Create (generated): `custom_components/dreame_a2_mower/mower/data/fault_catalog.json`
- Modify (generated): `tools/README.md`
- Test: `tests/inventory/test_gen_fault_catalog.py`

- [ ] **Step 1: Write the failing test (pure transform)**

Create `tests/inventory/test_gen_fault_catalog.py`:

```python
from tools.inventory.gen_fault_catalog import build_catalog


def _fixture():
    return {
        "iot": {
            "27": {"fault_name": "FAULT_HUMAN_DETECTED", "messageType": "工作消息",
                   "can_suppress": 1, "lang": {
                       "en": {"popup": "", "alert": "Human entry detected.",
                              "resident": "Human presence detected.",
                              "detailTitle": "Human", "detail": "step1\\nstep2"},
                       "nb": {"popup": "", "alert": "Menneske oppdaget.",
                              "resident": "", "detailTitle": "", "detail": ""}}},
            "0": {"fault_name": "FAULT_HANGING", "messageType": "异常",
                  "can_suppress": 0, "lang": {
                      "en": {"popup": "Robot lifted.", "alert": "",
                             "resident": "Robot lifted.", "detailTitle": "Lifted",
                             "detail": "a"}}},
        },
        "heartbeat": {},
    }


def test_build_catalog_transforms():
    cat = build_catalog(_fixture())
    e = cat["iot"]["27"]
    assert e["fault_name"] == "FAULT_HUMAN_DETECTED"
    assert e["category"] == "FAULT"                 # prefix
    assert e["severity"] == "work_message"          # 工作消息 normalized
    assert e["can_suppress"] is True
    assert e["lang"]["en"]["detail"] == "step1\nstep2"  # \\n -> real newline
    assert e["lang"]["nb"]["alert"] == "Menneske oppdaget."
    assert cat["iot"]["0"]["severity"] == "anomaly"   # 异常
    assert cat["meta"]["langs"] == ["en", "nb"]       # sorted union
    assert "heartbeat" in cat


def test_build_catalog_unknown_severity_is_unknown():
    fx = {"iot": {"9": {"fault_name": "INFO_X", "messageType": None,
                        "can_suppress": 0, "lang": {}}}, "heartbeat": {}}
    cat = build_catalog(fx)
    assert cat["iot"]["9"]["severity"] == "unknown"
    assert cat["iot"]["9"]["category"] == "INFO"
```

- [ ] **Step 2: Run, verify FAIL**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory/test_gen_fault_catalog.py -q`
Expected: FAIL — module/function missing.

- [ ] **Step 3: Write the generator**

Create `tools/inventory/gen_fault_catalog.py`:

```python
"""Generate the bundled g2408 fault/notification catalog from the app extract.

Transforms artifacts/g2408-plugin-extract/.../g2408_faults_localized.json into
custom_components/dreame_a2_mower/mower/data/fault_catalog.json — adding the
FAULT/ALERT/INFO `category` (fault_name prefix), a normalized `severity`, and
real newlines in detail text. Run with no args to (re)write the bundled file;
--check (dev-box, needs the artifact) compares without writing.
"""
from __future__ import annotations

import json
from pathlib import Path

TOOL_META = {
    "domain": "inventory",
    "run_by": "owner",
    "when": "When the g2408 plugin extract updates; regenerates the bundled fault catalog.",
    "summary": "Generate mower/data/fault_catalog.json (21-lang fault/notification strings) from the app extract.",
}

ARTIFACT = Path("/data/claude/homeassistant/artifacts/g2408-plugin-extract/tables/g2408_faults_localized.json")
OUT = Path(__file__).resolve().parents[2] / "custom_components/dreame_a2_mower/mower/data/fault_catalog.json"

_SEVERITY = {
    "异常": "anomaly", "故障": "malfunction",
    "工作消息": "work_message", "耗材消息": "consumable",
}


def _norm(s) -> str:
    return s.replace("\\n", "\n") if isinstance(s, str) else (s or "")


def build_catalog(localized: dict) -> dict:
    """Pure transform: extract JSON -> bundled catalog dict."""
    out: dict = {"meta": {
        "source": "g2408-plugin-extract ext1423 ver534 [apk:g2408-plugin-ext1423]",
        "source_file": "artifacts/g2408-plugin-extract/tables/g2408_faults_localized.json",
        "note": "GENERATED by tools/inventory/gen_fault_catalog.py — do not hand-edit",
    }}
    langs: set[str] = set()
    for channel in ("iot", "heartbeat"):
        ch = localized.get(channel) or {}
        out_ch: dict = {}
        for code, e in ch.items():
            fn = e.get("fault_name") or ""
            lang_out: dict = {}
            for lg, f in (e.get("lang") or {}).items():
                langs.add(lg)
                lang_out[lg] = {
                    "popup": f.get("popup") or "",
                    "alert": f.get("alert") or "",
                    "resident": f.get("resident") or "",
                    "detail_title": _norm(f.get("detailTitle")),
                    "detail": _norm(f.get("detail")),
                }
            out_ch[str(code)] = {
                "fault_name": fn,
                "category": fn.split("_")[0] if fn else "",
                "severity": _SEVERITY.get(e.get("messageType"), "unknown"),
                "can_suppress": bool(e.get("can_suppress")),
                "lang": lang_out,
            }
        out[channel] = out_ch
    out["meta"]["langs"] = sorted(langs)
    return out


def _render(catalog: dict) -> str:
    return json.dumps(catalog, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":  # pragma: no cover — CLI / dev I/O
    import argparse
    import sys

    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="compare regen vs committed (needs the artifact); no write")
    args = ap.parse_args()

    built = _render(build_catalog(json.loads(ARTIFACT.read_text(encoding="utf-8"))))
    if args.check:
        cur = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if cur != built:
            print("DRIFT: bundled fault_catalog.json != regen — run "
                  "tools/inventory/gen_fault_catalog.py", file=sys.stderr)
            sys.exit(1)
        print("ok: fault_catalog.json in sync")
        sys.exit(0)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(built, encoding="utf-8")
    print(f"wrote {OUT} ({len(built)} bytes)")
```

- [ ] **Step 4: Run, verify PASS**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory/test_gen_fault_catalog.py -q`
Expected: PASS.

- [ ] **Step 5: Generate the bundled data file**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/gen_fault_catalog.py`
Expected: `wrote .../mower/data/fault_catalog.json (<N> bytes)`. Confirm it exists and parses:
`/data/claude/homeassistant/.venv-vanilla/bin/python -c "import json,pathlib; d=json.loads(pathlib.Path('custom_components/dreame_a2_mower/mower/data/fault_catalog.json').read_text()); print('iot', len(d['iot']), 'heartbeat', len(d['heartbeat']), 'langs', len(d['meta']['langs']))"`
Expected: `iot 69 heartbeat 45 langs 21`.

- [ ] **Step 6: Regenerate the tools README**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/gen_readme.py`
Then confirm the README sync test passes:
`/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/tools/test_readme_in_sync.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tools/inventory/gen_fault_catalog.py custom_components/dreame_a2_mower/mower/data/fault_catalog.json tools/README.md tests/inventory/test_gen_fault_catalog.py
git commit -m "feat(faults): generator + bundled g2408 fault catalog (21 langs, category/severity)"
```

---

### Task 2: Pure access module

**Files:**
- Create: `custom_components/dreame_a2_mower/mower/fault_catalog.py`
- Test: `tests/unit/test_fault_catalog.py`

- [ ] **Step 1: Write the failing tests** (against the real bundled file from Task 1)

Create `tests/unit/test_fault_catalog.py`:

```python
from custom_components.dreame_a2_mower.mower import fault_catalog as fc


def test_fault_text_picks_first_nonempty_and_localizes():
    # 27 = FAULT_HUMAN_DETECTED, alert filled (popup empty)
    assert fc.fault_text(27, "en").startswith("Human entry into the mapped area")
    assert fc.fault_text(27, "nb")  # a non-empty Norwegian string
    assert fc.fault_text(27, "nb") != fc.fault_text(27, "en")
    # 0 = FAULT_HANGING, popup filled (alert empty) → first-non-empty falls to popup
    assert fc.fault_text(0, "en")


def test_fault_text_unknown_lang_falls_back_to_en():
    assert fc.fault_text(27, "xx") == fc.fault_text(27, "en")


def test_fault_text_unknown_code_is_none():
    assert fc.fault_text(99999, "en") is None


def test_metadata_helpers():
    assert fc.fault_name(27) == "FAULT_HUMAN_DETECTED"
    assert fc.fault_category(27) == "FAULT"
    assert fc.fault_category(72) == "INFO"
    assert fc.can_suppress(27) is True
    assert fc.fault_severity(72) == "work_message"
    assert 27 in fc.known_codes("iot")
    assert fc.can_suppress(99999) is False


def test_detail_has_real_newlines():
    d = fc.fault_detail(0, "en")
    assert d and "\\n" not in d  # literal backslash-n must be gone


def test_resolve_lang():
    assert fc.resolve_lang("nb") == "nb"
    assert fc.resolve_lang("zh-Hans") == "zh"
    assert fc.resolve_lang("en-GB") == "en"
    assert fc.resolve_lang("ja") == "en"
    assert fc.resolve_lang(None) == "en"
    assert "en" in fc.SUPPORTED_LANGS and len(fc.SUPPORTED_LANGS) == 21
```

- [ ] **Step 2: Run, verify FAIL**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_fault_catalog.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Write the access module**

Create `custom_components/dreame_a2_mower/mower/fault_catalog.py`:

```python
"""Pure access API for the bundled g2408 fault/notification catalog.

Loads mower/data/fault_catalog.json once and exposes per-code lookups by
channel ("iot" = s2p2, "heartbeat" = s1p1) and language. No HA imports.
Source: the app plugin extract [apk:g2408-plugin-ext1423]; see
tools/inventory/gen_fault_catalog.py.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).parent / "data" / "fault_catalog.json"

SUPPORTED_LANGS: frozenset[str] = frozenset({
    "zh", "en", "de", "fr", "it", "es", "pt", "nl", "da", "sv", "fi",
    "pl", "nb", "ru", "tr", "lt", "cs", "lv", "sk", "hu", "ro",
})

_DISPLAY_FIELDS = ("alert", "popup", "resident")


@lru_cache(maxsize=1)
def _catalog() -> dict:
    try:
        return json.loads(_DATA.read_text(encoding="utf-8"))
    except Exception:
        return {"iot": {}, "heartbeat": {}}


def _entry(code: int, channel: str) -> dict | None:
    try:
        return (_catalog().get(channel) or {}).get(str(int(code)))
    except (TypeError, ValueError):
        return None


def resolve_lang(ha_lang: str | None) -> str:
    """Map a HA language to a catalog lang (region-stripped), else 'en'."""
    if not ha_lang:
        return "en"
    lg = str(ha_lang).lower()
    if lg in SUPPORTED_LANGS:
        return lg
    base = lg.split("-")[0]
    return base if base in SUPPORTED_LANGS else "en"


def _field(code: int, lang: str, channel: str, key: str) -> str | None:
    e = _entry(code, channel)
    if e is None:
        return None
    langs = e.get("lang") or {}
    for src in (lang, "en"):
        val = (langs.get(src) or {}).get(key)
        if val:
            return val
    return None


def fault_text(code: int, lang: str = "en", channel: str = "iot") -> str | None:
    """The display string: first-non-empty(alert, popup, resident), lang then en."""
    e = _entry(code, channel)
    if e is None:
        return None
    langs = e.get("lang") or {}
    for src in (lang, "en"):
        f = langs.get(src) or {}
        for k in _DISPLAY_FIELDS:
            if f.get(k):
                return f[k]
    return None


def fault_detail(code: int, lang: str = "en", channel: str = "iot") -> str | None:
    return _field(code, lang, channel, "detail")


def fault_detail_title(code: int, lang: str = "en", channel: str = "iot") -> str | None:
    return _field(code, lang, channel, "detail_title")


def fault_name(code: int, channel: str = "iot") -> str | None:
    e = _entry(code, channel)
    return e.get("fault_name") if e else None


def fault_category(code: int, channel: str = "iot") -> str | None:
    e = _entry(code, channel)
    return e.get("category") if e else None


def fault_severity(code: int, channel: str = "iot") -> str | None:
    e = _entry(code, channel)
    return e.get("severity") if e else None


def can_suppress(code: int, channel: str = "iot") -> bool:
    e = _entry(code, channel)
    return bool(e.get("can_suppress")) if e else False


def known_codes(channel: str = "iot") -> frozenset[int]:
    out: set[int] = set()
    for k in (_catalog().get(channel) or {}):
        try:
            out.add(int(k))
        except (TypeError, ValueError):
            continue
    return frozenset(out)
```

- [ ] **Step 4: Run, verify PASS**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_fault_catalog.py -q`
Expected: PASS. (If `test_fault_text_picks_first_nonempty_and_localizes` asserts the exact 27 English prefix and the real string differs slightly, adjust the assertion to the real bundled text — read it via `fc.fault_text(27, "en")`.)

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/mower/fault_catalog.py tests/unit/test_fault_catalog.py
git commit -m "feat(faults): pure fault_catalog access API (text/detail/name/category/severity by lang)"
```

---

### Task 3: Validation CI gate + full suite

**Files:**
- Test: `tests/inventory/test_fault_catalog_valid.py`

- [ ] **Step 1: Write the validation test**

Create `tests/inventory/test_fault_catalog_valid.py`:

```python
import json
from pathlib import Path

from custom_components.dreame_a2_mower.mower import fault_catalog as fc

_DATA = Path(fc.__file__).parent / "data" / "fault_catalog.json"
_CATEGORIES = {"FAULT", "ALERT", "INFO"}
_SEVERITIES = {"anomaly", "malfunction", "work_message", "consumable", "unknown"}


def test_bundled_file_parses_and_has_both_channels():
    d = json.loads(_DATA.read_text(encoding="utf-8"))
    assert d["iot"] and d["heartbeat"]
    assert len(d["meta"]["langs"]) == 21


def test_every_entry_well_formed():
    d = json.loads(_DATA.read_text(encoding="utf-8"))
    for channel in ("iot", "heartbeat"):
        for code, e in d[channel].items():
            assert e["fault_name"], f"{channel} {code} missing fault_name"
            assert e["category"] in _CATEGORIES, f"{channel} {code} category={e['category']}"
            assert e["severity"] in _SEVERITIES, f"{channel} {code} severity={e['severity']}"
            assert isinstance(e["can_suppress"], bool)
            assert "en" in e["lang"], f"{channel} {code} missing en"


def test_covers_wire_confirmed_codes():
    iot = fc.known_codes("iot")
    for c in (0, 4, 5, 27, 72):
        assert c in iot, f"iot code {c} missing from catalog"
        assert fc.fault_text(c, "en"), f"iot code {c} has no en display text"
```

- [ ] **Step 2: Run, verify PASS**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory/test_fault_catalog_valid.py -q`
Expected: PASS.

- [ ] **Step 3: Run the FULL suite**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q --ignore=tests/archive`
Expected: all pass (~2515 baseline + the new tests). The only new package file is the bundled JSON + the pure module + tests — no entity/audit coupling, so no audit-gate changes expected. Fix anything our additions broke (e.g. a "no stray files in mower/" style test, if any — unlikely).

- [ ] **Step 4: Commit**

```bash
git add tests/inventory/test_fault_catalog_valid.py
git commit -m "test(faults): structural validation gate for the bundled fault catalog"
```

- [ ] **Step 5: Note on release**

P0 ships NO behavior (pure data + access API, no consumer yet). Do NOT cut a dedicated release — it rides out with P1 (the first user-visible phase). Leave the commits on `main`; the controller decides when to push.

---

## Notes / gotchas
- Test interpreter: `/data/claude/homeassistant/.venv-vanilla/bin/python`. Stage by explicit path; leave untracked `tools/probes/oss_*` alone.
- The generator reads the dev-box artifact (`/data/claude/homeassistant/artifacts/...`); `--check` needs it present. CI does NOT run `--check` (artifact isn't in CI) — it validates the committed bundled file + unit-tests `build_catalog` on a fixture instead.
- The bundled `fault_catalog.json` is ~1 MB and ships with the package (HACS ships all of `custom_components/`). `mower/data/` is a new dir — the JSON in it ships automatically; no manifest change needed.
- `build_catalog` output is deterministic (`sort_keys=True`) so re-running the generator yields byte-identical output.
- P0 is foundation only — NO changes to `error_codes.py`, the error sensor, notifications, or any gate. Those are P1+.
