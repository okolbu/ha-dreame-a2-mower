# Phase A1 — CFG writable settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the read-only CFG single-key "More Settings" controls (WRP/DND/LOW/BAT/LIT/REC/LANG) write to the mower using the app's exact captured envelopes, flip their `control_mode` to `DEVICE_WRITABLE`, and confirm the already-writable CFG keys' transport matches the capture.

**Architecture:** A new pure module `protocol/cfg_payloads.py` holds per-key read-modify-write builders that take the raw `cloud_state.cfg[KEY]` list and the changed field(s) and return the app's exact write-dict, preserving undecoded slots. Entity descriptors gain a `build_from_cfg_fn` hook; the handler RMWs from raw cfg and reverts if no base exists. Verdicts flip to `DEVICE_WRITABLE`. The existing `set_cfg` transport is unchanged (already matches the capture).

**Tech Stack:** Python, the repo's vanilla pytest venv (`/data/claude/homeassistant/.venv-vanilla/bin/python`), inventory validators (`tools/inventory/*`).

**Spec:** `docs/superpowers/specs/2026-06-10-phase-a1-cfg-writable-settings-design.md`

**Key reference data (captured 2026-06-09; read↔write asymmetry — CFG reads as positional lists, writes as named dicts):**

| Key | READ list (cloud_state.cfg[KEY]) | WRITE `d`-payload (app capture) |
|---|---|---|
| WRP | `[value, time]` (sen absent in read) | `{"value":V, "time":T, "sen":S}` |
| DND | `[value, start, end]` | `{"value":V, "time":[start,end]}` |
| LOW | `[value, start, end]` | `{"value":V, "time":[start,end]}` |
| BAT | `[recharge, resume, flag, custom_en, start, end]` | charging: `{"type":"charging","value":[custom_en,start,end]}` · power: `{"type":"power","value":[recharge,resume,flag]}` |
| LIT | `[value, start, end, standby, working, charging, error, fill]` | `{"value":V,"time":[start,end],"light":[standby,working,charging,error],"fill":F}` |
| REC | `[value, sen, m0,m1,m2,m3, r0,r1,r2]` | `{"value":V,"sen":S,"mode":[m0,m1,m2,m3],"report":[r0,r1,r2]}` |
| LANG | `[text, voice]` | `{"type":"voice"\|"text","value":idx}` |

**Audit finding (already done during planning):** `set_cfg` wraps non-dict values as `{"value":X}` and sends dicts directly — this already matches the capture for every already-writable key (ATA `{value:[1,0,0]}`, MSG_ALERT/VOICE `{value:[...]}`, VOL/PROT/CLS/FDP/STUN/AOP `{value:N}`). So **no `set_cfg` change is needed**; the already-writable keys get a confirming inventory verification only (Task 9), no code change.

**Conventions for every task:**
- Python interpreter: `/data/claude/homeassistant/.venv-vanilla/bin/python` (`python` on PATH is broken).
- Run a single test: `… -m pytest <path>::<name> -v`.
- Stage commits by explicit path (a concurrent process commits to this repo; never `git add -A`).
- End commit messages with the Co-Authored-By trailer for Claude Opus 4.8.
- Branch is already `phase-a1-cfg-writable-settings`.

---

### Task 1: Scrubbed capture fixture (test oracle)

**Files:**
- Create: `tests/fixtures/cfg_envelopes_2026-06-09.json`

The private capture (`/data/claude/homeassistant/dreame-app-capture-2026-06-09/`) is off-GitHub. Extract the non-secret CFG write `d`-payloads and the read lists into a committed fixture so tests don't depend on the capture.

- [ ] **Step 1: Create the fixture file** with the captured shapes (verbatim from the capture; these are the values already extracted during planning):

