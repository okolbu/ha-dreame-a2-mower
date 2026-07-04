"""Writes-service shared plumbing (layer 4) — refactor-v2 P3.9b.

The WriteResult-construction helpers shared across the writes family
(``schedule`` / ``settings`` / ``tasks`` / ``map_edit``) plus the OTA-trigger
orchestration. Extracted VERBATIM from ``coordinator/_writes.py``; each function
that needs the coordinator takes it (``coord``) as its first argument.

**set_cfg/set_pre/trigger_firmware_update home (P3.9b decision).** The low-level
device WRITERS (``set_cfg`` / ``set_pre`` / ``trigger_firmware_update``) STAY in
the transport layer at ``cloud_client/_writers.py``: they are HTTP/routed-action
calls that reach into the cloud-client's own transport internals (``self.action``,
``self.request``, ``self._did``/``self._uid``/``self._last_send_error_code``).
Moving them into this domain package would force a domain→transport-internals
back-edge — the opposite of the clean split P3.5 landed. Instead the writes
services here ORCHESTRATE those transport writers by calling
``coord._cloud.set_cfg`` / ``.set_pre`` / ``.trigger_firmware_update`` — a legal
domain(4)→transport(2) downward call (``tests/audit/test_layer_imports.py``).
"""
from __future__ import annotations

from ...cloud_client import WriteResult


def _accepted() -> WriteResult:
    """Accepted verdict for a completed device round-trip (out[0].r == 0
    on every leg). Same fields as ``WriteResult.local_ok()`` but named for
    the wire case — ``local_ok`` is reserved for writes with NO round-trip."""
    return WriteResult(delivered=True, accepted=True, code=0)


def _chunked_kv_write_result(ok: bool, response: dict | None) -> WriteResult:
    """Map a ``write_chunked_key`` (iotuserdata setDeviceData) outcome to a
    WriteResult.

    HONEST-SIGNAL CAVEAT: this transport is the cloud KV record store (see
    ``inventory.yaml`` § READ/WRITE SURFACES item 3) — the accept/reject
    verdict is the CLOUD's (``success``/``code``), and there is NO per-write
    device verdict on this channel (nothing like out[0].r exists here). For
    keys where the cloud record is the authoritative store (SETTINGS.*,
    AI_HUMAN.0) the cloud accepting IS the write landing; ``accepted`` here
    claims exactly that and no more.
    """
    if ok:
        return _accepted()
    if response is None:
        # Non-dict / no response — no evidence the cloud stored anything.
        return WriteResult.not_delivered("no response from cloud KV write")
    code = response.get("code")
    msg = str(response.get("msg") or "")
    return WriteResult(
        delivered=True, accepted=False,
        code=code if isinstance(code, int) else None, msg=msg,
    )


def _write_result_from_schedule_exc(exc: Exception) -> WriteResult:
    """Map a SCHD*V3 write exception to an honest WriteResult.

    ``write_schedule_row`` / ``write_schedule_enabled_state`` raise
    ``CfgActionError`` on any failing leg. When the error carries a device
    code (``out[0].r != 0`` — a Dreame application-level rejection) the
    device demonstrably heard the request → delivered-but-rejected. Without
    a code (None result / malformed envelope) there is no evidence of
    delivery → not-delivered (retryable). Any other exception type is a
    transport failure → not-delivered.
    """
    from ...protocol.cfg_action import CfgActionError

    if isinstance(exc, CfgActionError) and exc.code is not None:
        return WriteResult(
            delivered=True, accepted=False, code=exc.code, msg=str(exc)
        )
    return WriteResult.not_delivered(str(exc))


async def async_trigger_firmware_update(coord) -> bool:
    """Fire the OTA "update now" trigger. Returns the device decision
    (False = refused: weak WiFi / charge -- gated device-side)."""
    if not hasattr(coord, "_cloud"):
        return False
    return bool(
        await coord.hass.async_add_executor_job(
            coord._cloud.trigger_firmware_update
        )
    )
