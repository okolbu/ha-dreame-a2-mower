# Phase E — Schedule editing (write via the SCHD*V3 device plane)

**Status:** approved 2026-06-10. Wire facts from
`/data/claude/homeassistant/dreame-app-schedule-write-2026-06-10.md`
(app↔mower MITM, treated as wire-verified per the project's capture process).

## Problem

The mower schedule is *displayed* (read-only) on the dashboard via a custom card
over `DreameA2ScheduleCountSensor` (`slots[].plans[]` attributes) and is *editable*
end-to-end at the service+card layer: the card holds the working set as the user
adds/edits/deletes runs and, on Save, calls
`dreame_a2_mower.set_schedule_plans` with the complete new plan list for one slot →
`coordinator.write_schedule(new_slots)`.

The single defect: `write_schedule` pushes the new blob to the **`SCHEDULE.*`
iotuserdata KV** via `write_chunked_key("SCHEDULE", …)`. Per the decoded protocol,
`SCHEDULE.*` is only the **app's cache mirror** — the device ignores it as a source
of truth. The real write is the **`SCHD*V3` routed-action chunked transaction** on
`sendCommand action s2.a50`. So schedule edits today are silently cloud-cache-only
(the same A2 KV-vs-device-plane bug seen in prior phases).

Phase E is therefore a **transport swap**, not a new UI: replace the KV write with
the `SCHD*V3` transaction, plus the honesty/fact-discipline updates.

## Non-goals (YAGNI)

- No new services. `set_schedule_plans` (full-slot-replace) already covers
  add/edit/delete because the card does client-side RMW. Granular
  `set_schedule_run`/`delete_schedule_run` are not built.
- No new display surfaces. The schedule calendar view + edit/delete list already
  exist on the dashboard (custom card over the sensor). No HA schedule
  `CalendarEntity`.
- No enable/disable. The app has no per-entry disable concept; deletion is the
  only removal. We never expose an enable/disable toggle. (The `SCHDSV3` state's
  `enabled`/`flag` are *preserved* on write, never user-exposed.)
- The dashboard card's `tap_action → service` wiring and calendar-click create/edit
  remain a separate future TODO (dashboard deploy, not integration code).

## Wire protocol (authoritative — from the 2026-06-10 doc)

Two layers; only the second is authoritative:

| Layer | Where | Authoritative? |
|---|---|---|
| `SCHEDULE.*` KV (`setDeviceData`) | app cache mirror | No — device ignores it |
| `SCHD*V3` via `sendCommand action s2.a50` | device control plane | **Yes** |

### Transport — one logical schedule write = header + N data chunks + state

All via `send_action(siid=2, aiid=50, [{"m":"s","t":<KEY>,"d":<...>}])` (the same
plumbing `cfg_action.set_pre`/`probe_get` use; `_unwrap` raises `CfgActionError`
on `r!=0`):

```
(1) HEADER: t="SCHDIV3", d={ i:<slot>, l:<total JSON byte length>, v:<txnId> }
(2) DATA:   t="SCHDDV3", d={ s:<offset>, l:<chunk len>, d:"<chunk>", v:<txnId> }   (×N, ≤50-byte chunks, ordered by s)
(3) STATE:  t="SCHDSV3", d={ i:<slot>, v:<version>, s:[<enabled>, <flag>] }
```

- The reassembled `SCHDDV3` payload is **one row**: `[slot, enabled, name, "<b64 blob>"]`.
- **Two distinct `v` fields**: header/chunks share the **txn id** (a large monotonic
  ms-epoch int — must be identical across header+all chunks of one write); the state's
  `v` is the **schedule version**.
- `l` in the header = total byte length of the row JSON string; `l` per chunk = that
  chunk's length.
- **READ** (RMW base): `t="SCHDTV3"` revision probe, then `SCHDIV3`/`SCHDDV3` with
  `m:"r"`; responses carry the same `[slot,enabled,name,b64]` rows.

### Blob — already correctly implemented

The base64 blob = one fixed record per run, concatenated, each terminated `0xED`:

```
record := AA <07+mode>  B2  TT TT  00  [ZZ]  [SEG]  ED
```

| mode | meaning | header[1] | len | zone byte[6] | seg byte[7] |
|---:|---|---|---:|---|---|
| 0 | all-area | `0x07` | 7 | — | — |
| 1 | zone full | `0x08` | 8 | yes | — |
| 2 | zone edge | `0x09` | 9 | yes | yes |

byte[2]=`(weekday<<4)|mode` (weekday **Sun=0…Sat=6**); byte[3:5]=LE u16,
`&0x0FFF`=minute-of-day, high nibble=mode; byte[5]=`0x00`; byte[6]=zone (mode≥1);
byte[7]=0-based edge index (mode 2).

**`protocol/schedule_encode.encode_schedule_blob` already emits exactly this layout**
(`_ACTION_LEN={0:7,1:8,2:9}`, the all-area 7-byte no-zone record, the
`mode<<12` time high-nibble, the `(bit+1)%7` weekday inversion to tm_wday). The
2026-06-10 doc's wire-verified all-area sample `aa07300c0300ed` confirms the existing
model — **no encoder change and no retraction needed**. We reuse it as-is and add a
byte-identical regression test against the three captured samples.

## Architecture

### New: `protocol/schedule_action.py` (protocol-only, no HA imports)

Mirrors `cfg_action.py` style — takes a `send_action(siid, aiid, params)` callable,
unwraps via the shared `_unwrap`.

```python
from .cfg_action import ROUTED_ACTION_SIID, ROUTED_ACTION_AIID, _unwrap, CfgActionError

CHUNK_SIZE = 50

def chunk_row_json(row_json: str) -> list[tuple[int, str]]:
    """Split a row-JSON string into (offset, chunk) pairs of <=CHUNK_SIZE bytes,
    ordered by offset, covering the whole string exactly once."""

def read_schedule_rows(send_action) -> list[list]:
    """Probe SCHDTV3, then read rows via SCHDIV3/SCHDDV3 (m:'r').
    Returns the list of [slot, enabled, name, b64blob] rows (RMW base).
    Raises CfgActionError on transport/endpoint failure."""

def write_schedule_row(send_action, *, slot, enabled, name, blob_b64,
                       version, flag, txn_id) -> None:
    """Emit SCHDIV3 header + N SCHDDV3 chunks (shared txn_id) + SCHDSV3 state.
    row_json = json.dumps([slot, enabled, name, blob_b64], separators=(',',':')).
    Raises CfgActionError if any leg returns r!=0."""
```

`l` (header) = `len(row_json.encode("utf-8"))`. Chunk `l` = `len(chunk.encode("utf-8"))`.
(JSON is ASCII for our payloads, but length is computed on bytes to be exact.)

### Changed: `coordinator/_writes.py::write_schedule`

Becomes an RMW over the device plane:

1. `rows = read_schedule_rows(self._cloud.action)` (executor job) — authoritative
   `[slot,enabled,name,b64]` + per-slot version where available; fall back to
   `cloud_state.schedule.version` if the read yields none.
2. For each incoming `ScheduleSlot` in `new_slots`:
   - `blob_b64 = encode_schedule_blob(slot.plans)`.
   - Look up the authoritative row for `slot.slot_id`. Skip the write if the
     re-encoded blob **and** name are unchanged (idempotent — avoids spurious
     version bumps / rewriting the untouched seasonal slot).
   - Preserve `enabled`/`flag` from the authoritative row (default `enabled=1`,
     `flag` from row or `0`); `name` from the slot; `version = current+1`.
   - `txn_id = self._next_schedule_txn_id()` (monotonic ms-epoch int, generated in
     the coordinator so the protocol layer stays pure/testable).
   - `write_schedule_row(...)` under `self._chunked_write_lock` (executor job).
3. `await self._refresh_cloud_state()`; return overall success.

`build_schedule_set_value` and the `write_chunked_key("SCHEDULE", …)` path are
**retired** (deleted from `write_schedule`; the helper may remain only if other
callers exist — grep shows none, so remove it).

The `set_schedule_plans` service handler is unchanged (it builds `new_slots` and
calls `write_schedule`).

### Honesty + fact discipline

- Flip the schedule control's `control_mode` in `control_honesty.py` from read-only
  to **writable** (`_W`), justified by: app-MITM wire-verification of the accepted
  `SCHD*V3` bytes **plus** byte-identical unit tests proving our integration emits
  those exact bytes. Per the user's clarification, app↔mower MITM snooping **is**
  wire-verification across the board (not integration-originated wire only).
- `inventory.yaml` + `entity-inventory.yaml`: schedule rows updated with the
  writable verdict and a verification record tagged
  `[app-mitm:2026-06-10-schedule-write]`; cite the three samples + transport.
- **Docs TODO (this phase):** update the fact-discipline rule in the repo `CLAUDE.md`
  and the relevant `docs/research/` note(s) to state that **app-MITM (app↔mower)
  captures count as wire-verified across the board**, superseding any wording that
  implied only integration-originated wire or only calendar entities qualify.
- `docs/research/app-integration-roadmap.md`: mark row **E done** with the version.
- `tools/state_machine/state_machine_audit_expectations.yaml` + audit: keep green
  (control-mode flip; no new entities expected — verify the audit still exits 0).
- `docs/research/knowledge-gaps.md`: carry the doc's open items (byte[5] meaning;
  2nd-edge `seg=1`; multi-day-per-run bitmask-vs-records; slot allocation on add).

