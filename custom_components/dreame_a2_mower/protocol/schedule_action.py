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
