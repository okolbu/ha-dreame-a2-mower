"""Schedule-write service (layer 4) — refactor-v2 P3.9b.

The SCHD*V3 schedule-write family, extracted VERBATIM from
``coordinator/_writes.py``: the per-slot diff-and-write (``write_schedule``) and
the standalone season enable/disable (``write_schedule_enabled``). Each function
takes the coordinator (``coord``) as its first argument; cross-method calls stay
``coord.<method>`` so the coordinator's public/test surface + monkeypatches are
preserved. (The monotonic txn-id generator stays on ``_WritesMixin`` — it reads
the coordinator-private lazy ``_last_schedule_txn_id`` via ``getattr`` default,
which a domain module can't do without tripping the private-getattr gate.)
"""
from __future__ import annotations

from typing import Any

from ...const import LOGGER
from ...cloud_client import WriteResult
from ...protocol.schedule_action import (
    read_live_schedule,
    write_schedule_enabled_state,
    write_schedule_row,
)
from ...protocol.schedule_encode import encode_schedule_blob

from .service import _accepted, _write_result_from_schedule_exc


async def write_schedule(
    coord,
    new_slots: tuple[Any, ...] | list[Any],
) -> WriteResult:
    """Push changed schedule slots to the device via the SCHD*V3 transport.

    new_slots is a sequence of ScheduleSlot dataclasses (.plans is the
    source of truth; .raw_blob_b64 is ignored — re-encoded). Reads the
    authoritative rows, writes only slots whose re-encoded blob or name
    changed, preserving each slot's enabled state, bumping the schedule
    version. The SCHEDULE.* KV is intentionally NOT written (the device
    ignores it; see dreame-app-schedule-write-2026-06-10.md).

    Returns a :class:`WriteResult` (P2 Task 5 — was a bool): accepted when
    every changed slot's SCHD*V3 transaction was accepted; otherwise the
    FIRST failing slot's verdict (a ``CfgActionError`` with a device code
    → delivered-but-rejected; without one → not-delivered). A no-op write
    (all slots unchanged) is trivially accepted.
    """
    if not hasattr(coord, "_cloud") or coord._cloud is None:
        LOGGER.warning("write_schedule: cloud client not ready")
        return WriteResult.not_delivered("cloud client not ready")

    # Read the authoritative LIVE schedule once (rows for the skip-gate +
    # the live version to bump). The SCHEDULE.* KV / cloud_state.version is
    # a stale cache, so deriving the base version from it could emit a
    # new_version BELOW the device's current and get the write rejected
    # (verified 2026-06-17: KV v=35477 vs live v=58177).
    live = await coord.hass.async_add_executor_job(
        read_live_schedule, coord._cloud.action
    )
    if live is not None:
        rows = live.get("d") or []
        base_version = int(live.get("v") or 0)
    else:
        rows = []
        cs = coord.cloud_state
        base_version = cs.schedule.version if cs is not None else 0
    new_version = base_version + 1

    by_slot = {
        r[0]: r for r in rows if isinstance(r, list) and len(r) == 4
    }
    # SCHDSV3 `s` is the FULL per-slot enabled array; build it once from the
    # live rows so editing one season's plans preserves the OTHER season's
    # on/off (sending [thisslot, 0] would flip the active season).
    # Absent slot → 0 (disabled): a never-configured slot is off on the
    # device, and defaulting to 1 would wrongly enable it.
    enabled_array = [
        int(by_slot[i][1]) if i in by_slot else 0 for i in (0, 1)
    ]

    failure: WriteResult | None = None
    async with coord._chunked_write_lock:
        for slot in new_slots:
            blob_b64 = encode_schedule_blob(tuple(slot.plans))
            # Name is HTML-escaped on the wire — only `&` (the device read
            # row carries `Spr &amp; Sum`); `<`/`>`/`"` appear unescaped.
            # decode does html.unescape, so compare AND write the escaped
            # form, else `&`-names never match the skip gate and drift via
            # double-escape on each save.
            wire_name = (slot.name or "").replace("&", "&amp;")
            prev = by_slot.get(slot.slot_id)
            prev_blob = prev[3] if prev else None
            prev_name = prev[2] if prev else None
            if (
                prev is not None
                and blob_b64 == prev_blob
                and wire_name == prev_name
            ):
                continue  # unchanged — skip (idempotent, no version churn)
            txn_id = coord._next_schedule_txn_id()
            try:
                await coord.hass.async_add_executor_job(
                    lambda s=slot, b=blob_b64, t=txn_id, n=wire_name, ea=enabled_array: write_schedule_row(
                        coord._cloud.action,
                        slot=s.slot_id,
                        enabled_array=ea,
                        name=n,
                        blob_b64=b,
                        version=new_version,
                        txn_id=t,
                    )
                )
                LOGGER.info(
                    "[schedule-write] slot %d, %d plan(s), v→%d, blob_len=%d",
                    slot.slot_id, len(slot.plans), new_version, len(blob_b64),
                )
            except Exception as exc:  # noqa: BLE001 — surface, keep going
                if failure is None:
                    failure = _write_result_from_schedule_exc(exc)
                LOGGER.warning(
                    "[schedule-write] slot %d rejected: %r", slot.slot_id, exc
                )

    await coord._refresh_cloud_state()
    return failure if failure is not None else _accepted()