## Testing

Vanilla stubbed-HA venv (`/data/claude/homeassistant/.venv-vanilla`). Fake
tokens/dids/GPS only; never commit real signed URLs or capture bytes.

1. `chunk_row_json`: ≤50-byte boundaries; offsets contiguous and cover the string
   exactly; single-char tail chunk; reassembly == input.
2. `write_schedule_row` (fake `send_action` capturing every call): asserts one
   `SCHDIV3` header with correct `i`/`l`/`v`; N `SCHDDV3` chunks with correct
   `s`/`l`/`d`, ordered, sharing the header's `v`; one `SCHDSV3` with `i`/`v`(version)/
   `s:[enabled,flag]`; raises `CfgActionError` when a leg returns `r!=0`.
3. `read_schedule_rows`: fake `send_action` returns `m:'r'` chunk responses →
   reassembles the `[slot,enabled,name,b64]` rows.
4. Byte-identical blob regression: `encode_schedule_blob` of the decoded plans for
   `aa07300c0300ed` (Wed 13:00 all-area), `aa085120120002ed` (Fri 09:04 z2 full),
   `aa0902e021000200ed` (Sun 08:00 z2 edge) round-trips byte-for-byte.
5. `write_schedule` (fake cloud): writes via `write_schedule_row` (the new
   transport), **never** calls `write_chunked_key` with `"SCHEDULE"`; skips
   unchanged slots; preserves `enabled`/`flag`; bumps version; refreshes state.
6. `set_schedule_plans` service still resolves the coordinator and reaches
   `write_schedule` with the rebuilt slot list (regression).

## Versioning / release

`manifest.json` 1.0.25a4 → **1.0.25a5** (single-digit alpha bump, no HACS
string-sort ladder issue). On completion: merge to `main`, push, `release.sh`
(tag + GitHub Release + HACS refresh).
