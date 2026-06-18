# Authoritative error text from cloud notifications (todo7 #2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `sensor.dreame_a2_mower_error` show the authoritative cloud notification wording (from the existing per-code `_notif_text_cache`), persist that cache across restarts, and add a dev tool + curation pass to align the static `error_codes.py` fallback strings.

**Architecture:** The error sensor prefers `coord.cloud_error_text(code)` (a read of the existing `_notif_text_cache` keyed by `(siid,piid,value)`) over the static `describe_error(code)`. The cache — already written by the boot baseline and the reactive s2p2 resolver — gains a Store so it accumulates and survives restarts. A `tools/probes/` script diffs cloud-vs-static text to drive a gate-respecting curation of `error_codes.py`.

**Tech Stack:** Python (Home Assistant custom component); `homeassistant.helpers.storage.Store`; vanilla-pytest venv at `/data/claude/homeassistant/.venv-vanilla/bin/python`.

**Test command (throughout):** `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest <path> -q`. System python3 is broken. Stage by EXPLICIT path; never `git add -A` (untracked `tools/probes/oss_*` are NOT ours).

**Key facts:**
- `_notif_text_cache: dict[tuple[int,int,int], str]` initialized at `coordinator/_core.py:220` (`= {}`). Written at `coordinator/_notifications.py:97` (baseline seed loop) and `:214` (reactive resolver). s2p2 = siid 2 / piid 2, so a fault code `c` is keyed `(2, 2, c)`.
- Error sensor (`entities/sensor/device.py`): `DreameA2DiagnosticSensorEntityDescription(key="error_description", name="Error", value_fn=lambda coord: _active_fault_text(coord.state_machine.snapshot()))`. `_active_fault_text(snapshot)` (lines 69-82) joins `describe_error(c)` over `snapshot.errors`.
- `error_codes.py` is CI-gated by `tests/inventory/test_error_codes_confidence_gate.py`: a code may have a description ONLY if `inventory.yaml § state_codes` (`s2p2_<code>`) is `decoded: confirmed|partial`.

---

### Task 1 (A): Error sensor prefers cloud text

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_notifications.py` (add `cloud_error_text`)
- Modify: `custom_components/dreame_a2_mower/entities/sensor/device.py` (`_active_fault_text` + the error sensor `value_fn`)
- Test: `tests/integration/test_error_sensor_value.py` (create if absent, else append — check first; there's an existing `test_error_sensor_value` referenced in memory)

- [ ] **Step 1: Write the failing test**

Create/append `tests/integration/test_error_text_cloud_preference.py`:

```python
from types import SimpleNamespace
from custom_components.dreame_a2_mower.entities.sensor.device import _active_fault_text
from custom_components.dreame_a2_mower.mower.error_codes import describe_error


def _snap(errors):
    return SimpleNamespace(errors=set(errors))


def test_active_fault_text_prefers_cloud_then_static():
    # code 27 has cloud text; code 4 does not → static fallback.
    # Compare the static part against describe_error() (NOT a literal) so this
    # test survives Task 4's curation of the static strings.
    coord = SimpleNamespace(
        cloud_error_text=lambda c: "CLOUD-TEXT-27" if c == 27 else None
    )
    out = _active_fault_text(_snap({4, 27}), coord)
    assert out == f"{describe_error(4)}; CLOUD-TEXT-27"  # sorted: 4 static, 27 cloud


def test_active_fault_text_no_coord_is_all_static():
    out = _active_fault_text(_snap({27}))
    assert out == describe_error(27)  # no coord → static fallback (curation-robust)


def test_active_fault_text_none_when_no_errors():
    assert _active_fault_text(_snap(set()), SimpleNamespace(cloud_error_text=lambda c: "x")) is None
```

- [ ] **Step 2: Run, verify FAIL**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_error_text_cloud_preference.py -q`
Expected: FAIL — `_active_fault_text` takes only `snapshot` (TypeError on the 2-arg call), or the cloud preference isn't applied.

