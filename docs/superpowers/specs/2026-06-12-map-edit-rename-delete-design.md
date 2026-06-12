# Phase F (part 1) — Map editing: rename zone & delete object

**Status:** approved 2026-06-12. Wire facts from the 2026-06-09 app↔mower MITM
capture (`/data/claude/homeassistant/dreame-app-capture-2026-06-09/miio-cloud-13267-http.jsonl`),
summarized in `dreame-app-WRITE-implementation-guide-2026-06-09.md`. Per the
project rule, app↔mower MITM is wire-verified.

## Scope

Wire the two **wire-confirmed, non-spatial** map-edit operations:
- **Rename a mowing zone** — `o=219 {region:<zone#>, name:"…"}`
- **Delete a map object** (zone / no-go / ignore-obstacle) — `o=218 {id:<objId>, type:<category>}`

Both run inside the device's map-edit **transaction**: `o=204 (p:0)` begin →
mutation(s) `(p:0)` → `o=201 (p:1)` commit, on the currently-selected map.
Targeting a specific map sends `o=200 {idx:map_id}` first (which makes that map
active and it stays active — mirrors the app's edit screen).

### Wire evidence (capture order, escaped quotes stripped)
```
m:a,p:0,o:204            # begin edit
m:a,p:0,o:218 d:{id:101,type:0}    # delete zone/no-go
m:a,p:0,o:219 d:{region:1,name:"Zone1 test"}   # rename zone
m:a,p:0,o:219 d:{region:1,name:"Zone1"}        # rename back
m:a,p:1,o:201            # commit
...
o:218 d:{id:102,type:4}  # delete obstacle (category 4)
o:200 d:{idx:1} / {idx:0}  # select map
```
Confirmed: `o=219` region+name; `o=218` id+category (0=zone/no-go, 4=obstacle —
both observed; other category codes to confirm); transaction `204…201` with
`p:0` on begin/mutations and `p:1` on commit; multiple mutations may share one
wrapper.

## Non-goals (deferred, feasibility confirmed)

- **Create** no-go / mow-shape / ignore-obstacle (`o=215`/`o=234`) — needs
  coordinates; deferred to a future interactive click-to-draw Lovelace card
  (canvas/SVG over the map render → pixel→meter → service).
- **Split / merge** (`o=220`/`o=221`) — destructive (clears schedule / resets
  prefs); deferred.
- **Rename whole map / delete whole map** — uncaptured.
- **Draw-by-driving** — BT-gated, uncaptured.
- No new UI this phase (services + sensor attrs only; a card comes later).

## Architecture

### 1. Transport — add `p` to the routed-action helpers

`protocol/cfg_action.py::call_action_op(send_action, op, extra=None, *, p=0)`:
build `{"m":"a","p":int(p),"o":int(op)}` and attach `d=extra` only when `extra`
is given (unchanged default `p=0` keeps every existing caller identical).

`cloud_client/_rpc.py::routed_action(self, op, extra=None, *, p=0)`: thread `p`
through to `call_action_op`. Existing callers pass no `p` → no behaviour change.

### 2. Coordinator — the edit transaction (`coordinator/_writes.py`)

```python
async def edit_map(self, map_id: int, mutations: list[tuple[int, dict | None]]) -> bool:
    """Run a map-edit transaction on `map_id` and refresh state.

    mutations is an ordered list of (opcode, payload) — e.g.
    [(219, {"region":1,"name":"X"})] or [(218, {"id":101,"type":0})].
    Sequence: o=200{idx:map_id} -> o=204(p:0) -> each mutation(p:0)
    -> o=201(p:1). The target map becomes (and stays) active. Each leg is
    sent via routed_action; a None result marks overall failure but the
    commit (o=201) is always sent so the device never stays in edit mode.
    Refreshes cloud_state + MAPL afterward. Held under _chunked_write_lock.
    """
```
Then thin wrappers:
- `rename_zone(map_id, region, name)` → `edit_map(map_id, [(219, {"region":region, "name":name})])`
- `delete_map_object(map_id, obj_id, category)` → `edit_map(map_id, [(218, {"id":obj_id, "type":category})])`

`edit_map` calls (each an executor job): `routed_action(200,{"idx":map_id})`,
`routed_action(204)`, `routed_action(op,payload)` per mutation,
`routed_action(201, p=1)`. Track `ok = all legs non-None` (begin+mutations);
always send commit; `await self._refresh_cloud_state()` (which re-reads MAPL so
the new active map + edited objects surface). Return `ok`.

### 3. Decoder — surface the cloud object id + delete category (`map_decoder.py`)

`_collect_exclusion_entries` currently reads `entry[1]` (geometry) and discards
`entry[0]` (the cloud object id — same `entry[0]=id` pattern spots/zones use).
Change:
- It returns `(obj_id, rotated_path, subtype)` triples (parse `entry[0]` as
  `int` when present; `None`/`-1` when absent).
- `ExclusionZone` gains `obj_id: int | None = None` and a derived
  `delete_category: int | None` (subtype `None`→0 no-go, `"ignore"`→4
  ignore-obstacle; leave `None` for unknown → not offered for delete).
- `MowingZone` already has `zone_id` (the `region` for rename and the delete id
  for zones, category 0); `SpotZone` already has `spot_id`.
- **Geometry/rendering math is untouched** — additive id fields only. All
  existing decoder tests must stay green.

> Build-time verification: confirm against a real `fetch_map` payload that
> existing exclusion entries carry `entry[0]` ids in the same space as the
> captured deletes (101/301 category 0, 102 category 4). If some object kinds
> lack ids, omit them from `deletable_objects` (don't fabricate ids) and note
> it in knowledge-gaps.

### 4. Surfacing — per-map sensor attributes (`sensor_map.py`)

Add two attributes to the existing per-map map sensor (no new entities):
- `renamable_zones: [{"region": zone_id, "name": name}, …]` (from `MowingZone`).
- `deletable_objects: [{"id": id, "category": cat, "label": str}, …]` — union
  of mowing zones (cat 0), no-go (cat 0), ignore-obstacles (cat 4) that carry an
  id. `label` is human text (e.g. `"Zone1"`, `"No-go #101"`, `"Ignore #102"`).

These feed the services today and the future click-to-select/draw card. The
target map for the services is identified by the sensor's `map_id`.

### 5. Services (`services.yaml` + `services.py`)

- `dreame_a2_mower.rename_zone` — fields `map_id` (int), `zone` (int, the
  `region`/`zone_id`), `name` (str). Handler resolves the coordinator → `rename_zone`.
- `dreame_a2_mower.delete_map_object` — fields `map_id` (int), `object_id` (int),
  `category` (int; 0=zone/no-go, 4=ignore-obstacle). Handler → `delete_map_object`.
  Delete is deliberate (explicit id+category; no bulk delete).

Register both alongside the existing services; add to the unregister list.

### 6. Honesty + fact discipline

- These are write operations surfaced as **services**, not control entities, so
  there is no `control_honesty.py` verdict to flip (services don't carry a
  padlock). The writable capability is recorded in `entity-inventory.yaml` /
  `inventory.yaml` verification records.
- `inventory.yaml`: add a confirmed verification for the map-edit transaction +
  the `o=219`/`o=218`/`o=204`/`o=201`/`o=200` opcode table, tagged
  `[app-mitm:2026-06-09-map-edit]`, citing the capture file + the observed
  payloads. Status `verified`, evidence pointer (taxonomy: `verified` +
  `evidence:`, matching existing rows — NOT `confirmed`/`source:`).
- `docs/research/app-integration-roadmap.md`: row F → **partial done**
  (v1.0.25a6) — rename+delete shipped; create/split/merge/rename-map/delete-map/
  draw-by-driving deferred.
- `docs/research/knowledge-gaps.md`: record the deferred ops + the open
  delete-category codes (only 0 and 4 observed) + that rename-map/delete-map are
  uncaptured.
- `tools/state_machine/state_machine_audit_expectations.yaml` + audit: no new
  entities expected (services + sensor attrs only) — verify the audit still exits
  0; add rows only if a new entity is introduced.

### 7. Behaviour note

Editing a non-active map makes it active and it stays active (matches the app's
edit screen). HA reflects the new active map after the post-write MAPL refresh.
This is intentional, not a bug; document it in the service descriptions.

## Testing

Vanilla stubbed-HA venv (`/data/claude/homeassistant/.venv-vanilla`). Fake
dids/coords/ids only.

1. `call_action_op` / `routed_action` `p` param: `p=0` default unchanged;
   `p=1` emits `{"m":"a","p":1,"o":201}`; `extra` still nested under `d`.
2. `edit_map` envelope (fake `routed_action` capturing every call): order is
   `o=200{idx} → o=204 → mutation(s) → o=201(p=1)`; correct `p` per leg;
   commit always sent even if a mutation returns None; returns False on any
   begin/mutation failure, True on all-success; `_refresh_cloud_state` awaited;
   `_chunked_write_lock` held.
3. `rename_zone` builds `[(219, {"region":R,"name":N})]`; `delete_map_object`
   builds `[(218, {"id":I,"type":C})]`.
4. Decoder: an exclusion entry `[101, {path…}]` yields `ExclusionZone.obj_id==101`
   and `delete_category==0`; an `"ignore"` entry yields category 4; an entry with
   no id yields `obj_id is None`. Existing geometry tests unchanged.
5. Sensor attrs: `renamable_zones` lists `{region,name}` from MowingZone;
   `deletable_objects` lists zones + id-bearing exclusions with category + label;
   objects without ids are excluded.
6. Services resolve the coordinator and reach `rename_zone` / `delete_map_object`
   with the right args.

## Versioning / release

`manifest.json` is bumped by `release.sh` (it owns the bump; do NOT pre-bump).
Last released = 1.0.25a5 → release.sh auto-bumps to **1.0.25a6**. On completion:
merge to `main`, push, `release.sh` (tag + GitHub Release + HACS refresh).
