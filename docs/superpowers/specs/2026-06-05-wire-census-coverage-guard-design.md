# Wire-Census Coverage Guard — Design

**Date:** 2026-06-05
**Status:** Approved (brainstorming → spec)
**Branch:** `feat/wire-census-coverage-guard`

## Problem

`inventory.yaml` is meant to be the **total map of everything the g2408 sends
upstream**, but it drifts silently from the wire: a property's value set in the
inventory reflects only the values someone happened to notice, not all values
the corpus actually contains. Concrete drift found 2026-06-05 (`updates1.txt`):

- `s5p104` — inventory records value `7`; corpus also has `12`.
- `s5p105` — inventory records `1,2,4`; corpus has `1,2,3,4,5` (missing `3,5`).
- `s5p106` — corpus has 17 distinct values (`1..20`); inventory undercounts.
- `s5p107` — corpus has ~190 distinct values (`1..255`) — a counter, not an enum.
- `s1p53` — mislabelled `OBSTACLE` in both the integration AND the external
  probe; it is actually **Bluetooth connectivity** (fires on app foreground/
  background). (Out of scope here — a separate correctness fix.)

There is no mechanism that fails when a wire-observed value isn't accounted for.
The probe corpus already decodes every reading (the `pretty`/`deep` log entries
even mark first-sightings with a `NEW` prefix), so the data to close this exists
— it just isn't diffed against the inventory or gated.

## Goal

A **durable, CI-gated coverage guard**: for every `(siid,piid)` and — for
discrete properties — every distinct value in the probe corpus, `inventory.yaml`
must account for it. CI fails on any **unparked novelty**, but an undecoded value
may be *parked* (`unknown`) to go green and decoded later. **Total map enforced;
decoding deferrable.**

## Corpus shape (what we're working with)

`probe_log_*.jsonl` (9 logs on the dev box) entry types:
`mqtt_message` (raw payloads), `pretty` (decoded readings like
`NEW s5p104 (S5P104_RAW) = 12`), `deep` (complex-value dumps for nested props).
Distinct properties named across the corpus: **56 variants → ~28 distinct
`(siid,piid)`** (s1:15, s2:20, s3:2, s5:10, s6:8, s99:1). Properties appear both
under a decoded name and as `UNKNOWN` when the probe's own decoder can't resolve
them.

**Constraint:** the raw `probe_log_*.jsonl` live in the dev-box parent dir, NOT
in the integration repo — so GitHub CI cannot read them. The guard bridges this
with a **committed census artifact** (below).

## Architecture — three components + a workflow

### 1. `tools/wire_census.py` — census generator (dev-box)

Aggregates all `probe_log_*.jsonl`. From `pretty` lines it parses
`sNpM (NAME) = value`; from `deep` it parses nested-property shape dumps. Emits,
per property:

```jsonc
{
  "s5p104": {
    "siid": 5, "piid": 104, "names": ["S5P104_RAW"],
    "kind_hint": "enum",            // auto-guess; inventory's value_kind wins
    "values": [7, 12],              // distinct discrete values (enum/counter)
    "shape_sigs": null,             // for nested props: distinct key-sets / op ids
    "first_seen": {"7": "2026-04-..", "12": "2026-05-25 12:32:24"},
    "count": 41
  },
  ...
}
```

- For **nested** props (s2p50/56/51) it records distinct **shape signatures**
  (sorted key-sets, or the `o`/op id for s2p50) instead of raw values.
- For **blob** props (s1p1/s1p4 `[bytes]`) it records presence only (no values —
  internal byte decode is tracked in `knowledge-gaps.md`, not here).
- `kind_hint` auto-guess: small distinct set → `enum`; wide 0–255 spread →
  `counter`; `[bytes]` → `blob`; nested dump → `nested`. Advisory only.

Writes **`docs/research/wire-census.json`** (committed, pretty-printed, stable key
order so diffs are clean). Regenerated on the dev box after new captures.

**Modes:**
- (default) regenerate `wire-census.json`.
- `--seed` — emit `value_kind` + `observed_values` YAML blocks per property from
  the census, for one-time paste/merge into `inventory.yaml` (bootstrap; avoids
  hand-typing ~hundreds of values).
- `--unknowns` — print every census value/property NOT registered in inventory,
  each annotated with **circumstance** (timestamp + the s2p1/s2p2/activity window
  around its first sighting, pulled from `mqtt_message`) and an **auto-grep of
  `OLD/`** (esp. `dreame-mower/.../device_code.py`) for candidate names.

### 2. Inventory schema additions (per observed entry)

```yaml
    value_kind: enum        # enum | counter | continuous | blob | nested
    observed_values:        # only for value_kind: enum (and shape list for nested)
      - {value: 7,  status: confirmed}     # decoded elsewhere in the entry
      - {value: 12, status: unknown}       # PARKED — acknowledged, not yet decoded
```