```json
{
  "_source": "dreame-app-capture-2026-06-09/miio-cloud-13267-http.jsonl (private, off-GitHub); non-secret CFG setting envelopes only",
  "writes": {
    "WRP":  {"value": 0, "time": 4, "sen": 1},
    "DND":  {"value": 1, "time": [1260, 420]},
    "LOW":  {"value": 0, "time": [1200, 480]},
    "BAT_charging": {"type": "charging", "value": [0, 1080, 480]},
    "BAT_power":    {"type": "power", "value": [15, 95, 1]},
    "LIT":  {"value": 1, "time": [480, 1200], "light": [1, 1, 1, 1], "fill": 1},
    "REC":  {"value": 0, "sen": 1, "mode": [1, 1, 1, 1], "report": [0, 1, 3]},
    "LANG_voice": {"type": "voice", "value": 0},
    "LANG_text":  {"type": "text", "value": 7},
    "PROT": {"value": 1}, "CLS": {"value": 1}, "ATA": {"value": [1, 0, 0]},
    "FDP": {"value": 0}, "STUN": {"value": 0}, "AOP": {"value": 0},
    "MSG_ALERT": {"value": [0, 1, 1, 1]}, "VOICE": {"value": [0, 1, 1, 1]}, "VOL": {"value": 51}
  },
  "reads": {
    "WRP": [1, 4],
    "DND": [0, 1260, 420],
    "LOW": [1, 1200, 480],
    "BAT": [15, 95, 1, 1, 1080, 480],
    "LIT": [0, 480, 1200, 1, 1, 1, 1, 1],
    "REC": [1, 1, 1, 1, 1, 1, 0, 1, 3],
    "LANG": [7, 7]
  }
}
```

> NOTE: `BAT_power` value `[15,95,1]` is `[recharge,resume,flag]` derived from the read list `[15,95,1,…]`; no standalone BAT power write was captured (the captured BAT write was the charging type). The power-type shape is from the inventory-confirmed `{type:"power",value:[recharge%,resume%,flag]}`. Mark this one as inventory-confirmed, not capture-verbatim, in a `_notes` key if you wish.

- [ ] **Step 2: Commit**

```bash
git add tests/fixtures/cfg_envelopes_2026-06-09.json
git commit -m "test(a1): scrubbed CFG envelope fixture from 2026-06-09 capture

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `cfg_payloads.py` builders (the core, TDD)

**Files:**
- Create: `custom_components/dreame_a2_mower/protocol/cfg_payloads.py`
- Test: `tests/protocol/test_cfg_payloads.py`

All builders are pure: `(raw_read_list, **changes) -> dict | None`. They RMW from the raw read list, preserving every slot not being changed. Return `None` when `raw` is falsy/too short to RMW safely (caller reverts — see Task 3).

- [ ] **Step 1: Write the failing test** (`tests/protocol/test_cfg_payloads.py`):

```python
import json
from pathlib import Path

import pytest

from custom_components.dreame_a2_mower.protocol import cfg_payloads as cp

_FIX = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "cfg_envelopes_2026-06-09.json").read_text()
)
READS = _FIX["reads"]
WRITES = _FIX["writes"]


def test_build_dnd_matches_capture():
    # read [0,1260,420]; capture write set value=1 keeping time
    out = cp.build_dnd(READS["DND"], value=True)
    assert out == {"value": 1, "time": [1260, 420]}


def test_build_dnd_changes_time_preserves_value():
    out = cp.build_dnd(READS["DND"], start=1260, end=420)
    assert out == {"value": 0, "time": [1260, 420]}


def test_build_low_matches_capture():
    out = cp.build_low(READS["LOW"], value=False)
    assert out == {"value": 0, "time": [1200, 480]}


def test_build_wrp_preserves_sen_and_defaults():
    # read [1,4] has no sen -> default sen=1 (observed); set value off
    out = cp.build_wrp(READS["WRP"], value=False)
    assert out == {"value": 0, "time": 4, "sen": 1}


def test_build_wrp_change_time():
    out = cp.build_wrp(READS["WRP"], time=5)
    assert out == {"value": 1, "time": 5, "sen": 1}


def test_build_bat_charging_matches_capture():
    # read [15,95,1,1,1080,480]; set custom-charging enabled off
    out = cp.build_bat_charging(READS["BAT"], enabled=False)
    assert out == {"type": "charging", "value": [0, 1080, 480]}


def test_build_bat_power_preserves_flag():
    out = cp.build_bat_power(READS["BAT"], recharge=15, resume=95)
    assert out == {"type": "power", "value": [15, 95, 1]}


