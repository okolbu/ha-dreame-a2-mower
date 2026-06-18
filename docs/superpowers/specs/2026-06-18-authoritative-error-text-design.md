# Authoritative error text from cloud notifications (todo7 #2) — design

**Date:** 2026-06-18 · **Status:** approved, pre-implementation

## Problem

`sensor.dreame_a2_mower_error` shows the short, curated `error_codes.py` string
(e.g. code 27 → "Human detected"), while the cloud notification carries the
authoritative app wording ("Human entry into the mapped area is detected. Please
be alert. View snapshots in the app."). The notification event and the logbook
already prefer the cloud text; the error sensor is the only consumer that
doesn't. The cloud text is already mapped by code in the existing
`_notif_text_cache: {(siid,piid,value) -> en_text}` (populated by both the boot
baseline and the reactive s2p2 resolver), but that cache is per-process — it's
rebuilt from the latest-10 each restart and never persisted.

## Decisions (from brainstorming)
- Error sensor prefers the cached cloud text, static string as fallback.
- **Persist the cache directly** (not by threading the code through #1's
  `device_messages` dicts) — same source text keyed by code, decoupled. Over
  time the persisted cache captures "all or most" codes; new ones are caught as
  they fire.
- Divergence surfaced as a **dev tool**, not a live entity.

## Components

### A. Error sensor prefers cloud text (core)
- New method on `_NotificationsMixin` (owns the cache):
  ```python
  def cloud_error_text(self, code: int) -> str | None:
      """Authoritative cloud notification text for an s2p2 code, or None.
      s2p2 = siid 2 / piid 2; the resolver keys the cache by (siid,piid,value)."""
      return self._notif_text_cache.get((2, 2, int(code)))
  ```
- `entities/sensor/device.py:_active_fault_text(snapshot, coord=None)`: for each
  latched fault code prefer `coord.cloud_error_text(c)` (via a defensive
  `getattr(coord, "cloud_error_text", None)`) over `describe_error(c)`. `coord`
  defaults `None` (keeps the audit eval-path + existing callers working — all
  static when coord absent).
- The error sensor's `value_fn` becomes
  `lambda coord: _active_fault_text(coord.state_machine.snapshot(), coord)`.
- `error_codes.py` is untouched → the `test_error_codes_confidence_gate` CI gate
  is unaffected.

### B. Persist the text cache
- `_core.py __init__`: add `self._notif_text_store: Store | None = None`.
- New `_restore_notif_text_cache(self)` (mirrors `_restore_device_messages`):
  construct `Store(self.hass, version=1, key=f"dreame_a2_mower_notif_text_{entry_id}")`,
  `async_load()`, parse each `"siid:piid:value"` string key back to an
  `(int,int,int)` tuple, and MERGE into `self._notif_text_cache` (so a restored
  entry is available before the baseline runs). Tolerate a missing/corrupt store.
  Call it in `_async_update_data`'s first-run block (alongside
  `_restore_device_messages`, before notification baseline/MQTT).
- New `_persist_notif_text_cache(self)`: serialize the cache to
  `{f"{s}:{p}:{v}": text}` and `self._notif_text_store.async_delay_save(
  lambda: serialized, NOTIF_TEXT_SAVE_DELAY_S)` (guarded on store not None;
  `NOTIF_TEXT_SAVE_DELAY_S = 5`). Call it after the cache is updated:
  (1) at the end of `_establish_notification_baseline` (after the seed loop),
  (2) in the reactive resolver right after `self._notif_text_cache[target_key] = text`.
- Net effect: the cache accumulates `(siid,piid,value) -> en_text` for every code
  ever seen and survives restarts; `cloud_error_text` (A) reads from it.

### C. Divergence dev tool
- `tools/probes/error_text_divergence.py` (with a `TOOL_META` block per the
  tools/ convention; regenerate the tools README via `gen_readme.py`).
- Source of cloud text (pick the richest available):
  - `--cache-file <path>`: a persisted notif-text store JSON (the accumulated
    cache, copied from the HA box `/config/.storage/dreame_a2_mower_notif_text_*`)
    → full coverage; OR
  - default: a one-shot live cloud fetch of device-messages/v2 (latest ~10) →
    build `{value: en_text}` from each record's `source.value` + `localizationContents.en`.
- Diff against `ERROR_CODE_DESCRIPTIONS`, cross-referencing `inventory.yaml §
  state_codes` `decoded` status. Print per code:
  `MATCH` / `DIFFERS (static="..." cloud="...")` / `MISSING-STATIC (cloud only)`
  / `MISSING-CLOUD (static only)`, each tagged with the inventory decoded status.
  This is the "authoritative flag" that identifies which static strings are
  short/borrowed/missing and which `hypothesized` codes are promotion candidates.

### D. Curate static fallback strings
- Run C; for each `DIFFERS`/`MISSING-STATIC` code whose inventory `decoded` is
  `confirmed`/`partial`, update its `error_codes.py` description to the fuller
  cloud wording, and append a `state_codes` `verifications:` row dated 2026-06-18
  citing the cloud text (`status: verified`, evidence the device-messages probe).
- Codes with cloud text but only `hypothesized` are LISTED by the tool as
  promotion candidates but NOT added to `error_codes.py` (the confidence gate
  forbids it). Promoting them is out of scope here (needs the inventory row
  flipped to confirmed first, a separate decision).
- The `test_error_codes_confidence_gate` and full suite must stay green.

## Data flow
Boot: `_restore_notif_text_cache` seeds the cache from disk → baseline adds the
latest-10 → live s2p2 fires add more, each persisting via `async_delay_save`.
Display: error sensor `value_fn` → `_active_fault_text(snapshot, coord)` →
`coord.cloud_error_text(c)` (persisted cache) or `describe_error(c)` fallback.

## Testing
- A: `_active_fault_text` with a fake coord whose `cloud_error_text` returns text
  for one latched code and `None` for another → joined output uses cloud text
  where present, static fallback elsewhere; `coord=None` → all static.
- B: persist → restore round-trip incl. the `"s:p:v"` key (de)serialization;
  bad/missing store → cache unchanged, no raise; restore MERGES (doesn't clobber
  a live entry).
- C: diff logic on fixtures (MATCH/DIFFERS/MISSING-STATIC/MISSING-CLOUD +
  decoded-status tagging); `TOOL_META`/README sync gate green.
- D: `test_error_codes_confidence_gate` + full suite green after the edits.

## Out of scope
- Threading the code through `device_messages` dicts (we persist the cache
  directly instead).
- Auto-promoting `hypothesized` codes to confirmed.
- A live divergence entity (the tool covers it).

## Verification (live, after release)
With the integration running and a recent fault that pushed a notification,
`sensor.dreame_a2_mower_error` shows the full app wording; after a restart the
persisted cache still resolves it (no per-process reset). The tool lists current
divergences for ongoing curation.