- `value_kind` tells the guard *how* to check: `enum` → every census value must
  be in `observed_values`; `nested` → every census shape-sig must be registered
  (an `observed_shapes` list); `counter`/`continuous` → no value enumeration
  (presence, optional min/max range); `blob` → property-presence only.
- `observed_values` is the **park list**. A value with `status: unknown` is
  parked: it satisfies the gate but is visibly flagged as undecoded (and shows up
  in `--unknowns` until decoded). `status` reuses the existing taxonomy
  (`confirmed | partial | presumed | unknown`).
- Schema validator (`inventory_gen.py --validate-only`) extends to accept these
  fields and validate their shapes/enums.

### 3. CI test `tests/inventory/test_wire_coverage.py`

Loads `docs/research/wire-census.json` + `inventory.yaml`. For each property in
the census:
- (a) the `(siid,piid)` MUST have an inventory entry → else FAIL
  (`unregistered property sNpM seen on wire`).
- (b) `value_kind: enum` → every census `value` ∈ `observed_values` → else FAIL
  (`unparked value sNpM=V — decode it or park as status: unknown`).
- (c) `value_kind: nested` → every census shape-sig ∈ `observed_shapes` → else
  FAIL.
- (d) `counter`/`continuous`/`blob` → property-presence only (skip value
  enumeration); optionally assert observed range ⊆ a declared `[min,max]`.

Runs in the existing `inventory` test job (no network, no raw logs — reads the
committed census).

### Regeneration workflow (steady state)

1. New capture lands → `python tools/wire_census.py` regenerates
   `wire-census.json`.
2. CI flags any new unparked value/property.
3. `tools/wire_census.py --unknowns` surfaces it with circumstance + OLD/ grep.
4. Dev **decodes** it (→ `status: confirmed/partial` + semantic) OR **parks** it
   (`status: unknown`) to go green. Either way the total map stays complete.

## Bootstrap (the one-time heavy lift)

`--seed` generates the initial `value_kind` + `observed_values` for all ~28
properties from the census. The dev reviews each `value_kind` (the auto-guess is
advisory — e.g. s2p2 is a large `enum`, s5p107 is a `counter` despite both having
many distinct values) and merges into inventory. Already-documented codes (e.g.
the s2p2 state_codes) map to `status: confirmed`; genuinely-unknown ones (s5p104=
12, s5p105=3/5, etc.) are parked `unknown` and become the classification backlog.

## Out of scope (separate concerns, explicitly excluded)

- **Byte/bit decode inside s1p1/s1p4 blobs** — tracked in `knowledge-gaps.md`
  §1–2. The guard checks the blob *property* is present, not its internal bytes.
- **The s1p53 relabel** (Bluetooth, not Obstacle) — `updates1.txt` item 1; a
  definite correctness fix across the integration + docs + external probe,
  handled as its own task. (The census will *register* s1p53; what it's *named*
  is the relabel's job.)
- **Decoding the parked unknowns** (s5p104–107 etc.) — the guard surfaces and
  enforces acknowledgement; the actual decode is the human classification loop it
  enables, done incrementally.

## Testing

- **Census parser** — unit test on a small synthetic `.jsonl` fixture
  (pretty/deep/mqtt lines) → assert the per-property value sets, shape-sigs, and
  first-seen map.
- **Coverage checker** — unit test on a tiny inventory+census pair: parked value
  → pass; unparked value → fail with the right message; missing property → fail;
  `counter` kind → value-enumeration skipped; `nested` shape-sig present/absent.
- **Bootstrap (`--seed`)** — assert it emits valid YAML that round-trips through
  the schema validator.
- Existing full suite stays green; the new CI test is additive.

## File structure

| File | Responsibility |
|---|---|
| `tools/wire_census.py` | Census generator + `--seed`/`--unknowns` modes (dev-box; reads probe logs from a configurable dir) |
| `docs/research/wire-census.json` | Committed census artifact (the in-repo CI bridge) |
| `custom_components/dreame_a2_mower/inventory.yaml` | `value_kind` + `observed_values`/`observed_shapes` per observed entry |
| `tools/inventory_gen.py` | Schema validator extended for the new fields |
| `tests/inventory/test_wire_coverage.py` | The CI coverage gate |
| `tests/tools/test_wire_census.py` | Census parser + checker unit tests |

## Fact-discipline note

The census records what's *on the wire* (observation), not meanings. Parking a
value `status: unknown` is the honest state for an undecoded value — it is
explicitly NOT a claim. Decoded values still require their normal
`verifications:` evidence. Cross-references from `OLD/` (e.g. dreame-mower) enter
as `presumed`/`partial`, never `confirmed`, until g2408-wire-labelled — same rule
as the 2026-06-05 s2p2=20/72 cross-reference.