def test_build_lit_toggle_working_preserves_rest():
    # read [0,480,1200,1,1,1,1,1]; turn working(light[1]) off
    out = cp.build_lit(READS["LIT"], working=False)
    assert out == {"value": 0, "time": [480, 1200], "light": [1, 0, 1, 1], "fill": 1}


def test_build_lit_period_on():
    out = cp.build_lit(READS["LIT"], value=True)
    assert out == {"value": 1, "time": [480, 1200], "light": [1, 1, 1, 1], "fill": 1}


def test_build_rec_toggle_value_preserves_mode_report():
    # read [1,1, 1,1,1,1, 0,1,3]; turn value off
    out = cp.build_rec(READS["REC"], value=False)
    assert out == {"value": 0, "sen": 1, "mode": [1, 1, 1, 1], "report": [0, 1, 3]}


def test_build_rec_change_sensitivity():
    out = cp.build_rec(READS["REC"], sen=2)
    assert out == {"value": 1, "sen": 2, "mode": [1, 1, 1, 1], "report": [0, 1, 3]}


def test_build_lang_voice():
    out = cp.build_lang(READS["LANG"], kind="voice", value=0)
    assert out == {"type": "voice", "value": 0}


def test_build_lang_text():
    out = cp.build_lang(READS["LANG"], kind="text", value=7)
    assert out == {"type": "text", "value": 7}


@pytest.mark.parametrize("fn,args", [
    (cp.build_dnd, {"value": True}), (cp.build_low, {"value": True}),
    (cp.build_lit, {"value": True}), (cp.build_rec, {"value": True}),
    (cp.build_bat_charging, {"enabled": True}), (cp.build_bat_power, {"recharge": 10, "resume": 90}),
])
def test_builders_return_none_on_empty_base(fn, args):
    assert fn(None, **args) is None
    assert fn([], **args) is None
```

- [ ] **Step 2: Run it, expect failure**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_cfg_payloads.py -q`
Expected: FAIL — `ModuleNotFoundError: cfg_payloads` / attributes missing.

- [ ] **Step 3: Implement `cfg_payloads.py`:**

```python
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
```

