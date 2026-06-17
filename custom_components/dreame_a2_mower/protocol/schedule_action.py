"""Routed-action transport for the device-plane schedule (SCHD*V3).

The authoritative schedule write is NOT the SCHEDULE.* iotuserdata KV (that is
only the app's cache mirror, which the device ignores). It is a chunked
transaction over siid:2/aiid:50: a SCHDIV3 header, N SCHDDV3 data chunks
(<=50 bytes, sharing one txn id), then a SCHDSV3 state write.

Wire facts: dreame-app-schedule-write-2026-06-10.md (app<->mower MITM).
Protocol-only — no HA imports.
"""
from __future__ import annotations

import json
from typing import Any

from .cfg_action import (  # noqa: F401  (re-exported error type for callers)
    ROUTED_ACTION_AIID,
    ROUTED_ACTION_SIID,
    CfgActionError,
    _unwrap,
)

CHUNK_SIZE = 50


def chunk_row_json(row_json: str) -> list[tuple[int, str]]:
    """Split row_json into (offset, chunk) pairs of <=CHUNK_SIZE bytes.

    Offsets are byte offsets into the UTF-8 encoding, contiguous, covering the
    whole string exactly once. Our row JSON is ASCII (base64 + digits + simple
    names), so byte offset == char offset; we slice on bytes to stay exact.
    """
    raw = row_json.encode("utf-8")
    out: list[tuple[int, str]] = []
    for off in range(0, len(raw), CHUNK_SIZE):
        out.append((off, raw[off:off + CHUNK_SIZE].decode("utf-8")))
    return out


def _send(send_action, t: str, d: Any) -> None:
    """Fire one routed-action leg and raise if the device rejects it."""
    raw = send_action(ROUTED_ACTION_SIID, ROUTED_ACTION_AIID, [{"m": "s", "t": t, "d": d}])
    _unwrap(raw)  # raises CfgActionError on r!=0 / malformed envelope


def write_schedule_row(
    send_action,
    *,
    slot: int,
    enabled: int,
    name: str,
    blob_b64: str,
    version: int,
    flag: int,
    txn_id: int,
) -> None:
    """Write one schedule slot row via the chunked SCHD*V3 transaction.

    Order: SCHDIV3 header -> N SCHDDV3 chunks (shared txn_id) -> SCHDSV3 state.
    `version` is the schedule version (SCHDSV3 `v`); `txn_id` is the shared
    header/chunk `v`. Raises CfgActionError if any leg returns r!=0.
    """
    row_json = json.dumps([slot, enabled, name, blob_b64], separators=(",", ":"))
    total_len = len(row_json.encode("utf-8"))
    _send(send_action, "SCHDIV3", {"i": slot, "l": total_len, "v": txn_id})
    for off, chunk in chunk_row_json(row_json):
        _send(send_action, "SCHDDV3",
              {"s": off, "l": len(chunk.encode("utf-8")), "d": chunk, "v": txn_id})
    _send(send_action, "SCHDSV3", {"i": slot, "v": version, "s": [enabled, flag]})


# Max bytes requested per SCHDDV3 read chunk (matches the app's request size).
READ_CHUNK = 100
# Guard against a device that never advances the offset (avoid an infinite loop).
_MAX_READ_CHUNKS = 64


def read_live_schedule(send_action) -> dict | None:
    """Read the authoritative LIVE schedule via the SCHDIV3->SCHDDV3 chunked GET.

    The cloud SCHEDULE.* iotuserdata KV is a stale cache that app schedule edits
    do NOT write back; the live schedule is read with m:'g' over siid:2/aiid:50,
    the inverse of :func:`write_schedule_row`:

      1. SCHDIV3 {i:0}            -> {i:0, l:<total bytes>, v:<version>}
      2. SCHDDV3 {s, l, v} (loop) -> {d:<chunk str>, l:<bytes>, s:<offset>, v}

    The data-chunk offset `s` is advanced by the device-reported `l` until it
    reaches the header's total `l`; the chunk `d` strings are concatenated in
    order and JSON-parsed to ``{"d": [[slot, enabled, name, b64blob], ...],
    "v": <version>}`` — the shape :func:`parse_schedule_batch` /
    ``schedule_decode.py`` already consume.

    Returns that dict on success, or ``None`` on any malformed/empty/rejected
    response (the caller falls back to the stale SCHEDULE.* KV). Synchronous
    over the cloud relay; m:'g' is required (m:'r' returns no payload).

    Wire-verified [app-mitm:2026-06-17] + live cloud-relay run 2026-06-17.
    """
    try:
        hdr = _unwrap(send_action(
            ROUTED_ACTION_SIID, ROUTED_ACTION_AIID,
            [{"m": "g", "t": "SCHDIV3", "d": {"i": 0}}],
        ))
    except CfgActionError:
        return None
    hd = hdr.get("d") if isinstance(hdr, dict) else None
    if not isinstance(hd, dict):
        return None
    try:
        total = int(hd["l"])
        version = int(hd["v"])
    except (KeyError, TypeError, ValueError):
        return None
    if total <= 0:
        return None

    buf = ""
    consumed = 0
    guard = 0
    while consumed < total:
        guard += 1
        if guard > _MAX_READ_CHUNKS:
            return None
        want = min(READ_CHUNK, total - consumed)
        try:
            cp = _unwrap(send_action(
                ROUTED_ACTION_SIID, ROUTED_ACTION_AIID,
                [{"m": "g", "t": "SCHDDV3",
                  "d": {"s": consumed, "l": want, "v": version}}],
            ))
        except CfgActionError:
            return None
        cd = cp.get("d") if isinstance(cp, dict) else None
        if not isinstance(cd, dict):
            return None
        chunk = cd.get("d")
        ln = cd.get("l")
        if (
            not isinstance(chunk, str)
            or not isinstance(ln, int)
            or isinstance(ln, bool)
            or ln <= 0
        ):
            return None
        buf += chunk
        consumed += ln

    try:
        obj = json.loads(buf)
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(obj, dict) or not isinstance(obj.get("d"), list):
        return None
    return obj


def read_schedule_rows(send_action) -> list[list]:
    """Read the authoritative live schedule rows for RMW.

    Thin wrapper over :func:`read_live_schedule` returning just the
    ``[slot, enabled, name, b64blob]`` rows. Returns ``[]`` on any failure.
    """
    obj = read_live_schedule(send_action)
    rows = obj.get("d") if isinstance(obj, dict) else None
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, list) and len(r) == 4]
