"""Pure read-modify-write builders for CFG single-key write payloads.

CFG keys READ back from the cloud as positional lists but WRITE as named
dicts (confirmed by the 2026-06-09 app-MITM capture). Each builder takes the
raw read list (``cloud_state.cfg[KEY]``) plus the field(s) being changed and
returns the exact ``d``-payload the app sends, preserving every slot not
being changed (including undecoded ones: WRP ``sen``, LIT ``fill``, BAT
``flag``, REC ``mode``/``report``).

Returns ``None`` when the raw base is missing/too short to RMW safely — the
caller must then revert its optimistic update rather than send a partial
payload that would wipe undecoded fields.

Read↔write field maps (capture 2026-06-09):
  WRP  read [value, time]            -> {value, time, sen}
  DND  read [value, start, end]      -> {value, time:[start,end]}
  LOW  read [value, start, end]      -> {value, time:[start,end]}
  BAT  read [recharge,resume,flag,custom_en,start,end]
       charging -> {type:"charging", value:[custom_en,start,end]}
       power    -> {type:"power",    value:[recharge,resume,flag]}
  LIT  read [value,start,end,standby,working,charging,error,fill]
       -> {value, time:[start,end], light:[standby,working,charging,error], fill}
  REC  read [value,sen,m0,m1,m2,m3,r0,r1,r2]
       -> {value, sen, mode:[m0..m3], report:[r0..r2]}
  LANG read [text, voice]            -> {type:"voice"|"text", value}
"""
from __future__ import annotations

from typing import Any


def _i(x: Any) -> int:
    return int(bool(x)) if isinstance(x, bool) else int(x)


def build_wrp(raw: Any, *, value: bool | None = None, time: int | None = None) -> dict | None:
    if not raw or len(raw) < 2:
        return None
    cur_value, cur_time = raw[0], raw[1]
    sen = raw[2] if len(raw) > 2 else 1  # sen absent from read; default observed 1
    return {
        "value": _i(value) if value is not None else _i(cur_value),
        "time": int(time) if time is not None else int(cur_time),
        "sen": int(sen),
    }


def _build_window(raw: Any, *, value: bool | None, start: int | None, end: int | None) -> dict | None:
    if not raw or len(raw) < 3:
        return None
    cur_value, cur_start, cur_end = raw[0], raw[1], raw[2]
    return {
        "value": _i(value) if value is not None else _i(cur_value),
        "time": [
            int(start) if start is not None else int(cur_start),
            int(end) if end is not None else int(cur_end),
        ],
    }


def build_dnd(raw: Any, *, value: bool | None = None, start: int | None = None, end: int | None = None) -> dict | None:
    return _build_window(raw, value=value, start=start, end=end)


def build_low(raw: Any, *, value: bool | None = None, start: int | None = None, end: int | None = None) -> dict | None:
    return _build_window(raw, value=value, start=start, end=end)


def build_bat_charging(raw: Any, *, enabled: bool | None = None, start: int | None = None, end: int | None = None) -> dict | None:
    if not raw or len(raw) < 6:
        return None
    custom_en, cur_start, cur_end = raw[3], raw[4], raw[5]
    return {"type": "charging", "value": [
        _i(enabled) if enabled is not None else _i(custom_en),
        int(start) if start is not None else int(cur_start),
        int(end) if end is not None else int(cur_end),
    ]}


def build_bat_power(raw: Any, *, recharge: int | None = None, resume: int | None = None) -> dict | None:
    if not raw or len(raw) < 3:
        return None
    cur_recharge, cur_resume, flag = raw[0], raw[1], raw[2]
    return {"type": "power", "value": [
        int(recharge) if recharge is not None else int(cur_recharge),
        int(resume) if resume is not None else int(cur_resume),
        int(flag),
    ]}


def build_lit(
    raw: Any, *, value: bool | None = None, start: int | None = None, end: int | None = None,
    standby: bool | None = None, working: bool | None = None,
    charging: bool | None = None, error: bool | None = None,
) -> dict | None:
    if not raw or len(raw) < 8:
        return None
    light = [raw[3], raw[4], raw[5], raw[6]]
    for idx, ch in ((0, standby), (1, working), (2, charging), (3, error)):
        if ch is not None:
            light[idx] = _i(ch)
    return {
        "value": _i(value) if value is not None else _i(raw[0]),
        "time": [int(start) if start is not None else int(raw[1]),
                 int(end) if end is not None else int(raw[2])],
        "light": [int(x) for x in light],
        "fill": int(raw[7]),
    }


def build_rec(raw: Any, *, value: bool | None = None, sen: int | None = None) -> dict | None:
    if not raw or len(raw) < 9:
        return None
    return {
        "value": _i(value) if value is not None else _i(raw[0]),
        "sen": int(sen) if sen is not None else int(raw[1]),
        "mode": [int(raw[2]), int(raw[3]), int(raw[4]), int(raw[5])],
        "report": [int(raw[6]), int(raw[7]), int(raw[8])],
    }


def build_lang(raw: Any, *, kind: str, value: int) -> dict | None:
    if kind not in ("voice", "text"):
        return None
    return {"type": kind, "value": int(value)}