- [ ] **Step 3: Add `cloud_error_text` to `_NotificationsMixin`**

In `coordinator/_notifications.py`, add this method to `_NotificationsMixin` (near `_establish_notification_baseline`):

```python
    def cloud_error_text(self, code: int) -> str | None:
        """Authoritative cloud notification text for an s2p2 code, or None.

        s2p2 = siid 2 / piid 2; the resolver keys `_notif_text_cache` by
        (siid, piid, value). Returns the cloud's English wording if we've seen a
        notification for this code (this session or restored from disk), else None.
        """
        return self._notif_text_cache.get((2, 2, int(code)))
```

- [ ] **Step 4: Update `_active_fault_text` + the error sensor `value_fn`**

In `entities/sensor/device.py`, replace `_active_fault_text` (lines 69-82) with:

```python
def _active_fault_text(snapshot, coord=None) -> str | None:
    """Human text for the currently-latched fault(s), or None.

    Prefers the authoritative cloud notification text (coord.cloud_error_text)
    over the static error_codes.py description, falling back to static when the
    cloud text isn't cached (cold boot, or a fault that pushed no notification).
    `coord` is optional so the audit eval-path / static callers still work.
    Reads snapshot.errors (the latched fault set), joined sorted with '; '.
    """
    errors = getattr(snapshot, "errors", None)
    if not errors:
        return None
    cloud = getattr(coord, "cloud_error_text", None)

    def _text(c: int) -> str:
        if cloud is not None:
            t = cloud(c)
            if t:
                return t
        return describe_error(c)

    return "; ".join(_text(c) for c in sorted(errors))
```

Then change the error sensor description's `value_fn` (the `key="error_description"` entry, ~line 670) from:
```python
        value_fn=lambda coord: _active_fault_text(coord.state_machine.snapshot()),
```
to:
```python
        value_fn=lambda coord: _active_fault_text(coord.state_machine.snapshot(), coord),
```

- [ ] **Step 5: Run, verify PASS**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_error_text_cloud_preference.py -q`
Expected: PASS. (The tests compare static parts against `describe_error()`, so Task 4's later curation of the static strings won't break them.)

- [ ] **Step 6: Run pre-existing error-sensor tests**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q -k "error" 2>&1 | tail -20`
Expected: PASS. If a pre-existing `_active_fault_text` test calls it with one arg, it still works (coord defaults None).

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_notifications.py custom_components/dreame_a2_mower/entities/sensor/device.py tests/integration/test_error_text_cloud_preference.py
git commit -m "feat(errors): error sensor prefers authoritative cloud text, static fallback"
```

---

### Task 2 (B): Persist the notification text cache

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_core.py` (`__init__` store field; call restore in `_async_update_data`)
- Modify: `custom_components/dreame_a2_mower/coordinator/_notifications.py` (serialize helpers + restore/persist methods + wire baseline & reactive)
- Test: `tests/integration/test_notif_text_persist.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_notif_text_persist.py`:

```python
import asyncio
from types import SimpleNamespace

from custom_components.dreame_a2_mower.coordinator._notifications import (
    _NotificationsMixin, _serialize_text_cache, _deserialize_text_cache,
)


def test_serialize_roundtrip():
    cache = {(2, 2, 27): "human", (2, 2, 4): "wheel"}
    ser = _serialize_text_cache(cache)
    assert ser == {"2:2:27": "human", "2:2:4": "wheel"}
    assert _deserialize_text_cache(ser) == cache


def test_deserialize_tolerates_garbage():
    assert _deserialize_text_cache({"bad-key": "x", "2:2:9": "ok", "1:2": "short"}) == {(2, 2, 9): "ok"}


class _FakeStore:
    def __init__(self, data=None):
        self.data = data
        self.saved = []
    async def async_load(self):
        return self.data
    def async_delay_save(self, data_func, delay):
        self.saved.append((data_func(), delay))


def test_restore_merges_into_cache():
    c = _NotificationsMixin()
    c._notif_text_cache = {(2, 2, 99): "live"}  # a pre-existing live entry
    c._notif_text_store = _FakeStore({"2:2:27": "restored"})
    c.entry = SimpleNamespace(entry_id="e1")
    c.hass = SimpleNamespace()
    asyncio.run(c._restore_notif_text_cache())
    assert c._notif_text_cache == {(2, 2, 99): "live", (2, 2, 27): "restored"}


def test_restore_tolerates_bad_store():
    class _BadStore:
        async def async_load(self):
            raise RuntimeError("corrupt")
    c = _NotificationsMixin()
    c._notif_text_cache = {}
    c._notif_text_store = _BadStore()
    c.entry = SimpleNamespace(entry_id="e1")
    c.hass = SimpleNamespace()
    asyncio.run(c._restore_notif_text_cache())  # must not raise
    assert c._notif_text_cache == {}


def test_persist_schedules_save():
    c = _NotificationsMixin()
    c._notif_text_cache = {(2, 2, 27): "human"}
    store = _FakeStore()
    c._notif_text_store = store
    c._persist_notif_text_cache()
    assert store.saved == [({"2:2:27": "human"}, 5)]
```

