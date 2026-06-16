# Live-map backfill from the authoritative trail store

**Status:** Design (approved direction)
**Date:** 2026-06-16

## Problem

The Dreame app, when you open the live map mid-session, instantly repaints the
already-mowed path captured since the session began, then resumes live painting.
The integration's dashboard live map (`dreame-mower-map-card`, Overview tab,
`dashboards/mower/dashboard.yaml:218`) is *supposed* to do the same via a
`track_snapshot` cold-start seed, but in practice it paints from "now."

Two concrete defects, both rooted in one architectural mistake — a **parallel
trail mirror** that drifts from the authoritative store:

- **Gap 1 — backfill does not survive a restart.** `_track_snapshot`
  (`coordinator/_core.py:312`) is in-memory, initialised to `None`, and reset to
  `[]` only when a *new* session begins (`_begin_live_stream()`,
  `coordinator/_mqtt_handlers.py:485`). On an HA restart mid-session that branch
  is deliberately skipped (the session is restored from `in_progress.json`, so
  `live_map.is_active()` is already true). Result: `_track_snapshot` stays `None`,
  and `_publish_live_point` only appends `if self._track_snapshot is not None`
  (`coordinator/_rendering.py:282`), so it never resumes accumulating either. The
  card seeds from `None` → empty → paints from now. The real trail is sitting,
  fully restored, in `live_map.track`.

- **Gap 2 — the snapshot truncates its own early history.** It is capped at
  `_LIVE_TRACK_SNAPSHOT_MAX = 1000` (`coordinator/_rendering.py:90`) and overflow
  drops the *oldest* point (`del self._track_snapshot[0]`). At the ~5 s push
  cadence that is ~83 minutes; a longer mow silently loses its early trail even
  with no restart.

The authoritative trail — `live_map.track` — is persisted, restored on boot, and
holds the full per-point history `[t, x_m, y_m, area_m2, heading_deg, task_state,
role]`. The fix is to serve the backfill **from it** and retire the mirror.

## Non-goals

- **Filling genuine downtime.** If the integration was down for part of a
  session, those positions are unknown until the end-of-session cloud blob; the
  map legitimately stays empty there. This design must *not* draw a false line
  across such a gap (see part 3), but it does not try to recover the missing
  points.
- **Role-coloured backfill (mowing vs traversal).** The live card draws a
  single-colour trail for live points today; the backfill matches that for
  parity. Per-role colouring is a possible later enhancement, out of scope here.

## Design

Delivery stays as a **camera state attribute** (chosen over a WebSocket command:
it is the existing model, needs no async fetch in the card, and the payload stays
bounded by decimation).

### 1. Derive `track_snapshot` from `live_map.track` (fixes Gap 1)

In `camera/map.py:extra_state_attributes`, build `track_snapshot` from
`self.coordinator.live_map.track` instead of reading
`coordinator._track_snapshot`. Map each `TrackPoint` to the card's existing
contract `[x_m, y_m, heading_deg | None, t]`, preserving point order.

Because `live_map.track` is restored from `in_progress.json` on boot, the
backfill survives restarts with no extra "repopulate on restore" code, no
accumulation guard, and no drift between two stores.

Cache the derived list keyed by `len(live_map.track)` (the count only grows
during a session and is reset at finalize), so the per-attribute-read cost is a
dict lookup except on the ~5 s boundary when a point is appended.

### 2. Decimate, don't truncate (fixes Gap 2)

When the derived trail exceeds a wire budget (`LIVE_TRACK_SNAPSHOT_MAX`, raised
to ~2000), keep every Nth point (`stride = ceil(len / MAX)`) so the **full
extent** is preserved at reduced resolution — never drop the oldest. Always keep
the final point so the seed's hand-off to `latest_point` is continuous. A
polyline at 2000 points is visually indistinguishable from one at 5000.

### 3. Gap-aware drawing in the card (the "leave it empty" requirement)

`_seedFromSnapshot` currently builds one continuous `<path>`, so a restart /
downtime gap is bridged by a phantom straight mow-line. Every snapshot point
carries its timestamp at index 3, so the card splits the path wherever two
consecutive points are more than a threshold apart in time
(`SEED_GAP_SECONDS`, ~30 s — comfortably above the ~5 s cadence). The trail
becomes a multi-subpath `d` (`M … L … M … L …`); downtime renders as genuinely
empty.

A stationary pause (mower up, points deduped) also produces a time gap, but the
positions either side coincide, so the split is a zero-length break — harmless.
Only real movement across a gap (i.e. downtime) yields a visible break, which is
the desired behaviour.

### 4. Retire the mirror

Remove `coordinator._track_snapshot`, `_LIVE_TRACK_SNAPSHOT_MAX`'s mirror role,
the `_track_snapshot` reset inside `_begin_live_stream`, and the append in
`_publish_live_point`. `latest_point` / `point_seq` continue to drive incremental
live painting unchanged. `_begin_live_stream` keeps resetting
`_live_point_seq`/`_latest_point` for a clean new-session start.

## Components touched

| Unit | Change |
|---|---|
| `camera/map.py` | `track_snapshot` attr derived from `live_map.track` (mapped + decimated + cached) |
| `coordinator/_rendering.py` | drop `_track_snapshot` accumulation; keep `_publish_live_point` (latest/seq only); decimation helper |
| `coordinator/_core.py` | remove `self._track_snapshot` field |
| `coordinator/_mqtt_handlers.py` | `_begin_live_stream` no longer touches the mirror (unchanged otherwise) |
| `www/dreame-mower-map-card.js` | `_seedFromSnapshot` / `_redrawTrail` split path on time gaps; bump `CARD_VERSION` |

## Data flow

```
s1p4 push ─► live_map.append_point() ─► live_map.track  (persisted, restored)
                                          │
                          extra_state_attributes (cached by len)
                                          │  map → [x,y,hdg,t], decimate ≤2000
                                          ▼
                                   track_snapshot attr
                                          │
card cold-start (seq<0 | seq regressed | gap>1)
   _seedFromSnapshot ─► split on Δt>SEED_GAP_SECONDS ─► multi-subpath trail
                                          │
                       then live: latest_point / point_seq append
```

## Error / edge handling

- **No session / idle:** `live_map.track` empty → `track_snapshot` empty/absent →
  card falls through to the idle `last_known_point` icon (unchanged).
- **Heading `None`:** preserved as `null` in the point; card already tolerates it
  (motion-vector fallback).
- **Restart with browser already open:** server `point_seq` resets low; the card's
  existing `point_seq < this._seq` branch re-seeds from the (now restored)
  snapshot — works for free once the snapshot is correct.
- **Very large track:** bounded by decimation; cache avoids recompute thrash.

## Testing

- Unit: `track_snapshot` derives correctly from a populated `live_map.track`;
  survives a simulated restart (track restored, mirror gone); decimation keeps
  first+last and bounds length; cache invalidates on append.
- Card: node render-harness (per repo convention) asserting `_seedFromSnapshot`
  emits multiple subpaths when a time gap is present and one path otherwise.
- Live validation (user): run a session, then (a) hard-refresh the dashboard
  mid-mow, (b) restart HA mid-mow and reopen — confirm the trail repaints to the
  current position with downtime gaps left empty.