- [ ] **Step 4: Run tests, expect pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_cfg_payloads.py -q`
Expected: PASS (all builder tests green).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/cfg_payloads.py tests/protocol/test_cfg_payloads.py
git commit -m "feat(a1): pure CFG RMW payload builders matching 2026-06-09 capture

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Switch base — `build_from_cfg_fn` hook + RMW-from-raw handler

**Files:**
- Modify: `custom_components/dreame_a2_mower/_switch_base.py` (description dataclass ~L48; handler ~L100-145)
- Test: `tests/integration/test_cfg_switch_writes.py` (create)

Add an optional `build_from_cfg_fn: Callable[[list, bool], Any] | None` to the description. When set, the handler reads `coordinator.cloud_state.cfg.get(cfg_key)` and calls `build_from_cfg_fn(raw, enabled)`; if it returns `None` (no base / partial), revert the optimistic state and abort the write.

- [ ] **Step 1: Write the failing test** (`tests/integration/test_cfg_switch_writes.py`):

```python
"""Phase A1: descriptor switches with build_from_cfg_fn RMW from raw cfg."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.dreame_a2_mower import _switch_base as sb


@pytest.mark.asyncio
async def test_build_from_cfg_fn_rmw_calls_write_setting(monkeypatch):
    desc = sb.DreameA2SwitchEntityDescription(
        key="dnd", name="DND", cfg_key="DND",
        build_from_cfg_fn=lambda raw, enabled: {"value": int(enabled), "time": [raw[1], raw[2]]},
        value_fn=lambda s: False,
    )
    coord = SimpleNamespace()
    coord.data = SimpleNamespace()
    coord.cloud_state = SimpleNamespace(cfg={"DND": [0, 1260, 420]})
    coord.write_setting = AsyncMock(return_value=True)

    ent = sb.DreameA2Switch(coord, desc)  # type: ignore[arg-type]
    ent._control_mode = sb.ControlMode.DEVICE_WRITABLE
    monkeypatch.setattr(ent, "async_write_ha_state", lambda: None, raising=False)

    await ent.async_turn_on()
    coord.write_setting.assert_awaited_once()
    args, kwargs = coord.write_setting.call_args
    assert args[0] == "DND"
    assert args[1] == {"value": 1, "time": [1260, 420]}


@pytest.mark.asyncio
async def test_build_from_cfg_fn_none_base_reverts(monkeypatch):
    desc = sb.DreameA2SwitchEntityDescription(
        key="rec", name="REC", cfg_key="REC",
        build_from_cfg_fn=lambda raw, enabled: None,  # no base
        value_fn=lambda s: False,
    )
    coord = SimpleNamespace()
    coord.data = SimpleNamespace()
    coord.cloud_state = SimpleNamespace(cfg={})  # REC absent
    coord.write_setting = AsyncMock(return_value=True)
    ent = sb.DreameA2Switch(coord, desc)  # type: ignore[arg-type]
    ent._control_mode = sb.ControlMode.DEVICE_WRITABLE
    monkeypatch.setattr(ent, "async_write_ha_state", lambda: None, raising=False)

    await ent.async_turn_on()
    coord.write_setting.assert_not_awaited()  # aborted, no write
```

> Confirm the exact `DreameA2Switch.__init__` signature and `ControlMode` import in `_switch_base.py` first; adapt the test construction to match (the test above assumes `DreameA2Switch(coordinator, description)` and a settable `_control_mode`).

- [ ] **Step 2: Run it, expect failure**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_cfg_switch_writes.py -q`
Expected: FAIL — `build_from_cfg_fn` is not a valid field / not honored by the handler.

- [ ] **Step 3: Add the field + handler branch.**

In the `DreameA2SwitchEntityDescription` dataclass (after `build_value_fn`/`field_updates_fn`, ~L48):

```python
    build_from_cfg_fn: Callable[[Any, bool], Any] | None = None
```

In the handler `_async_set` (the body after the `read_only` guard, ~L120, where it currently does `if desc.build_value_fn is not None: wire_value = desc.build_value_fn(...)`), insert the cfg branch BEFORE the `build_value_fn` branch:

```python
        if desc.build_from_cfg_fn is not None:
            cs = getattr(self.coordinator, "cloud_state", None)
            raw = cs.cfg.get(desc.cfg_key) if cs is not None else None
            wire_value = desc.build_from_cfg_fn(raw, enabled)
            if wire_value is None:
                # No cached base to RMW from — don't send a partial payload.
                LOGGER.warning(
                    "switch.%s: no cfg base for %s; write aborted",
                    self.entity_id, desc.cfg_key,
                )
                self.async_write_ha_state()  # snap back
                return
        elif desc.build_value_fn is not None:
            wire_value = desc.build_value_fn(self.coordinator.data, enabled)
        else:
            wire_value = enabled
```

(Keep the existing `field_updates_fn` and `write_setting(...)` call that follows. Ensure `Any` and `LOGGER` are imported in `_switch_base.py`.)

- [ ] **Step 4: Run tests, expect pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_cfg_switch_writes.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/_switch_base.py tests/integration/test_cfg_switch_writes.py
git commit -m "feat(a1): switch descriptor build_from_cfg_fn RMW hook + no-base revert

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Wire switch descriptors to the new builders

**Files:**
- Modify: `custom_components/dreame_a2_mower/switch_global.py`

Repoint the read-only/wrong-shape switches at `cfg_payloads` builders via `build_from_cfg_fn`, and add `cfg_key`+builder to the LIT/REC switches that had it omitted. Import: `from .protocol import cfg_payloads as _cfgp` (top of file).

- [ ] **Step 1: Update each descriptor** (per the field map below). For each, set `build_from_cfg_fn` and REMOVE the now-obsolete `build_value_fn`/`field_updates_fn` for that entity (the optimistic `field_updates` is still wanted — keep `field_updates_fn`; only the wire-shape `build_value_fn` is replaced). Add `cfg_key` where missing.

| switch key | cfg_key | build_from_cfg_fn |
|---|---|---|
| dnd | DND | `lambda raw, on: _cfgp.build_dnd(raw, value=on)` |
| rain_protection | WRP | `lambda raw, on: _cfgp.build_wrp(raw, value=on)` |
| low_speed_at_night | LOW | `lambda raw, on: _cfgp.build_low(raw, value=on)` |
| custom_charging_period | BAT | `lambda raw, on: _cfgp.build_bat_charging(raw, enabled=on)` |
| led_period | LIT | `lambda raw, on: _cfgp.build_lit(raw, value=on)` |
| led_in_standby | LIT | `lambda raw, on: _cfgp.build_lit(raw, standby=on)` |
| led_in_working | LIT | `lambda raw, on: _cfgp.build_lit(raw, working=on)` |
| led_in_charging | LIT | `lambda raw, on: _cfgp.build_lit(raw, charging=on)` |
| led_in_error | LIT | `lambda raw, on: _cfgp.build_lit(raw, error=on)` |
| human_presence_alert | REC | `lambda raw, on: _cfgp.build_rec(raw, value=on)` |

For the LIT/REC switches that previously had `# cfg_key intentionally omitted — read-only`, remove that comment and the `entity_category=EntityCategory.DIAGNOSTIC` only if it conflicts with the existing convention (keep DIAGNOSTIC — it's orthogonal to writability). Keep each entity's existing `value_fn` and `field_updates_fn` (the optimistic state field).

- [ ] **Step 2: Verify import + no syntax errors**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -c "import ast; ast.parse(open('custom_components/dreame_a2_mower/switch_global.py').read())"`
Expected: no output (parses).

- [ ] **Step 3: Run the switch write test from Task 3 + existing switch tests**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_cfg_switch_writes.py tests/ -k "switch" -q`
Expected: PASS (existing read-only assertions for these keys will be updated in Task 8; if any fail now on read_only, note them — they flip in Task 8).

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/switch_global.py
git commit -m "feat(a1): point DND/WRP/LOW/BAT/LIT/REC switches at cfg_payloads builders

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Numbers — BAT power + REC sensitivity

**Files:**
- Modify: `custom_components/dreame_a2_mower/number.py`

Read `number.py` first to learn its descriptor + handler shape (it has `cfg_key` and a `read_only`-gated handler calling `write_setting` at ~L280-312). Apply the same `build_from_cfg_fn` pattern as Task 3 (mirror it into the number description + handler), or, if the number handler already passes a builder, repoint it.

- [ ] **Step 1: Add `build_from_cfg_fn` to the number description + handler branch** (mirror Task 3 exactly: read `coordinator.cloud_state.cfg.get(cfg_key)`, call builder, revert on `None`). Write a focused test `tests/integration/test_cfg_number_writes.py` analogous to Task 3's switch test, asserting:
  - `auto_recharge_battery_pct` set to 20 → `write_setting("BAT", {"type":"power","value":[20,95,1]}, …)` (resume+flag preserved from read `[15,95,1,…]`).
  - `resume_battery_pct` set to 90 → `{"type":"power","value":[15,90,1]}`.
  - `human_presence_alert_sensitivity` set to 2 → `write_setting("REC", {"value":1,"sen":2,"mode":[…],"report":[…]}, …)`.

Builders/wiring:
| number key | cfg_key | build_from_cfg_fn |
|---|---|---|
| auto_recharge_battery_pct | BAT | `lambda raw, v: _cfgp.build_bat_power(raw, recharge=int(v))` |
| resume_battery_pct | BAT | `lambda raw, v: _cfgp.build_bat_power(raw, resume=int(v))` |
| human_presence_alert_sensitivity | REC | `lambda raw, v: _cfgp.build_rec(raw, sen=int(v))` |

(The number handler's builder receives the new numeric value rather than a bool; name the param `v`. If the number description has no `build_from_cfg_fn` field, add it the same way as the switch description.)

- [ ] **Step 2: Run the test, expect fail → implement → pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_cfg_number_writes.py -q`
Expected: FAIL first, then PASS after wiring.

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/number.py tests/integration/test_cfg_number_writes.py
git commit -m "feat(a1): BAT-power + REC-sensitivity numbers RMW via cfg_payloads

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Selects — LANG (lcd/voice language) + WRP resume hours

**Files:**
- Modify: `custom_components/dreame_a2_mower/select_global.py`

Read `select_global.py` (LANG selects at ~L410/429; `rain_protection_resume_hours` exists too). Apply the `build_from_cfg_fn` pattern (mirror Task 3 into the select description + handler). The select handler maps the chosen option → an index/int, then builds.

- [ ] **Step 1: Wire + test** (`tests/integration/test_cfg_select_writes.py`):

| select key | cfg_key | build_from_cfg_fn (v = resolved int index) |
|---|---|---|
| voice_language | LANG | `lambda raw, v: _cfgp.build_lang(raw, kind="voice", value=int(v))` |
| lcd_language | LANG | `lambda raw, v: _cfgp.build_lang(raw, kind="text", value=int(v))` |
| rain_protection_resume_hours | WRP | `lambda raw, v: _cfgp.build_wrp(raw, time=int(v))` |

Test asserts e.g. selecting voice English(0) → `write_setting("LANG", {"type":"voice","value":0}, …)`; resume-hours 5 → `write_setting("WRP", {"value":1,"time":5,"sen":1}, …)`.

> Confirm how the select maps option-string → int (existing option/index map in the descriptor). Reuse it; do not invent a new mapping.

- [ ] **Step 2: fail → implement → pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_cfg_select_writes.py -q`

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/select_global.py tests/integration/test_cfg_select_writes.py
git commit -m "feat(a1): LANG + WRP-resume-hours selects RMW via cfg_payloads

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Time entities — DND/LOW/BAT-charging/LIT start & end

**Files:**
- Modify: `custom_components/dreame_a2_mower/time.py`

Read `time.py` (read-only-gated at ~L147). Apply the `build_from_cfg_fn` pattern. A `TimeEntity` value is a `datetime.time`; convert to minutes-since-midnight (`t.hour*60 + t.minute`) for the builder.

- [ ] **Step 1: Wire + test** (`tests/integration/test_cfg_time_writes.py`). The builder receives minutes-since-midnight:

| time key | cfg_key | build_from_cfg_fn (m = minutes-since-midnight) |
|---|---|---|
| dnd start | DND | `lambda raw, m: _cfgp.build_dnd(raw, start=m)` |
| dnd end | DND | `lambda raw, m: _cfgp.build_dnd(raw, end=m)` |
| low start | LOW | `lambda raw, m: _cfgp.build_low(raw, start=m)` |
| low end | LOW | `lambda raw, m: _cfgp.build_low(raw, end=m)` |
| custom charging start | BAT | `lambda raw, m: _cfgp.build_bat_charging(raw, start=m)` |
| custom charging end | BAT | `lambda raw, m: _cfgp.build_bat_charging(raw, end=m)` |
| led period start | LIT | `lambda raw, m: _cfgp.build_lit(raw, start=m)` |
| led period end | LIT | `lambda raw, m: _cfgp.build_lit(raw, end=m)` |

> Use the EXACT time-entity keys present in `time.py` (the table names are descriptive; map them to the real keys when you read the file). If a given start/end time entity does not currently exist, do NOT invent it — note it in your report and skip; the switch on/off still works.

Test asserts e.g. setting DND start to 21:00 → `write_setting("DND", {"value":0,"time":[1260,420]}, …)` (read `[0,1260,420]`, end preserved).

- [ ] **Step 2: fail → implement → pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_cfg_time_writes.py -q`

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/time.py tests/integration/test_cfg_time_writes.py
git commit -m "feat(a1): DND/LOW/BAT/LIT time entities RMW via cfg_payloads

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Flip control_mode verdicts → DEVICE_WRITABLE

**Files:**
- Modify: `custom_components/dreame_a2_mower/control_honesty.py`
- Modify: any existing tests asserting these controls are read-only

- [ ] **Step 1: Flip the in-scope controls** in `CONTROL_MODES` from `_C`/`_P`/`_N` to `_W`:
  - `select.dreame_a2_mower_rain_protection_resume_hours`, `lcd_language`, `voice_language`
  - `number.dreame_a2_mower_human_presence_alert_sensitivity`; in the `number.dreame_a2_mower_<key>` sub-map: `auto_recharge_battery_pct`, `resume_battery_pct`
  - in the `switch.dreame_a2_mower_<key>` sub-map: `dnd`, `low_speed_at_night`, `custom_charging_period`, `rain_protection`, `led_period`, `led_in_standby`, `led_in_working`, `led_in_charging`, `led_in_error`, `human_presence_alert`
  - in the `time.dreame_a2_mower_<key>` entry: the DND/LOW/BAT/LIT start/end time leaves (this entry is currently a blanket `_N`; if it's a single `_N` for all time entities, split it into a per-leaf sub-map so only the wired time leaves become `_W` and any genuinely-unwired ones stay `_N`).

- [ ] **Step 2: Run the control_mode code-sync test**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory/test_control_mode_code_sync.py -q` (find the exact path: `grep -rl control_mode tests/inventory`)
Expected: it will FAIL until Task 9 updates `entity-inventory.yaml` to match. That's expected — Task 9 closes the sync. (If you prefer, do Task 8 + Task 9 as one commit so the sync test never goes red mid-stream.)

- [ ] **Step 3: Update existing read-only assertions.** Grep tests for these keys asserting `read_only`/padlock and update them to expect writable:

Run: `grep -rnE "read_only|_reject_readonly|DEVICE_WRITABLE|READ_ONLY" tests/ | grep -iE "dnd|rain_protection|low_speed|custom_charging|led_|human_presence|battery_pct|language|resume_hours"`
Update each to the new expectation.

- [ ] **Step 4: Commit (jointly with Task 9 if you combined them)**

```bash
git add custom_components/dreame_a2_mower/control_honesty.py tests/
git commit -m "feat(a1): flip CFG More-Settings controls to DEVICE_WRITABLE

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Inventory + entity-inventory updates (fact discipline)

**Files:**
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml`
- Modify: `custom_components/dreame_a2_mower/inventory.yaml`

- [ ] **Step 1: entity-inventory.yaml** — for each flipped control, supersede its Phase 0 "write path captured, NOT wired" verification with a new one: now wired + writable via `cfg_payloads.build_<key>`, transport-parity-confirmed against the 2026-06-09 capture; update the `control_mode` field to `device_writable`. Bump `status.last_seen: "2026-06-10"`.

- [ ] **Step 2: inventory.yaml** — append a verification to each CFG key entry (WRP/DND/LOW/BAT/LIT/REC/LANG) recording the write is now wired in the integration via the RMW builder, citing `app-mitm:2026-06-09-settings-sweep`. For the already-writable audited keys (PROT/CLS/ATA/FDP/STUN/AOP/MSG_ALERT/VOICE/VOL), append a confirming verification that the integration's `set_cfg` envelope matches the captured app envelope (no code change needed). No retractions expected (the transport already matched); if you find any prior claim that the integration's shape was wrong, retract it verbatim.

- [ ] **Step 3: Validate + sync**

Run:
```
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/entity_inventory_audit.py
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory/ -q
```
Expected: validator ok; entity audit `missing from inventory: 0`; control_mode code-sync test now GREEN (CONTROL_MODES ↔ entity-inventory aligned).

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/entity-inventory.yaml custom_components/dreame_a2_mower/inventory.yaml
git commit -m "inventory(a1): record CFG writes wired + writable; confirm audited-key transport parity

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Full suite + final verification

**Files:** none (verification only)

- [ ] **Step 1: Full test suite**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q`
Expected: baseline maintained — all passed except the intended changes; 4 skipped. No failures. (Baseline before A1 was 2055 passed / 4 skipped; A1 adds tests, so the passed count rises.)

- [ ] **Step 2: Inventory gates**

Run:
```
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_audit.py --consistency
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/entity_inventory_audit.py
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/audit_outstanding_retractions.py
```
Expected: all clean/green.

- [ ] **Step 3: Parity spot-check.** Confirm each in-scope entity's builder output equals the fixture's captured write for a representative change (already covered by Task 2 unit tests; re-run them):

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_cfg_payloads.py -q`
Expected: PASS — every builder matches the captured envelope.

- [ ] **Step 4: Report** the final pass/skip counts, the list of controls flipped to writable, and confirm `set_cfg` was NOT modified (audit confirmed parity):

Run: `git diff --stat main..HEAD -- custom_components/dreame_a2_mower/cloud_client/`
Expected: empty (no cloud_client change — transport already matched).
