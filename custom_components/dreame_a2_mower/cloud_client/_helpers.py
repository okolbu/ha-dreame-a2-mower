"""Shared module-level helpers for the cloud_client package (B1d split)."""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

_LOGGER = logging.getLogger("custom_components.dreame_a2_mower.cloud_client")

T = TypeVar("T")


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
