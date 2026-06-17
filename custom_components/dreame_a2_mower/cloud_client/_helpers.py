"""Shared module-level helpers for the cloud_client package (B1d split)."""
from __future__ import annotations

import json
import logging
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

_LOGGER = logging.getLogger("custom_components.dreame_a2_mower.cloud_client")

T = TypeVar("T")

# --- Wire-send trace (debugging instrument; ships OFF) ----------------------
# When the sentinel file exists, every siid=2/aiid=50 action send (every
# routed_action and set_cfg) is appended as one JSONL record to the trace file.
# This captures the EXACT on-wire `in[0]` payload + the device's response so it
# can be diffed against the app↔mower MITM captures (the app does an operation
# that sticks; we do one that doesn't — the diff is in the bytes).
#
# Enable on the live box without a code change or restart: `touch` the sentinel
# (the check is per-call). Ships safe: no sentinel → zero overhead beyond one
# stat per action, and actions are low-volume (writes only).
_WIRE_TRACE_SENTINEL = "/config/dreame_a2_wire_trace.enabled"
_WIRE_TRACE_PATH = "/config/dreame_a2_wire_trace.jsonl"
_WIRE_TRACE_MAX_BYTES = 4_000_000  # rotate to .1 past this, so it can't fill disk


def wire_trace_enabled() -> bool:
    """True when the operator has dropped the trace sentinel file."""
    try:
        return os.path.exists(_WIRE_TRACE_SENTINEL)
    except OSError:
        return False


def wire_trace(record: dict[str, Any]) -> None:
    """Best-effort append one JSONL trace record. NEVER raises into a write.

    No-op unless the sentinel exists. ``default=repr`` keeps non-JSON values
    (e.g. an exception object) from breaking the line; a single oversized file
    is rotated to ``<path>.1`` rather than growing without bound.
    """
    if not wire_trace_enabled():
        return
    try:
        try:
            if os.path.getsize(_WIRE_TRACE_PATH) > _WIRE_TRACE_MAX_BYTES:
                os.replace(_WIRE_TRACE_PATH, _WIRE_TRACE_PATH + ".1")
        except OSError:
            pass  # file absent / not yet created — nothing to rotate
        line = json.dumps(record, separators=(",", ":"), default=repr)
        with open(_WIRE_TRACE_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:  # noqa: BLE001 — tracing must never break a real write
        pass


@dataclass(frozen=True)
class WriteResult:
    """Honest outcome of a device-ACTION write (routed_action / dispatch_action).

    The cloud relay's top-level HTTP ``code`` is always 0 on a reachable cloud
    even when the *device* rejects the action — the real verdict is in
    ``out[0].r``. This envelope carries both the transport-delivery fact and the
    device-acceptance fact so callers can distinguish "the mower never heard it"
    (retryable / asleep) from "the mower heard it and said no" (permanent).

    Fields:
      - ``delivered`` — the cloud relay returned a payload (not None / not 80001).
      - ``accepted``  — delivered AND ``out[0].r == 0`` (device actually did it).
      - ``code``      — ``out[0].r`` when delivered; else the transport error code
                        (80001 / ``_last_send_error_code`` / None).
      - ``msg``       — ``out[0].msg``/``e`` when delivered+rejected; a transport
                        note otherwise.
    """

    delivered: bool
    accepted: bool
    code: int | None
    msg: str = ""

    @property
    def ok(self) -> bool:
        """Convenience for callers that only care about success."""
        return self.accepted

    def __bool__(self) -> bool:
        """Truthiness == accepted.

        Load-bearing: legacy callers wrote ``if result:`` / ``bool(leg)`` against
        the raw device dict (truthy on mere delivery). Tying ``__bool__`` to
        ``accepted`` keeps ``edit_map``'s ``ok = ok and bool(leg_result)``
        correct after the swap — a delivered-but-rejected leg now reads falsy.
        """
        return self.accepted

    @classmethod
    def local_ok(cls) -> "WriteResult":
        """Synthetic accepted result for a write with no device round-trip.

        Used for local-only actions and the no-op map-switch branch — there's
        nothing to ask the device, so the write trivially succeeds
        (delivered + accepted, code 0).
        """
        return cls(delivered=True, accepted=True, code=0)

    @classmethod
    def not_delivered(cls, msg: str = "") -> "WriteResult":
        """Synthetic not-delivered result (the mower never heard the command).

        ``code`` is left ``None`` because no transport/device code was read —
        consistent with every other synthetic not-accepted result.
        """
        return cls(delivered=False, accepted=False, code=None, msg=msg)


def _http_retry(
    action: Callable[[], T],
    *,
    max_attempts: int,
    delay_s: float = 0.0,
    should_retry: Callable[[BaseException], bool] = lambda _exc: True,
) -> T:
    """Run action() up to max_attempts times, retrying on exception.

    Semantics:
      - max_attempts must be >= 1 (raises ValueError otherwise).
      - On success: return action()'s return value immediately.
      - On exception: if should_retry(exc) returns True AND attempts
        remain, sleep delay_s and retry. Otherwise re-raise.
      - delay_s == 0 (default): no sleep between attempts.

    Helper uses blocking time.sleep — by design, since callers run in
    executor threads.
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1, got {max_attempts}")
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return action()
        except Exception as exc:
            # NB: catch Exception, NOT BaseException — KeyboardInterrupt,
            # SystemExit, and asyncio.CancelledError must propagate (a
            # cancelled executor task should not be retried for ~24s).
            last_exc = exc
            if not should_retry(exc):
                raise
            if attempt < max_attempts - 1 and delay_s > 0:
                time.sleep(delay_s)
    assert last_exc is not None  # unreachable: loop always raises or returns
    raise last_exc


def _random_agent_id() -> str:
    """Return a 13-char uppercase-hex random string used in the MQTT client-id.

    Mirrors legacy ``dreame/protocol.py`` ``_random_agent_id()``.
    """
    letters = "ABCDEF"
    return "".join(random.choice(letters) for _ in range(13))