async def write_schedule_enabled(
    coord, slot_id: int, enabled: bool
) -> WriteResult:
    """Enable or disable one schedule season via a standalone SCHDSV3 write.

    Seasons are mutually exclusive (device-enforced): enabling a slot makes
    it the sole active one; disabling a slot sets it off (and, since only one
    is ever on, leaves no schedule running). Reads the live schedule for the
    fresh version + current enabled states, then writes the full array.

    Does NOT guard against an active task — the service layer does (it owns
    the user-facing ServiceValidationError).

    Returns a :class:`WriteResult` (P2 Task 5 — was a bool); see
    ``write_schedule`` for the exception→verdict mapping.
    """
    if not hasattr(coord, "_cloud") or coord._cloud is None:
        LOGGER.warning("write_schedule_enabled: cloud client not ready")
        return WriteResult.not_delivered("cloud client not ready")

    live = await coord.hass.async_add_executor_job(
        read_live_schedule, coord._cloud.action
    )
    if live is not None:
        rows = live.get("d") or []
        version = int(live.get("v") or 0)
        by_slot = {r[0]: r for r in rows if isinstance(r, list) and len(r) == 4}
        current = [int(by_slot[i][1]) if i in by_slot else 0 for i in (0, 1)]
    else:
        cs = coord.cloud_state
        version = cs.schedule.version if cs is not None else 0
        current = [0, 0]
        if cs is not None:
            for s in cs.schedule.slots:
                if s.slot_id in (0, 1):
                    # s.mode / wire element[1] is the per-slot enabled flag (confirmed app-mitm 2026-06-17).
                    current[s.slot_id] = int(s.mode)

    if enabled:
        new_array = [1 if i == slot_id else 0 for i in (0, 1)]  # sole active
    else:
        new_array = list(current)
        if slot_id in (0, 1):
            new_array[slot_id] = 0

    result = _accepted()
    async with coord._chunked_write_lock:
        try:
            await coord.hass.async_add_executor_job(
                lambda v=version, a=new_array: write_schedule_enabled_state(
                    coord._cloud.action, version=v, enabled_array=a
                )
            )
            LOGGER.info(
                "[schedule-enable] slot %d → %s, s=%s, v=%d",
                slot_id, "on" if enabled else "off", new_array, version,
            )
        except Exception as exc:  # noqa: BLE001 — surface, keep going
            result = _write_result_from_schedule_exc(exc)
            LOGGER.warning("[schedule-enable] slot %d rejected: %r", slot_id, exc)

    await coord._refresh_cloud_state()
    return result
