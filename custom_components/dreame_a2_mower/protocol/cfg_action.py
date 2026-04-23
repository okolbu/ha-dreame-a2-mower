"""Routed-action wrappers for siid:2 aiid:50 calls.

Per apk.md, the Dreame mower exposes most of its CFG/PRE/CMS/etc.
machinery via a single MIoT action endpoint at siid=2 aiid=50.
The `in[0]` payload routes by `m` (mode: 'g'=get, 's'=set, 'a'=action,
'r'=remote) and `t` (target: 'CFG', 'PRE', 'DOCK', 'CMS', ...).

Returns are unwrapped from `result.out[0]` (the cloud envelope).

This module provides typed wrappers but deliberately stays
protocol-only — no HA imports. The device.py layer is responsible
for translating CFG payloads into entity state.
"""

from __future__ import annotations

from typing import Any


# Action endpoint constants per apk decompilation.
ROUTED_ACTION_SIID = 2
ROUTED_ACTION_AIID = 50


class CfgActionError(RuntimeError):
    """Raised when a routed action call returns no data."""


def _unwrap(result: Any) -> Any:
    """Unwrap the cloud envelope. The protocol's send-action path
    returns `{"result": {"out": [<payload>]}}` on success and various
    error shapes on failure. We accept any shape that yields an
    `out[0]` mapping; everything else raises."""
    if not isinstance(result, dict):
        raise CfgActionError(f"unexpected result type: {type(result).__name__}")
    inner = result.get("result", result)  # tolerate flat or nested
    out = inner.get("out") if isinstance(inner, dict) else None
    if not isinstance(out, list) or not out:
        raise CfgActionError(f"action returned no `out`: {result!r}")
    return out[0]


def get_cfg(send_action) -> dict:
    """Fetch the full settings dict (WRP, DND, BAT, CLS, VOL, LIT,
    AOP, REC, STUN, ATA, PATH, WRF, PROT, CMS, PRE, ...).

    `send_action` must be a callable matching the protocol's
    action(siid, aiid, parameters) signature.
    """
    raw = send_action(
        ROUTED_ACTION_SIID, ROUTED_ACTION_AIID, [{"m": "g", "t": "CFG"}]
    )
    payload = _unwrap(raw)
    d = payload.get("d") if isinstance(payload, dict) else None
    if not isinstance(d, dict):
        raise CfgActionError(f"getCFG returned no `d` dict: {payload!r}")
    return d


def get_dock_pos(send_action) -> dict:
    """Fetch dock position + lawn-connection status."""
    raw = send_action(
        ROUTED_ACTION_SIID, ROUTED_ACTION_AIID, [{"m": "g", "t": "DOCK"}]
    )
    payload = _unwrap(raw)
    d = payload.get("d") if isinstance(payload, dict) else None
    if not isinstance(d, dict):
        raise CfgActionError(f"getDockPos returned no `d` dict: {payload!r}")
    dock = d.get("dock")
    if not isinstance(dock, dict):
        raise CfgActionError(f"getDockPos: missing dock subkey: {d!r}")
    return dock


def set_pre(send_action, pre_array: list) -> Any:
    """Write the PRE preferences array. Caller is responsible for
    read-modify-write semantics (read CFG.PRE, modify the slot,
    pass the full updated array here)."""
    if not isinstance(pre_array, list) or len(pre_array) < 10:
        raise ValueError(
            f"PRE array must have at least 10 elements, got {len(pre_array) if isinstance(pre_array, list) else type(pre_array).__name__}"
        )
    return send_action(
        ROUTED_ACTION_SIID,
        ROUTED_ACTION_AIID,
        [{"m": "s", "t": "PRE", "d": {"value": pre_array}}],
    )


def call_action_op(send_action, op: int, extra: dict | None = None) -> Any:
    """Invoke an action opcode (`{m:'a', p:0, o:OP, ...}`).

    Per apk § "Actions", op 100 = globalMower, 101 = edgeMower,
    102 = zoneMower, 110 = startLearningMap, 11 = suppressFault,
    9 = findBot, 12 = lockBot, 401 = takePic, 503 = cutterBias.
    The extra dict (if given) is merged into the payload — for
    zoneMower this is `{region: [zone_id]}`.
    """
    payload: dict = {"m": "a", "p": 0, "o": int(op)}
    if extra:
        payload.update(extra)
    return send_action(ROUTED_ACTION_SIID, ROUTED_ACTION_AIID, [payload])