- [ ] **Step 2: Run, verify FAIL**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_notif_text_persist.py -q`
Expected: FAIL — `_serialize_text_cache` / `_restore_notif_text_cache` / `_persist_notif_text_cache` undefined.

- [ ] **Step 3: Add serialize helpers + module const in `_notifications.py`**

Near the top of `coordinator/_notifications.py` (after imports), add:

```python
# Debounce window for persisting the notification text cache.
NOTIF_TEXT_SAVE_DELAY_S = 5


def _serialize_text_cache(cache: dict) -> dict:
    """(siid,piid,value)->text  ==>  "siid:piid:value"->text (JSON-safe keys)."""
    return {f"{s}:{p}:{v}": t for (s, p, v), t in cache.items()}


def _deserialize_text_cache(data) -> dict:
    """Inverse of _serialize_text_cache; drops any malformed key."""
    out: dict[tuple[int, int, int], str] = {}
    if not isinstance(data, dict):
        return out
    for k, t in data.items():
        parts = str(k).split(":")
        if len(parts) != 3:
            continue
        try:
            out[(int(parts[0]), int(parts[1]), int(parts[2]))] = t
        except (TypeError, ValueError):
            continue
    return out
```

- [ ] **Step 4: Add restore + persist methods to `_NotificationsMixin`**

In `coordinator/_notifications.py`, add to `_NotificationsMixin`:

```python
    async def _restore_notif_text_cache(self) -> None:
        """Seed _notif_text_cache from disk on boot so authoritative cloud text
        survives restarts (the cache is otherwise per-process). Merges into any
        live entries; tolerates a missing/corrupt store."""
        from homeassistant.helpers.storage import Store

        if self._notif_text_store is None:
            self._notif_text_store = Store(
                self.hass,
                version=1,
                key=f"dreame_a2_mower_notif_text_{self.entry.entry_id}",
            )
        try:
            stored = await self._notif_text_store.async_load()
        except Exception:
            LOGGER.exception("notif_text restore failed; continuing empty")
            return
        self._notif_text_cache.update(_deserialize_text_cache(stored))

    def _persist_notif_text_cache(self) -> None:
        """Debounced persist of the notification text cache (no-op if no store)."""
        store = getattr(self, "_notif_text_store", None)
        if store is None:
            return
        store.async_delay_save(
            lambda: _serialize_text_cache(self._notif_text_cache),
            NOTIF_TEXT_SAVE_DELAY_S,
        )
```

(`LOGGER` is already imported in this module.)

- [ ] **Step 5: Add the store field in `_core.py __init__` + call restore**

In `coordinator/_core.py __init__`, right after `self._notif_text_cache: dict[tuple[int, int, int], str] = {}` (line 220), add:

```python
        self._notif_text_store: Store | None = None  # initialised in _async_update_data
```

In `_core.py _async_update_data`'s first-run block (`if not hasattr(self, "_cloud"):`), right after the `await self._restore_device_messages()` line (added in todo7 #1), add:

```python
            await self._restore_notif_text_cache()
