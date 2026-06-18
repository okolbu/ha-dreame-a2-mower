# Fault catalog foundation (P0) — design

**Date:** 2026-06-18 · **Status:** approved, pre-implementation
**Program:** see `2026-06-18-fault-catalog-program-overview.md`.

## Goal
Bring the g2408 fault/notification catalog into the integration as a bundled,
regeneratable data asset with a clean pure-Python access API. **No entity/
behavior changes** — this is the shared foundation P1–P4 consume. Treat the
artifact as wire-authoritative (`[apk:g2408-plugin-ext1423]`).

## Components

### 1. Generator tool — `tools/inventory/gen_fault_catalog.py`
Transforms `artifacts/g2408-plugin-extract/tables/g2408_faults_localized.json`
into the bundled `custom_components/dreame_a2_mower/mower/data/fault_catalog.json`.
- Carries a `TOOL_META` block (tools/ convention) and regenerates the tools README.
- Per channel (`iot`, `heartbeat`), per code, emits:
  ```json
  {
    "fault_name": "FAULT_HUMAN_DETECTED",
    "category": "FAULT",                // = fault_name.split("_")[0] ∈ {FAULT,ALERT,INFO}
    "severity": "work_message",          // normalized messageType (see map)
    "can_suppress": true,                // bool(0/1)
    "lang": { "en": {"popup": "...", "alert": "...", "resident": "...",
                     "detail_title": "...", "detail": "..."}, "nb": {...}, ... }
  }
  ```
- Keeps ALL 21 langs and ALL five text fields (full fidelity — "all info lands").
- `severity` normalization map: `异常→anomaly`, `故障→malfunction`,
  `工作消息→work_message`, `耗材消息→consumable`, anything else / NaN → `unknown`.
- `detail`/`detail_title` text normalization: replace the literal `\\n` escape
  with a real newline (the source mixes `\n` and `\\n`); leave other text verbatim.
- Top-level `meta`: `{source, source_file, langs:[...], generated_note}`. NO
  timestamp (so regeneration is deterministic — the CI sync gate diffs bytes).
- `--check` mode: regenerate into memory and compare to the committed file;
  exit non-zero on any drift (the CI sync gate).

### 2. Bundled data — `custom_components/dreame_a2_mower/mower/data/fault_catalog.json`
The generator output, committed. Ships automatically with the package (HACS
ships the whole `custom_components/` tree). ~1 MB; loaded once.

### 3. Access module — `custom_components/dreame_a2_mower/mower/fault_catalog.py`
Pure Python, NO HA imports. Lazy-loads the JSON once (module-level cache).
Public API:
- `SUPPORTED_LANGS: frozenset[str]` — the 21 codes.
- `resolve_lang(ha_lang: str | None) -> str` — normalize a HA language to a
  catalog lang: exact match → it; strip region (`zh-Hans`→`zh`, `en-GB`→`en`) →
  match; else `"en"`.
- `fault_text(code: int, lang: str = "en", channel: str = "iot") -> str | None`
  — first-non-empty(`alert`, `popup`, `resident`) for `lang`; if the chosen
  language's fields are all empty/missing, fall back to `en`; then `None` if the
  code/channel is unknown.
- `fault_detail(code, lang="en", channel="iot") -> str | None` and
  `fault_detail_title(...)` — same lang-fallback.
- `fault_name(code, channel="iot") -> str | None`
- `fault_category(code, channel="iot") -> str | None`  (FAULT/ALERT/INFO)
- `fault_severity(code, channel="iot") -> str | None`
- `can_suppress(code, channel="iot") -> bool`  (False for unknown code)
- `known_codes(channel="iot") -> frozenset[int]`
Unknown code/channel → `None`/`False`/empty as appropriate (never raises).

### 4. CI sync gate — `tests/inventory/test_fault_catalog_sync.py`
- Runs the generator's `--check` (data ↔ generator in sync) — red on drift,
  with the regenerate command in the failure message.
- Asserts the bundled file parses and covers the wire-confirmed codes
  (`known_codes("iot")` ⊇ a pinned sample incl. 0, 4, 5, 27, 72).

### 5. Access-module unit tests — `tests/unit/test_fault_catalog.py`
- `fault_text(27, "en")` == the alert string; `fault_text(27, "nb")` == the
  Norwegian alert; `fault_text(0, "en")` uses popup (alert empty).
- `fault_text(27, "xx")` (unknown lang) → falls back to `en`.
- `fault_text(9999)` → `None`.
- `resolve_lang("nb")`=="nb"; `resolve_lang("zh-Hans")`=="zh";
  `resolve_lang("ja")`=="en"; `resolve_lang(None)`=="en".
- `fault_name(27)`=="FAULT_HUMAN_DETECTED"; `fault_category(27)`=="FAULT";
  `fault_category(72)`=="INFO"; `can_suppress(27)` is True; `fault_severity(72)`=="work_message".
- `fault_detail(0,"en")` contains the solution text with real newlines (no `\\n`).

## Data flow
artifact JSON → generator (add category, normalize severity + detail newlines) →
bundled `fault_catalog.json` → `fault_catalog.py` lazy-load → helper lookups
(P1–P4 consume). The artifact stays the source of truth; the generator + CI gate
keep the bundled copy faithful and regeneratable.

## Non-goals (this phase)
- No entity/sensor/notification changes (P1–P4).
- No edits to `error_codes.py`, `S2P2_EVENT_TYPES`, `FAULT_CODES`, or the
  confidence gate (P1/P2).
- No language plumbing from HA (`hass.config.language`) — the access module takes
  an explicit `lang`; the HA wiring lands in P1.

## Testing
Generator `--check` determinism (regenerate twice → identical); access helpers
(above); CI sync gate; bundled-file coverage of wire-confirmed codes.

## Verification
`gen_fault_catalog.py --check` is green; `import fault_catalog; fault_text(72,"nb")`
returns the Norwegian string. (No live HA needed — P0 ships no behavior.)
