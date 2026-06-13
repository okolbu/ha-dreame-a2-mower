"""Map a :class:`WriteResult` to an HA exception for user surfacing (Task B).

Task A plumbed the honest device verdict (a ``WriteResult``) up to every write
entry point but nothing raised — a rejected Start/zone/map-edit still looked
like success. This helper is the single place that turns a not-accepted result
into an exception so service calls and UI controls show an error instead of a
silent no-op.

Two distinctions matter:

  - **not delivered** (the mower never heard the command — asleep / 80001 /
    transport drop) is *retryable*; the message says "try again". This is the
    same class for both service and entity callers.
  - **delivered but rejected** (the device heard it and said no — ``out[0].r``
    != 0, e.g. ``-3`` "not supported / bad request") is *permanent*. In a
    service-call context this is a ``ServiceValidationError`` (a bad request the
    user should fix, not retry); in an entity context (button / lawn_mower)
    ``ServiceValidationError`` is not appropriate (it's service-only), so we
    raise a plain ``HomeAssistantError`` carrying the same message.

``accepted`` results return without raising (the happy path).
"""
from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from ..cloud_client import WriteResult


def _rejected_message(result: WriteResult, action_label: str) -> str:
    """Build the 'device rejected' message, appending msg when present."""
    suffix = f": {result.msg}" if result.msg else ""
    return (
        f"{action_label}: device rejected the command "
        f"(code {result.code}{suffix})"
    )


def raise_for_write_result(
    result: WriteResult,
    action_label: str,
    *,
    context: str = "service",
) -> None:
    """Raise the appropriate HA exception when ``result`` is not accepted.

    Args:
      result: the honest device verdict from ``dispatch_action`` / a coordinator
        write method.
      action_label: human label for the attempted command (e.g. ``"Mow zone"``,
        ``"Start mowing"``) — prefixes every message.
      context: ``"service"`` (default) raises ``ServiceValidationError`` for a
        delivered-but-rejected result; ``"entity"`` (button / lawn_mower) raises
        ``HomeAssistantError`` instead, since ``ServiceValidationError`` is
        service-call-only.

    Returns ``None`` (no raise) when ``result.accepted`` is True.
    """
    if result.accepted:
        return

    if not result.delivered:
        # Transport / asleep — retryable. Same class for service and entity.
        raise HomeAssistantError(
            f"{action_label}: not delivered — the mower may be "
            f"asleep/unreachable (code {result.code}). Try again."
        )

    # delivered and not accepted — the device actively rejected it.
    message = _rejected_message(result, action_label)
    if context == "service":
        raise ServiceValidationError(message)
    raise HomeAssistantError(message)