```

- [ ] **Step 6: Wire the persist into both cache-write sites in `_notifications.py`**

In `_establish_notification_baseline`, after `self._notif_baseline_done = True` (the line before the final `LOGGER.info(...)`), add:

```python
        self._persist_notif_text_cache()
```

In the reactive resolver, immediately after `self._notif_text_cache[target_key] = text` (line 214), add:

```python
        self._persist_notif_text_cache()
```

- [ ] **Step 7: Run, verify PASS**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_notif_text_persist.py -q`
Expected: PASS.

- [ ] **Step 8: Regression — notification tests**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q -k "notif or notification or baseline" 2>&1 | tail -20`
Expected: PASS. If a test builds a bare `_NotificationsMixin` and calls the baseline/resolver without `_notif_text_store`, the `getattr(... None)` guard in `_persist_notif_text_cache` makes it a no-op — confirm. If a test asserts exact call counts on a store, adjust.

- [ ] **Step 9: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_core.py custom_components/dreame_a2_mower/coordinator/_notifications.py tests/integration/test_notif_text_persist.py
git commit -m "feat(errors): persist notification text cache across restarts"
```

---

### Task 3 (C): Divergence dev tool

**Files:**
- Create: `tools/probes/error_text_divergence.py`
- Modify: the generated tools README (via `gen_readme.py`)
- Test: `tests/unit/test_error_text_divergence.py` (create)

- [ ] **Step 1: Read the conventions**

Read `tools/probes/lidar_parity_probe.py` for the `TOOL_META` block shape + header, and `/tmp/probe_devmsg.py`-style cloud-fetch (or `probe/probe_schedule_live.py`) for the login/fetch pattern. Find the tools README generator: `grep -rn "gen_readme" tools/` and read how `TOOL_META` feeds it.

- [ ] **Step 2: Write the failing test (pure diff logic)**

Create `tests/unit/test_error_text_divergence.py`:

```python
from tools.probes.error_text_divergence import compute_divergence


def test_compute_divergence_categories():
    cloud = {27: "Human entry into the mapped area is detected.", 4: "Left drive wheel error", 99: "Some new thing"}
    static = {27: "Human detected", 4: "Left drive wheel error", 7: "Trapped"}
    decoded = {27: "confirmed", 4: "confirmed", 99: "hypothesized", 7: "confirmed"}
    rows = {r["code"]: r for r in compute_divergence(cloud, static, decoded)}
    assert rows[27]["status"] == "DIFFERS"
    assert rows[4]["status"] == "MATCH"
    assert rows[99]["status"] == "MISSING-STATIC"   # cloud only
    assert rows[99]["decoded"] == "hypothesized"
    assert rows[7]["status"] == "MISSING-CLOUD"      # static only
    # rows carry both texts for DIFFERS
    assert rows[27]["static"] == "Human detected"
    assert rows[27]["cloud"].startswith("Human entry")
```

- [ ] **Step 3: Run, verify FAIL**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_error_text_divergence.py -q`
Expected: FAIL — module/function missing.

- [ ] **Step 4: Create the tool**

Create `tools/probes/error_text_divergence.py`. Keep `compute_divergence` PURE + importable; gate the cloud/file I/O behind `if __name__ == "__main__":`. Mirror the `TOOL_META` shape from `lidar_parity_probe.py`.

```python
"""Diff the authoritative cloud notification text against error_codes.py.

Surfaces codes whose static ERROR_CODE_DESCRIPTIONS string diverges from (or is
missing vs) the cloud's localizationContents.en — the "authoritative flag" for
curating g2408-specific wording. Source of cloud text: a persisted notif-text
store JSON (--cache-file, richest) or a one-shot live device-messages fetch.
"""
from __future__ import annotations

TOOL_META = {
    "domain": "probes",
    "summary": "Diff cloud notification text vs static error_codes.py descriptions.",
    "when": "Curating error_codes.py wording from authoritative cloud text.",
    "run_by": "maintainer",
}


