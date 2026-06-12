# Phase F part 2a — Map create / split / merge services

**Status:** approved 2026-06-12. Wire facts from the 2026-06-09 app↔mower MITM
capture (`/data/claude/homeassistant/dreame-app-capture-2026-06-09/miio-cloud-13267-http.jsonl`).
Decorative shape↔type map from `/data/claude/homeassistant/IMG_4615.PNG`.
Builds on Phase F part 1 (`edit_map` transaction + rename/delete).

## Scope

Wire the remaining **wire-verified** map-edit create/split/merge ops as
coordinate-driven services, each a single mutation through the existing
`edit_map` transaction (`o=200 select → o=204 begin → mutation(p:0) → o=201
commit(p:1)`, target map becomes active). No frontend this phase.

### Wire evidence (capture, escaped quotes stripped)
```
o=215 {id:-1, type:1, points:[[6.48,3.23],[-7.56,-5.81]], radius:0}          # line / virtual wall (2 pt)
o=215 {id:-1, type:2, points:[[9.65,-0.13],[4.12,-0.13],[4.12,5.01],[9.65,5.01]], radius:0}  # polygon (N pt)
o=215 {id:-1, type:3, points:[[-5.08,-4.97]], radius:1.4999654827152207}     # circle (1 pt + radius m)
o=215 {id:-1, type:9, points:[P,P,P,P], radius:0}                            # mow-shape Square (4 pt)
o=215 {id:-1, type:13, points:[[0.57,-8.39],[-7.97,0.15]], radius:0}         # mow-shape Heart (2 pt bbox)
o=234 {id:-1, type:0, points:[[-2.49,-5.97],...]}                            # ignore-obstacle (polygon, NO radius)
o=220 {id:1, line_start:[-0.19,-11.41], line_end:[-5.21,-6.22]}              # split zone 1 by a line
o=221 {ids:[2,1]}                                                            # merge zones 2 and 1
```
Coords are in **meters** (the map edit-frame). `id:-1` is the create sentinel
(server assigns the real id, which then appears in the decoded map + part-1
`deletable_objects`).

### `o=215` type codes (wire-confirmed + IMG_4615 "Shapes" screen)
| type | meaning | points |
|---:|---|---|
| 1 | no-go line / virtual wall | 2 |
| 2 | no-go polygon | N (≥3) |
| 3 | no-go circle | 1 + `radius` (m, >0) |
| 9 | mow-shape Square | 4 |
| 12 | mow-shape Circle | 2 (bbox) |
| 13 | mow-shape Heart | 2 |
| 14 | mow-shape Triangle | 2 |
| 15 | mow-shape Teardrop | 2 |
| 16 | mow-shape Mushroom | 2 |
| 17 | mow-shape Cloud | 2 |
| 18 | mow-shape Rainbow | 2 |

Mow-shapes are decorative "design your lawn" stamps — the robot mows around them
and leaves the shape uncut. Square (9) is a 4-corner rectangle; 12-18 are placed
by a 2-point bounding box.

## Non-goals (deferred)

- The interactive click-to-draw Lovelace card and the edit-frame↔render-frame
  coordinate verification — **F2b** (next phase). Services here are
  frame-agnostic: they pass the caller's meters straight to the wire and
  document that `points` are in map edit-frame meters.
- Rename-whole-map / delete-whole-map (uncaptured).
- Draw-by-driving (BT-gated).
- No decoder / sensor / entity changes; no new control-honesty entries (these
  are services).

## Architecture

### 1. Coordinator wrappers (`coordinator/_writes.py`) — reuse `edit_map`

Each builds one `(opcode, payload)` mutation and calls
`self.edit_map(map_id, [mutation])`. Validation raises `ValueError` (handler
catches → logs → no-op) BEFORE any wire call so a malformed shape never reaches
the device.

```python
_NOGO_TYPE = {"line": 1, "polygon": 2, "circle": 3}
_MOW_SHAPE_TYPE = {
    "square": 9, "circle": 12, "heart": 13, "triangle": 14,
    "teardrop": 15, "mushroom": 16, "cloud": 17, "rainbow": 18,
}

async def create_no_go(self, map_id, shape, points, radius=0.0) -> bool:
    """o=215 no-go: shape line(2pt)/polygon(>=3pt)/circle(1pt+radius>0)."""
    t = _NOGO_TYPE[shape]                      # KeyError -> ValueError in wrapper
    # validate point count per shape; circle requires radius > 0
    return await self.edit_map(map_id, [(215, {
        "id": -1, "type": t, "points": _as_pairs(points), "radius": float(radius),
    })])

async def create_ignore_obstacle(self, map_id, points) -> bool:
    """o=234 type 0 polygon (>=3 pt), no radius field."""
    return await self.edit_map(map_id, [(234, {
        "id": -1, "type": 0, "points": _as_pairs(points),
    })])

async def create_mow_shape(self, map_id, shape, points) -> bool:
    """o=215 decorative mow-shape: square(4pt) / others(2pt bbox), radius:0."""
    t = _MOW_SHAPE_TYPE[shape]
    # square needs 4 points; every other mow-shape needs exactly 2
    return await self.edit_map(map_id, [(215, {
        "id": -1, "type": t, "points": _as_pairs(points), "radius": 0,
    })])

async def split_zone(self, map_id, zone_id, line_start, line_end) -> bool:
    """o=220 split zone by a line (DESTRUCTIVE: clears that zone's schedule/prefs)."""
    return await self.edit_map(map_id, [(220, {
        "id": int(zone_id), "line_start": _pair(line_start), "line_end": _pair(line_end),
    })])

async def merge_zones(self, map_id, ids) -> bool:
    """o=221 merge zones by id list (DESTRUCTIVE: resets merged prefs)."""
    return await self.edit_map(map_id, [(221, {"ids": [int(i) for i in ids]})])
```

