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


def read_schedule_rows(send_action) -> list[list]:
    """Read the authoritative schedule rows for RMW.

    Probes SCHDTV3; the unwrapped payload's `d.rows` carries the
    [slot, enabled, name, b64blob] rows (the relay reassembles chunks on read).
    Returns [] on any malformed/empty response.
    """
    try:
        raw = send_action(ROUTED_ACTION_SIID, ROUTED_ACTION_AIID,
                          [{"m": "r", "t": "SCHDTV3"}])
        payload = _unwrap(raw)
    except CfgActionError:
        return []
    d = payload.get("d") if isinstance(payload, dict) else None
    rows = d.get("rows") if isinstance(d, dict) else None
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, list) and len(r) == 4]