def compute_divergence(
    cloud_by_code: dict[int, str],
    static_by_code: dict[int, str],
    decoded_by_code: dict[int, str],
) -> list[dict]:
    """Per-code comparison rows. status ∈ {MATCH, DIFFERS, MISSING-STATIC,
    MISSING-CLOUD}; each row carries code, static, cloud, decoded."""
    rows: list[dict] = []
    for code in sorted(set(cloud_by_code) | set(static_by_code)):
        s = static_by_code.get(code)
        c = cloud_by_code.get(code)
        if s is not None and c is not None:
            status = "MATCH" if s.strip() == c.strip() else "DIFFERS"
        elif c is not None:
            status = "MISSING-STATIC"
        else:
            status = "MISSING-CLOUD"
        rows.append({
            "code": code, "status": status, "static": s, "cloud": c,
            "decoded": decoded_by_code.get(code),
        })
    return rows


if __name__ == "__main__":  # pragma: no cover — live I/O
    import argparse, json, sys
    from pathlib import Path

    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-file", help="persisted notif-text store JSON (HA box /config/.storage/dreame_a2_mower_notif_text_*)")
    args = ap.parse_args()

    REPO = "/data/claude/homeassistant/ha-dreame-a2-mower"
    sys.path.insert(0, REPO)
    sys.path.insert(0, f"{REPO}/custom_components")
    from dreame_a2_mower.mower.error_codes import ERROR_CODE_DESCRIPTIONS  # type: ignore

    # cloud text by s2p2 value
    cloud_by_code: dict[int, str] = {}
    if args.cache_file:
        raw = json.loads(Path(args.cache_file).read_text())
        data = raw.get("data", raw)  # HA Store wraps under "data"
        for k, t in (data or {}).items():
            parts = str(k).split(":")
            if len(parts) == 3 and parts[0] == "2" and parts[1] == "2":
                cloud_by_code[int(parts[2])] = t
    else:
        # live fetch — reuse the device-messages fetch surface
        import types
        from unittest.mock import MagicMock
        for m in ("homeassistant","homeassistant.const","homeassistant.core","homeassistant.config_entries","homeassistant.helpers","homeassistant.helpers.event","homeassistant.helpers.update_coordinator","homeassistant.helpers.device_registry","homeassistant.components","homeassistant.components.persistent_notification","homeassistant.components.http","homeassistant.components.button","homeassistant.components.binary_sensor","homeassistant.components.camera","homeassistant.components.lawn_mower","homeassistant.components.number","homeassistant.components.select","homeassistant.components.sensor","homeassistant.components.switch","homeassistant.components.time","homeassistant.exceptions","homeassistant.util","voluptuous"):
            sys.modules.setdefault(m, MagicMock())
        pkg = types.ModuleType("dreame_a2_mower"); pkg.__path__ = [f"{REPO}/custom_components/dreame_a2_mower"]
        sys.modules["dreame_a2_mower"] = pkg
        from dreame_a2_mower.cloud_client import DreameA2CloudClient  # type: ignore
        cred = Path("/data/claude/homeassistant/secrets/server-credentials.txt").read_text().splitlines()
        cl = DreameA2CloudClient(username=cred[0].strip(), password=cred[1].strip(), country="eu")
        cl.login(); cl.select_first_g2408()
        recs = cl.fetch_device_messages(getattr(cl, "_did", None), 10) or []
        for r in recs:
            src = r.get("source") or {}; loc = r.get("localizationContents") or {}
            try:
                if int(src.get("siid")) == 2 and int(src.get("piid")) == 2:
                    txt = loc.get("en") or loc.get("en-US")
                    if txt:
                        cloud_by_code[int(src.get("value"))] = txt
            except (TypeError, ValueError):
                continue

    # decoded status from inventory
    import yaml  # noqa
    inv = yaml.safe_load(Path(f"{REPO}/custom_components/dreame_a2_mower/inventory.yaml").read_text())
    decoded_by_code: dict[int, str] = {}
    for entry in (inv.get("state_codes") or []):
        sid = str(entry.get("id") or "")
        if sid.startswith("s2p2_"):
            try:
                decoded_by_code[int(sid[len("s2p2_"):])] = (entry.get("status") or {}).get("decoded")
            except (TypeError, ValueError):
                continue

    rows = compute_divergence(cloud_by_code, ERROR_CODE_DESCRIPTIONS, decoded_by_code)
    for r in rows:
        if r["status"] == "MATCH":
            continue
        print(f"[{r['status']:14s}] s2p2={r['code']:>3} decoded={r['decoded']}")
        if r["static"] is not None:
            print(f"    static: {r['static']!r}")
        if r["cloud"] is not None:
            print(f"    cloud : {r['cloud']!r}")