`_as_pairs(points)` coerces an iterable of `[x, y]` (or `(x, y)`) into a list of
`[float, float]` pairs and raises `ValueError` on a malformed pair. `_pair(p)`
coerces a single `[x, y]`. Validation table:

| wrapper | shape | required points | radius |
|---|---|---|---|
| create_no_go | line | exactly 2 | sent (0) |
| create_no_go | polygon | ≥ 3 | sent (0) |
| create_no_go | circle | exactly 1 | sent, must be > 0 |
| create_ignore_obstacle | (polygon) | ≥ 3 | omitted |
| create_mow_shape | square | exactly 4 | sent (0) |
| create_mow_shape | other (12-18) | exactly 2 | sent (0) |

Unknown shape name → `ValueError`. The point-coordinates are NOT range-checked
(any meter value is valid map-frame; the device clamps).

### 2. Services (`services.py` + `services.yaml`)

Five services following the part-1 pattern (`_coordinator_from_call`,
`vol.Schema`, register + add to the unregister tuple). Use `vol.Coerce(...)` (the
vanilla test stub's `cv.string` is broken — see part 1). Points are passed as a
list of `[x, y]` float pairs.

- `dreame_a2_mower.create_no_go_zone` — `map_id` (int), `shape`
  (`vol.In(["line","polygon","circle"])`), `points` (list of [x,y]), `radius`
  (float, default 0).
- `dreame_a2_mower.create_ignore_obstacle` — `map_id`, `points`.
- `dreame_a2_mower.create_mow_shape` — `map_id`, `shape`
  (`vol.In(["square","circle","heart","triangle","teardrop","mushroom","cloud","rainbow"])`),
  `points`.
- `dreame_a2_mower.split_zone` — `map_id`, `zone` (int), `line_start` ([x,y]),
  `line_end` ([x,y]). Description flags it DESTRUCTIVE.
- `dreame_a2_mower.merge_zones` — `map_id`, `zones` (list of int). Description
  flags it DESTRUCTIVE.

Each `services.yaml` entry notes that `points`/coords are in map edit-frame
meters and that editing a non-active map makes it active (same as part 1).

### 3. Honesty + fact discipline

- All five ops are wire-confirmed → `inventory.yaml` verification records
  (`status: verified` + `evidence:` pointer to the capture; taxonomy as part 1),
  tagged `[app-mitm:2026-06-09-map-edit]`. Include the `o=215` type table +
  the decorative shape↔type map from `IMG_4615.PNG` (9=square…18=rainbow).
  Attach to the existing `o215`/`o220`/`o221`/`o234` inventory entries (part 1
  added an `o204` transaction record — extend, don't duplicate).
- `docs/research/app-integration-roadmap.md`: row F advances — create
  (o=215/o=234) + split/merge (o=220/o=221) now wired via services; only the
  interactive draw card (F2b) + rename-map/delete-map (uncaptured) +
  draw-by-driving remain.
- `docs/research/knowledge-gaps.md`: move create + split/merge out of "deferred"
  (now wired); keep the F2b card + the edit-frame↔render-frame verification as
  the open item; keep rename-map/delete-map uncaptured.
- `tools/state_machine/state_machine_audit_expectations.yaml` + audit: no new
  entities (services only) — verify the audit still exits 0.

## Testing

Vanilla stubbed-HA venv. Fake coords only.

1. Each wrapper builds the right `(opcode, payload)` via `edit_map` (patch/spy
   `edit_map` on a `_WritesMixin` instance): `create_no_go("polygon", 4pts)` →
   `(215, {id:-1, type:2, points:[…], radius:0.0})`; circle → type 3 + radius;
   line → type 1; `create_ignore_obstacle` → `(234, {id:-1, type:0, points})`
   (no radius key); `create_mow_shape("heart", 2pts)` → `(215, {type:13,…})`;
   `split_zone` → `(220, {id, line_start, line_end})`; `merge_zones([2,1])` →
   `(221, {ids:[2,1]})`.
2. Validation: wrong point count per shape raises ValueError (line≠2, circle≠1,
   polygon<3, square≠4, mow-shape≠2); circle radius≤0 raises; unknown shape name
   raises; `edit_map` NOT called when validation fails.
3. Shape-name→type mapping covers all of 1/2/3 and 9/12-18.
4. Services resolve the coordinator and reach the wrappers with the right args;
   a wrapper `ValueError` is caught by the handler (logged, no crash).

## Versioning / release

Do NOT pre-bump `manifest.json` — `release.sh` owns it (a6 → **a7**). On
completion: merge to `main`, push, `release.sh`.
