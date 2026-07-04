"""Session-type signal capture (layer 4) — extracted from
``coordinator/_mqtt_handlers.py`` in refactor-v2 P3.7 (autopsy #3 scope #3).

These functions feed the *type* signals of the active ``live_map`` session:

  - s2p50 TASK op (15 manual, 100-103 mow, 108/109 patrol/cruise) — latched
    UNGATED so a dock-launched command's op echo (which arrives ~40s before
    ``begin_session`` exists) survives to type the session.
  - s2p56 multi-target status list — appends per-target task_ids.
  - area-ever-positive mow-evidence latch.
  - patrol-start (s2p2=51) latch (handled in ``lifecycle_events``'s telemetry
    sampler, seeded here at session birth).

The logic is VERBATIM from the pre-split mixin; each function takes the
coordinator (``coord``) as its first argument instead of ``self`` so the
behaviour is identical while the code lives at the domain layer. The
coordinator keeps thin delegating methods for its public surface.
"""
from __future__ import annotations

from typing import Any

from ...const import LOGGER


def capture_session_type_signals(
    live_map,
    *,
    s2p56_status: list | None,
    s2p50_op: int | None,
    area_m2: float | None,
) -> None:
    """Feed mow-evidence / target signals into the active live_map session.

    - s2p56_status: list of [task_id, stage] entries -> append task_ids
      (dedup against the running tail).
    - s2p50_op: TASK op (15 manual, 100-103 mow, 109 cruise).
    - area_m2: latches area_ever_positive when > 0.
    """
    if s2p56_status:
        for entry in s2p56_status:
            if isinstance(entry, list) and entry:
                tid = entry[0]
                if not live_map.target_ids or live_map.target_ids[-1] != tid:
                    live_map.target_ids.append(tid)
    if s2p50_op is not None:
        live_map.last_task_op = s2p50_op
    if area_m2 is not None and area_m2 > 0:
        live_map.area_ever_positive = True


def latch_task_op(coord, op: int) -> None:
    """Record the latest task op (s2p50 echo), ungated by session-active.

    Persisted to the sidecar (last-wins, no window) so it survives a
    restart that lands before begin_session. If a session is already
    active, also set last_task_op directly so a mid-session op change
    (e.g. a new command without docking) is reflected immediately.
    """
    coord._pending_task_op = int(op)
    try:
        coord.session_archive.write_pending_op(int(op))
    except Exception:  # pragma: no cover - sidecar write is best-effort
        LOGGER.exception("_latch_task_op: sidecar write failed")
    if coord.live_map.is_active():
        coord.live_map.last_task_op = int(op)


def handle_task_op_echo(coord, value: Any) -> None:
    """Extract the op from an s2p50 value and latch it.

    s2p50 value is `{"d": {"o": <op>, ...}, ...}`; some payloads carry the
    op flat as `{"o": <op>}`. Non-dict / missing-op payloads are ignored.
    """
    if not isinstance(value, dict):
        return
    # The op can live at the top level (unwrapped echo `{o, exe, status,…}`
    # and the reject echo `{exe, o, status:false}`) OR nested under `d`
    # (wrapped echo `{d:{…o…}, t:"TASK"}`). Prefer the top level, fall back
    # to d.o — this also handles the SEND shape `{m, o, d:{payload}}` where d
    # is the payload (no `o`), which the old `value.get("d") or value` form
    # would have mis-read. (Corpus probe_log_20260520: all three echo shapes.)
    op = value.get("o")
    if op is None:
        inner = value.get("d")
        if isinstance(inner, dict):
            op = inner.get("o")
    if op is None:
        return
    try:
        latch_task_op(coord, int(op))
    except (TypeError, ValueError):
        return


def seed_session_type_from_pending(coord) -> None:
    """Seed live_map type signals from the pending latches at session birth.

    begin_session() nulls last_task_op + saw_patrol_start; this re-stamps
    them from the op echo (s2p50) and patrol-start (s2p2=51) that arrived
    before the session existed. No-op when nothing is latched or no session
    is active.
    """
    if not coord.live_map.is_active():
        return
    if coord._pending_task_op is not None:
        coord.live_map.last_task_op = coord._pending_task_op
    if coord._pending_saw_patrol_start:
        coord.live_map.saw_patrol_start = True