```

(Confirm the inventory `state_codes` entry shape — `id: s2p2_<n>` and `status.decoded` — by reading a couple of entries in `inventory.yaml`. Adjust the extraction keys to the real schema if they differ.)

- [ ] **Step 5: Run, verify PASS**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_error_text_divergence.py -q`
Expected: PASS.

- [ ] **Step 6: Regenerate the tools README + verify the live tool runs**

Run the README generator (find it: `grep -rln "def.*readme\|TOOL_META" tools/*gen* tools/**/gen* 2>/dev/null`; per repo convention it's `tools/.../gen_readme.py`). Run it so the new tool is listed; confirm the tools-README sync CI test passes:
`/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q -k "readme" 2>&1 | tail -10`
Then smoke-run the live tool (it has cloud creds via the probe pattern) to confirm it executes and prints divergences:
`/data/claude/homeassistant/.venv-vanilla/bin/python tools/probes/error_text_divergence.py 2>&1 | head -40`
Capture this output — Task 4 uses it.

- [ ] **Step 7: Commit**

```bash
git add tools/probes/error_text_divergence.py tests/unit/test_error_text_divergence.py
# include the regenerated tools README path printed by gen_readme
git add tools/<generated-readme-path>
git commit -m "feat(tools): error_text_divergence — cloud-vs-static error text diff"
```

---

### Task 4 (D): Curate static fallback strings (gate-respecting)

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/error_codes.py` (`ERROR_CODE_DESCRIPTIONS`)
- Modify: `custom_components/dreame_a2_mower/inventory.yaml` (`state_codes` verifications)
- Test: the existing `tests/inventory/test_error_codes_confidence_gate.py` (must stay green)

This task is **driven by the live Task-3 tool output** — the exact codes/strings come from the run, so follow the PROCESS, not a fixed string list.

- [ ] **Step 1: Run the divergence tool and collect candidates**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/probes/error_text_divergence.py` (optionally with `--cache-file <persisted store JSON>` for fuller coverage). From its output, collect every `DIFFERS` or `MISSING-STATIC` row whose `decoded` is `confirmed` or `partial`. These are the codes to curate. List `MISSING-STATIC` rows with `decoded` `hypothesized`/`None` separately as promotion candidates — do NOT edit error_codes.py for those (the gate forbids it).

- [ ] **Step 2: Update `ERROR_CODE_DESCRIPTIONS` for confirmed/partial divergences**

For each collected code, set its `ERROR_CODE_DESCRIPTIONS[code]` value to the cloud English text (verbatim, trimmed). Keep the dict ordering/formatting. Example shape (your code 27 will likely be one):

```python
    27: "Human entry into the mapped area is detected. Please be alert. View snapshots in the app.",
```

- [ ] **Step 3: Record the cloud text as inventory evidence**

For each curated code, append a `verifications:` row to its `inventory.yaml § state_codes` `s2p2_<code>` entry:

```yaml
      - date: "2026-06-18"
        status: verified
        claim: "Authoritative app/cloud notification text for s2p2=<code>: \"<cloud text>\". error_codes.py description updated to match."
        evidence: "tools/probes/error_text_divergence.py live run 2026-06-18 (device-messages/v2 localizationContents.en)"
```

Update each touched entry's `status.last_seen` to `2026-06-18`.

- [ ] **Step 4: Run the confidence gate + inventory validation**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory/test_error_codes_confidence_gate.py -q`
Expected: PASS (every edited code was already confirmed/partial, so the gate stays green).
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only`
Expected: `ok: inventory schema valid`.

- [ ] **Step 5: Re-run the tool to confirm curated codes now MATCH**

Run the tool again; the curated codes should now report `MATCH` (or drop out of the non-match output). Promotion candidates remain listed — that's expected.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/mower/error_codes.py custom_components/dreame_a2_mower/inventory.yaml
git commit -m "docs(errors): curate error_codes.py to authoritative cloud wording (confirmed codes)"
```

If the tool surfaces ZERO confirmed/partial divergences (all already match), record that in the commit message instead and skip the edits — the runtime preference (Task 1) already covers display; nothing to curate.

---

### Task 5: Entity-inventory, canonical, full suite, release + live-verify

**Files:**
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml`
- Modify (generated): `docs/research/inventory/generated/g2408-canonical.md` (only if inventory prose changed in Task 4)

- [ ] **Step 1: Update entity-inventory.yaml for the error sensor**

Find the `sensor.dreame_a2_mower_error` (`error_description`) entry. Update its read-source to note it now PREFERS the authoritative cloud notification text (`coord.cloud_error_text` → persisted `_notif_text_cache`) and falls back to the static `describe_error`. Add a `verifications:` row dated 2026-06-18, status `presumed` (code-read; live-verified after release). Match the file's schema (read neighbors first).

- [ ] **Step 2: Regenerate canonical (only if Task 4 edited inventory.yaml)**

If Task 4 changed `inventory.yaml`: run `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py`, then `git diff --stat docs/research/inventory/generated/g2408-canonical.md` — confirm only the curated state_codes sections changed; do NOT commit unrelated wire-census churn (restore those with `git checkout --`).

- [ ] **Step 3: Validate inventory schema**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only`
Expected: `ok: inventory schema valid`.

- [ ] **Step 4: Run the FULL suite**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q --ignore=tests/archive`
Expected: all pass (~2515 baseline + new tests). Fix any failure caused by this feature:
- A state-machine-audit expectations gate for the error sensor (its value_fn signature changed) — if `tests/audit/*` goes red, the error sensor isn't a NEW entity so likely fine, but check.
- The README-sync gate (new tool) — satisfied by Task 3.
- `test_error_codes_confidence_gate` — satisfied by Task 4.

- [ ] **Step 5: Commit docs**

```bash
git add custom_components/dreame_a2_mower/entity-inventory.yaml docs/research/inventory/generated/g2408-canonical.md
git commit -m "docs(errors): entity-inventory + canonical for authoritative error text"
```

- [ ] **Step 6: Release + live-verify (controller does this; not a subagent step)**

Push; move untracked `tools/probes/oss_*` aside for a clean tree; `tools/release/release.sh --notes "..."`; restore the probes; install via HACS; restart HA. Then verify on live HA:
1. With a fault that recently pushed a notification, `sensor.dreame_a2_mower_error` shows the full app wording (not the short static string).
2. The persisted store `dreame_a2_mower_notif_text_<entry_id>` exists on the HA box and grows over time.
3. After a restart, the cloud text still resolves (cache restored from disk).

---

## Notes / gotchas
- Test interpreter: `/data/claude/homeassistant/.venv-vanilla/bin/python`. Stage by explicit path; leave untracked `tools/probes/oss_*` alone.
- `error_codes.py` is CI-gated — only curate `confirmed`/`partial` codes (Task 4); the runtime preference (Task 1) covers display regardless of the static string.
- The cache is written in BOTH the baseline and the reactive resolver; persist after both (Task 2 Step 6).
- s2p2 keys are `(2, 2, code)`. Restore MERGES into the live cache (don't clobber).
- Task 4 is curation driven by the live tool output — there's no fixed string list; the confidence gate + re-run are the guardrails.
