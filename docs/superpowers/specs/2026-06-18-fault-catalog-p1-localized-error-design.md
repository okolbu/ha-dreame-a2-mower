# Localized error display (P1) — design

**Date:** 2026-06-18 · **Status:** approved, pre-implementation
**Program:** `2026-06-18-fault-catalog-program-overview.md`. Builds on P0
(`mower/fault_catalog.py` + bundled `mower/data/fault_catalog.json`).

## Goal
The error sensor (and the other `describe_error` consumers) show the
**authoritative app wording in the user's HA language**, sourced from the P0
catalog. Fully retire the hand-curated `ERROR_CODE_DESCRIPTIONS`. First
user-visible phase — releases (P0 rides out here).

## Carry-forward from P0
`fault_catalog.fault_text(code, lang)` does NOT resolve the language itself.
Callers resolve once: `lang = fault_catalog.resolve_lang(hass.config.language)`,
then pass `lang`. Default `lang="en"` where no `hass` is in hand.

## Components

### A. `describe_error` → catalog-backed; retire `ERROR_CODE_DESCRIPTIONS`
`mower/error_codes.py`:
- Delete the `ERROR_CODE_DESCRIPTIONS` dict.
- Rewrite `describe_error(code: int, lang: str = "en") -> str` to:
  `return fault_catalog.fault_text(int(code), lang) or f"Unknown error {code}"`.
  (`error_codes.py` and `fault_catalog.py` are both layer-2 — import is clean.)
- Keep `S2P2_EVENT_TYPES` and `FAULT_CODES` unchanged (P2 regenerates them).
- A code absent from the catalog → `"Unknown error N"` (already surfaces via the
  `[PROTOCOL_NOVEL]` / `unknown_s2p2` paths). Catalog-only, per decision.

### B. Error sensor localized value + attributes
`entities/sensor/device.py`, the `key="error_description"` diagnostic descriptor:
- `_active_fault_text(snapshot, coord=None)`: resolve
  `lang = fault_catalog.resolve_lang(getattr(getattr(coord, "hass", None), "config", None) and coord.hass.config.language)`
  defensively (audit fakes have no hass → `lang="en"`); join
  `describe_error(c, lang)` over `sorted(snapshot.errors)`.
- `value_fn=lambda coord: _active_fault_text(coord.state_machine.snapshot(), coord)`.
- Add `extra_state_attributes_fn=lambda coord: _error_attrs(coord)` where
  `_error_attrs` returns, for the latched fault set (localized to the same lang):
  - `error_detail`: "; "-joined `fault_catalog.fault_detail(c, lang)` (skip None).
  - `fault_names`: sorted list of `fault_catalog.fault_name(c)` (language-neutral).
  - `categories`: sorted-unique list of `fault_catalog.fault_category(c)` (FAULT/ALERT/INFO).
  Empty/absent → omit keys or empty values; never raise (defensive on coord).

### C. Other `describe_error` consumers
- `entities/sensor/device.py:_describe_error_or_none(code)` → keep English
  (`describe_error(code)`); it feeds a raw-code description with no per-call lang
  context. (Localizing it is a nicety; out of scope unless trivial.)
- `coordinator/_device_sync.py` (emergency-stop banner, ~line 342-352): resolve
  `lang` from `self.hass.config.language` and call `describe_error(code, lang)` so
  the banner text is localized too.

### D. Confidence gate + tests
- `tests/inventory/test_error_codes_confidence_gate.py`: `ERROR_CODE_DESCRIPTIONS`
  no longer exists, so its `_described_codes("ERROR_CODE_DESCRIPTIONS")` call
  would crash. Remove `ERROR_CODE_DESCRIPTIONS` from the checked vars; keep the
  `S2P2_EVENT_TYPES` check (still gates that dict until P2). Update the docstring.
- `tests/mower/test_error_codes.py`: assertions on specific `describe_error`
  strings change to the catalog wording — update to assert via the catalog
  (`describe_error(27) == fault_catalog.fault_text(27, "en")`) rather than literals,
  and that an unknown code → `"Unknown error N"`.
- `tests/audit/test_fake_coord.py`: if it builds a fake coord that exercises the
  error sensor value_fn, ensure the fake has a `hass.config.language` or that the
  defensive `lang="en"` path keeps it green.

### E. Release + live-verify
After the suite is green, release via `tools/release/release.sh`, install, restart,
and confirm on live HA: with a recent fault, `sensor.dreame_a2_mower_error` shows
the localized app wording, `error_detail`/`fault_names`/`categories` attributes
are populated, and the language matches the HA UI language.

## Out of scope (later phases)
- Regenerating `S2P2_EVENT_TYPES` slugs + `FAULT_CODES` from the catalog (P2).
- Reconciling inventory `state_codes` *semantics* to the catalog meanings (P2).
- Notification event / logbook localization + category→trigger handling (P3).
- Heartbeat (s1p1) channel (P4).

## Testing
- `describe_error(27, "en")` == catalog text; `describe_error(27, "nb")` localized
  + differs from en; unknown code → `"Unknown error N"`.
- `_active_fault_text` with a fake coord exposing `hass.config.language="nb"` →
  Norwegian text; with no hass → English; multi-fault join; empty errors → None.
- `_error_attrs`: detail/fault_names/categories for a 2-fault snapshot.
- Confidence gate green (no `ERROR_CODE_DESCRIPTIONS` reference); full suite green.

## Verification
Live HA error sensor shows localized authoritative wording + the new attributes;
language follows `hass.config.language`.
