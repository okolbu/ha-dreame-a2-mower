# Coordinator + Entity Wiring Implementation Plan (Phase 1, Plan C, Option 3 scope)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the currently-"Unavailable" HA entities into working ones for the Dreame A2 (g2408) by wiring the `protocol/` package from Plan B into the existing upstream `_message_callback` data flow — an overlay fix rather than a rewrite.

**Architecture:** Detect `dreame.mower.g2408` model at device instantiation and swap in a g2408-specific `property_mapping` so the existing siid/piid → `DreameMowerProperty` router recognises g2408 parameters. Intercept the three "blob" properties (`s1p4` telemetry, `s1p1` heartbeat, `s2p51` multiplexed config) in `_message_callback` to route them through `protocol/` decoders and store decoded state on the coordinator. Add new HA sensor/binary_sensor entities backed by the decoded telemetry. No MQTT-first write path (that's Plan D). No stripping of non-g2408 model code (that's Plan F). No live map overlay (that's Plan E).

**Tech Stack:** Home Assistant 2026.4, Python 3.14, existing upstream `dreame_mower` integration code, the Plan B `protocol/` package already committed at `v2.0.0-alpha.3`. Tests use the same pytest + `pythonpath` setup as Plan B.

---

## Environment & credentials

- **Fork working copy:** `/data/claude/homeassistant/ha-dreame-a2-mower/`
- **HA server:** `10.0.0.30`, HAOS 2026.4.2. The fork is HACS-installed and already has a live config entry connected to the user's g2408.
- **HA SSH credentials:** load from `/data/claude/homeassistant/ha-credentials.txt` (outside the repo). See any earlier plan for the `export HA_HOST=...` pattern.
- **Probe log fixtures:** already in `tests/fixtures/`. Real device identifiers were scrubbed from history during the Plan B polish force-push.
- **Starting HEAD:** current `main`, tagged `v2.0.0-alpha.3` (commit `0424f67` or later if more polish commits landed).

## Code layout context (pre-existing, not modified except where noted)

- `custom_components/dreame_a2_mower/__init__.py` — HA setup. Instantiates `DreameMowerDataUpdateCoordinator` → `DreameMowerDevice`.
- `custom_components/dreame_a2_mower/coordinator.py` — HA `DataUpdateCoordinator` wrapper around `DreameMowerDevice`.
- `custom_components/dreame_a2_mower/dreame/device.py` — the big one (5824 lines). `DreameMowerDevice.__init__` at line 156. `_message_callback` at line 366. `_handle_properties` at line 406. Class attribute `property_mapping` defaulting to `DreameMowerPropertyMapping` at line 153.
- `custom_components/dreame_a2_mower/dreame/types.py` — `DreameMowerPropertyMapping` dict at line 719 (A1 Pro-centric, currently mismatches g2408 for several properties).
- `custom_components/dreame_a2_mower/protocol/` — pure-Python decoders from Plan B. Imports as `from .protocol import ...` at HA runtime.
- `custom_components/dreame_a2_mower/sensor.py`, `switch.py`, etc. — platform modules. Entities read from `coordinator.device.data[did]`.

## Deploy + verify loop

Every task that touches live HA state follows the same sequence: `git push origin main` → SSH to HA → `cd /config/custom_components/dreame_a2_mower && git pull` → `ha core restart` → `ha core logs` to watch for tracebacks.

The user has HACS tracking the fork's `main` branch. Re-downloads from HACS UI also work if the user prefers. Either way the deploy target is `/config/custom_components/dreame_a2_mower/` on HA.

---

### Task 1: Research — catalog g2408 siid/piid divergences

**Files:**
- Create: `docs/research/2026-04-17-g2408-property-divergences.md`

No code changes. Pure investigation. Output feeds Tasks 2-4.

- [ ] **Step 1: Enumerate g2408-observed siid/piid combinations from probe logs**

From the working directory run:

```bash
. .venv/bin/activate
python3 - <<'PY'
import json
from collections import defaultdict

seen = defaultdict(set)
values = defaultdict(set)
with open("/data/claude/homeassistant/probe_log_20260417_095500.jsonl") as f:
    for line in f:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "mqtt_message":
            continue
        for p in obj.get("params") or []:
            if not isinstance(p, dict) or p.get("siid") is None:
                continue
            key = (p["siid"], p["piid"])
            seen[key].add(obj.get("timestamp", "?"))
            v = p.get("value")
            # Capture up to 3 example values per siid/piid
            if len(values[key]) < 3:
                if isinstance(v, (int, str, bool)) or v is None:
                    values[key].add(repr(v))
                elif isinstance(v, list):
                    values[key].add(f"list(len={len(v)})")
                elif isinstance(v, dict):
                    values[key].add(f"dict keys={sorted(v.keys())}")
                else:
                    values[key].add(type(v).__name__)

print(f"{'siid':>4}.{'piid':<4}  count  examples")
for key, timestamps in sorted(seen.items()):
    s, p = key
    print(f"  {s:>3}.{p:<4}  {len(timestamps):5}  {'; '.join(sorted(values[key]))[:80]}")
PY
```

This produces a complete catalogue of every property g2408 actually sends on MQTT during the RE session. Copy this output into `docs/research/2026-04-17-g2408-property-divergences.md`.

- [ ] **Step 2: Cross-reference against upstream's `DreameMowerPropertyMapping`**

Run:

```bash
grep -nE "DreameMowerProperty\.[A-Z_]+: \{siid: [0-9]+, piid: [0-9]+\}" \
  custom_components/dreame_a2_mower/dreame/types.py \
  | sort -t: -k4n -k5n > /tmp/upstream-mapping.txt
wc -l /tmp/upstream-mapping.txt
```

Expected: ~150 entries (upstream covers many A1 Pro properties).

- [ ] **Step 3: Build the divergence table**

For each siid/piid observed in Step 1, look up whether upstream's mapping has that exact pair. Categorise each as:

- **Match:** g2408 uses the same siid/piid as upstream (no change needed).
- **Divergence:** g2408 uses different siid/piid for the same logical property (e.g., STATE). Upstream's mapping is wrong for g2408.
- **New:** g2408-specific property not in upstream's enum (e.g., `s1p4` mowing telemetry blob).
- **Orphan:** upstream expects a siid/piid that g2408 never sends (the property is simply not available; fine to leave mapped — will stay Unavailable).

Write the divergence table into `docs/research/2026-04-17-g2408-property-divergences.md` in markdown form:

```markdown
| siid.piid | g2408 example value | Upstream property | g2408 semantic | Category |
|-----------|---------------------|-------------------|----------------|----------|
| 3.1       | 90                  | BATTERY_LEVEL     | BATTERY_LEVEL  | Match    |
| 2.2       | 48                  | (nothing)         | STATE          | Divergence (upstream maps STATE to 2.1) |
| 1.4       | list(len=33)        | (nothing)         | MOWING_TELEMETRY | New |
...
```

The important output is a clean list of:
1. **Properties to reassign:** which upstream `DreameMowerProperty` entries need different siid/piid for g2408 (Task 2 input).
2. **New blob properties:** siid/piid combinations that deliver raw byte lists and need decoder routing (Task 3 input).
3. **Multiplexed config:** confirm `s2p51` (2.51) as the singular destination for all the `{value: ...}` payloads (Task 5 input).

- [ ] **Step 4: Commit research**

```bash
git add docs/research/2026-04-17-g2408-property-divergences.md
git commit -m "docs(research): catalog g2408 siid/piid divergences from upstream mapping"
```

---

### Task 2: Add g2408 property-mapping overlay in `types.py`

**Files:**
- Modify: `custom_components/dreame_a2_mower/dreame/types.py` (append after the existing `DreameMowerPropertyMapping` block)
- Create: `tests/protocol/test_property_overlay.py`

- [ ] **Step 1: Write failing test**

Create `tests/protocol/test_property_overlay.py`:

```python
"""Tests for the g2408 property-mapping overlay.

The overlay is a shallow dict-merge of g2408-specific (siid, piid) corrections
on top of upstream's DreameMowerPropertyMapping. It leaves untouched any
property that already matches or that has no g2408 equivalent.
"""

from __future__ import annotations

import pytest


def test_overlay_module_importable():
    from custom_components.dreame_a2_mower.dreame.types import (
        DreameMowerProperty,
        property_mapping_for_model,
    )
    assert callable(property_mapping_for_model)


def test_g2408_mapping_fixes_state_piid():
    from custom_components.dreame_a2_mower.dreame.types import (
        DreameMowerProperty,
        property_mapping_for_model,
    )
    mapping = property_mapping_for_model("dreame.mower.g2408")
    state_entry = mapping[DreameMowerProperty.STATE]
    # g2408 carries state codes at siid=2 piid=2 (upstream says piid=1).
    assert state_entry["siid"] == 2
    assert state_entry["piid"] == 2


def test_g2408_mapping_preserves_battery_mapping():
    from custom_components.dreame_a2_mower.dreame.types import (
        DreameMowerProperty,
        property_mapping_for_model,
    )
    mapping = property_mapping_for_model("dreame.mower.g2408")
    # Upstream's BATTERY_LEVEL at (3,1) matches g2408 — overlay should not touch it.
    assert mapping[DreameMowerProperty.BATTERY_LEVEL] == {"siid": 3, "piid": 1}


def test_unknown_model_returns_upstream_mapping_unchanged():
    from custom_components.dreame_a2_mower.dreame.types import (
        DreameMowerPropertyMapping,
        property_mapping_for_model,
    )
    mapping = property_mapping_for_model("dreame.mower.unknown_model")
    assert mapping is DreameMowerPropertyMapping or mapping == DreameMowerPropertyMapping
```

Note: the test uses `custom_components.dreame_a2_mower.dreame.types` (the long path) rather than the pythonpath shortcut because this file lives under the HA integration package's `dreame/` submodule, not under `protocol/`. At pytest time this works only if HA itself is importable. We avoid that by making the test file `from __future__ import annotations` and using lazy inline imports — pytest fails cleanly if HA is not available, but since the overlay implementation uses only dict manipulation (no HA imports), a simpler workaround below lets the test run without HA.

**Alternative import strategy (use this instead if the above fails):**

Structure `property_mapping_for_model` so it can be imported directly from `dreame/types.py` without the parent package's HA imports. Python evaluates parent `__init__.py` on package import. To bypass, add the `dreame/` directory to pytest's `pythonpath` for this specific test run, OR make `types.py` re-exportable via a thin shim at `custom_components/dreame_a2_mower/protocol/_types_shim.py` that imports only the overlay dict. The latter is cleaner — see Step 3 variant.

- [ ] **Step 2: Run test, verify failure**

```bash
. .venv/bin/activate
pytest tests/protocol/test_property_overlay.py -v
```

Expected: `ImportError` on `property_mapping_for_model` (function does not exist yet).

- [ ] **Step 3: Implement the overlay**

Append to `custom_components/dreame_a2_mower/dreame/types.py` (AFTER the existing `DreameMowerPropertyMapping = { ... }` block):

```python
# ---------------------------------------------------------------------------
# g2408-specific property-mapping overlay.
#
# Upstream's DreameMowerPropertyMapping was built for A1 Pro and earlier
# vacuum-derived mowers. The Dreame A2 (dreame.mower.g2408) uses different
# siid/piid assignments for some properties. This overlay corrects those
# differences while leaving matches untouched.
#
# Divergences derived from probe-log analysis — see
# docs/research/2026-04-17-g2408-property-divergences.md for the full catalog.
# ---------------------------------------------------------------------------

_G2408_OVERLAY: dict[DreameMowerProperty, dict[str, int]] = {
    # g2408 emits state codes at siid=2 piid=2 (upstream expected piid=1).
    DreameMowerProperty.STATE: {siid: 2, piid: 2},
}


def property_mapping_for_model(model: str) -> dict[DreameMowerProperty, dict[str, int]]:
    """Return a property_mapping tailored for the device model.

    For known-divergent models (currently only dreame.mower.g2408) this
    returns a shallow copy of the upstream mapping with model-specific
    entries overlaid. For unknown models, returns the upstream mapping
    unchanged so behaviour matches pre-overlay code.
    """
    if model == "dreame.mower.g2408":
        merged = dict(DreameMowerPropertyMapping)
        merged.update(_G2408_OVERLAY)
        return merged
    return DreameMowerPropertyMapping
```

Note: `siid` and `piid` in the literal `{siid: 2, piid: 2}` are string-valued module-level constants (the convention used throughout `types.py`). If the test expects `{"siid": 2, "piid": 2}` (dict with string keys), confirm that `siid` and `piid` are indeed aliased to the strings `"siid"` and `"piid"` at the top of `types.py`. If not, replace `siid` and `piid` in the overlay with the string literals.

To verify: `grep -E "^(siid|piid) = " custom_components/dreame_a2_mower/dreame/types.py | head`. Expected: lines like `siid = "siid"` and `piid = "piid"`.

- [ ] **Step 4: Test imports run (HA-free workaround)**

Since `dreame/types.py` transitively imports from the parent `custom_components/dreame_a2_mower/__init__.py` (which imports HA), the test will need one of:
  (a) HA installed in the venv, or
  (b) Add `pythonpath = ["custom_components/dreame_a2_mower", "custom_components/dreame_a2_mower/dreame"]` to `pyproject.toml` and change the test's import to `from types import property_mapping_for_model` (risking a clash with stdlib `types` — probably don't do this), or
  (c) Mark the test as requiring HA: add `@pytest.mark.skipif("homeassistant" not in sys.modules)` and skip gracefully; then verify in Task 10 on the live HA install.

**Chosen approach:** (c). Keep the test but skip it when HA is not importable:

Replace the test file content with:

```python
"""Tests for the g2408 property-mapping overlay."""

from __future__ import annotations

import importlib
import pytest


def _import_types():
    try:
        return importlib.import_module("custom_components.dreame_a2_mower.dreame.types")
    except ImportError:
        pytest.skip("homeassistant not installed in venv; overlay exercised during live deploy in Task 10")


def test_overlay_exports_function():
    types = _import_types()
    assert hasattr(types, "property_mapping_for_model")
    assert callable(types.property_mapping_for_model)


def test_g2408_mapping_fixes_state_piid():
    types = _import_types()
    mapping = types.property_mapping_for_model("dreame.mower.g2408")
    state_entry = mapping[types.DreameMowerProperty.STATE]
    assert state_entry["siid"] == 2
    assert state_entry["piid"] == 2


def test_g2408_mapping_preserves_battery_mapping():
    types = _import_types()
    mapping = types.property_mapping_for_model("dreame.mower.g2408")
    assert mapping[types.DreameMowerProperty.BATTERY_LEVEL] == {"siid": 3, "piid": 1}


def test_unknown_model_returns_upstream_mapping_unchanged():
    types = _import_types()
    mapping = types.property_mapping_for_model("dreame.mower.unknown_model")
    assert mapping is types.DreameMowerPropertyMapping
```

This way tests pass on `pytest -v` (skipping cleanly if HA unavailable) and pass concretely when run on the HA side via a one-off `python3 -c`.

- [ ] **Step 5: Run tests, confirm they pass or skip cleanly**

```bash
pytest tests/protocol/test_property_overlay.py -v
```

Expected: either all pass, or all skip with a clear message. Either is acceptable at this stage; live verification happens in Task 10.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/dreame/types.py tests/protocol/test_property_overlay.py
git commit -m "feat(dreame): g2408 property-mapping overlay fixes STATE piid"
```

**Note:** Task 1's research may reveal additional divergences beyond `STATE`. Add them to `_G2408_OVERLAY` as entries at this point. If the research table shows a divergence not covered here, extend `_G2408_OVERLAY` and add one assertion per divergence to the test file before committing.

---

### Task 3: Wire overlay into `DreameMowerDevice.__init__`

**Files:**
- Modify: `custom_components/dreame_a2_mower/dreame/device.py` around line 153 (class attribute) and line 156 (`__init__`).

- [ ] **Step 1: Inspect the current class attribute**

```bash
sed -n '150,160p' custom_components/dreame_a2_mower/dreame/device.py
```

Expected to show:

```python
class DreameMowerDevice:
    ...
    property_mapping: dict[DreameMowerProperty, dict[str, int]] = DreameMowerPropertyMapping
```

- [ ] **Step 2: Locate `__init__` and find where `self._model` is set**

```bash
grep -n "self._model\|self\.model\s*=" custom_components/dreame_a2_mower/dreame/device.py | head
```

The model string (`dreame.mower.g2408`) should be stored on the device. If the field is `self._model`, the overlay hook should run after the model is known.

- [ ] **Step 3: Replace class attribute with instance-based assignment**

Modify `device.py` with a two-line change near the init:

Immediately after the line that sets `self._model` (or its equivalent — use grep output from Step 2), append:

```python
        # Apply model-specific property-mapping overlay (g2408 corrects siid/piid
        # divergences from upstream's A1-Pro-centric mapping).
        from .types import property_mapping_for_model
        self.property_mapping = property_mapping_for_model(self._model)
```

This OVERRIDES the class attribute with an instance attribute at the right moment. All the existing `self.property_mapping[prop]` reads (at line 380, 522, 551, 1294, 1366, 1376, 1924) automatically pick up the instance version.

Leave the class-level default in place — it ensures `property_mapping` still resolves to the upstream dict even if `__init__` never ran (e.g., during tests).

- [ ] **Step 4: Smoke-test the change**

```bash
grep -nE "self\.property_mapping\s*=" custom_components/dreame_a2_mower/dreame/device.py
```

Expected: exactly one hit — the new assignment in `__init__`. If multiple hits appear, there was a prior instance assignment that conflicts; inspect and reconcile.

```bash
. .venv/bin/activate
python3 -m compileall -q custom_components/dreame_a2_mower/dreame/device.py
```

Expected: silent (no SyntaxError).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/dreame/device.py
git commit -m "feat(dreame): apply model-specific property-mapping overlay in Device.__init__"
```

---

### Task 4: Intercept blob properties in `_message_callback` (s1p4 telemetry)

**Files:**
- Modify: `custom_components/dreame_a2_mower/dreame/device.py` around line 366 (`_message_callback`)

**Background:** Blob properties (`s1p4`, `s1p1`, `s2p51`) arrive as lists of bytes or dicts, not scalars. The existing `_handle_properties` just stuffs whatever comes in into `self.data[did]`. For blobs we want to **decode** the raw payload via `protocol/` and store the structured result instead, so entities can query `self.data[did].phase`, `.area_mowed_m2`, etc.

This task wires `s1p4` specifically. Tasks 5 and 6 follow the same pattern for `s1p1` and `s2p51`.

- [ ] **Step 1: Add a decoder dispatch table at module scope**

Open `custom_components/dreame_a2_mower/dreame/device.py`. Near the top, just below the existing imports, add:

```python
from ..protocol.telemetry import (
    InvalidS1P4Frame,
    MowingTelemetry,
    decode_s1p4,
)
```

(`..protocol` is the fork's new `protocol/` package. At HA runtime this relative import resolves correctly because `dreame/` and `protocol/` share the parent `dreame_a2_mower` package.)

- [ ] **Step 2: Intercept `s1p4` in `_message_callback`**

Locate the loop in `_message_callback` (around line 373-402) that iterates properties. Just before the `self._handle_properties(params)` call (around line 404), add a post-processing step that decodes any `s1p4` blobs in `params` and replaces the raw list with a `MowingTelemetry` instance:

Insert after the existing `self._handle_properties(params)` call target a new helper:

Find the line:

```python
                self._handle_properties(params)
```

Replace it with:

```python
                self._decode_blob_properties(params)
                self._handle_properties(params)
```

Then add the helper method later in the class (e.g., just after `_handle_properties`):

```python
    def _decode_blob_properties(self, params: list[dict]) -> None:
        """Decode any blob-typed properties in-place into structured objects.

        Blob properties (s1p4 telemetry, s1p1 heartbeat, s2p51 config) arrive
        as raw lists of bytes or dicts. We replace param['value'] with the
        decoded dataclass/object so downstream entities can read structured
        fields instead of raw bytes.
        """
        # DreameMowerProperty value (did) for the blob — derived from the
        # property_mapping lookup table; same property enum but g2408 siid/piid.
        from .types import DreameMowerProperty
        telemetry_did = DreameMowerProperty.MOWING_TELEMETRY.value if hasattr(DreameMowerProperty, "MOWING_TELEMETRY") else None
        for param in params:
            if not isinstance(param, dict):
                continue
            did = int(param.get("did", 0))
            value = param.get("value")
            if telemetry_did is not None and did == telemetry_did and isinstance(value, list):
                try:
                    param["value"] = decode_s1p4(bytes(value))
                except InvalidS1P4Frame as e:
                    _LOGGER.warning("Discarding malformed s1p4 frame: %s", e)
                    param["value"] = None
```

**Important:** the existing `DreameMowerProperty` enum (in `types.py`) does NOT have a `MOWING_TELEMETRY` member. This task must add it. See next step.

- [ ] **Step 3: Add `MOWING_TELEMETRY` to the property enum**

In `custom_components/dreame_a2_mower/dreame/types.py`, find the `DreameMowerProperty` enum definition (should be near line 719 or similar). Add a new member:

```python
    MOWING_TELEMETRY = <next_available_integer_value>
```

The `<next_available_integer_value>` should be a fresh integer not used by any existing member. Pick an unused value like `900` (or whatever the highest existing value + 1 is — check with `grep -nE "^\s*[A-Z_]+ = [0-9]+" custom_components/dreame_a2_mower/dreame/types.py | sort -t= -k2n | tail`).

Also add the overlay entry in `_G2408_OVERLAY` (extend Task 2's overlay):

```python
_G2408_OVERLAY: dict[DreameMowerProperty, dict[str, int]] = {
    DreameMowerProperty.STATE: {siid: 2, piid: 2},
    DreameMowerProperty.MOWING_TELEMETRY: {siid: 1, piid: 4},  # s1p4 — 33-byte mowing telemetry blob
}
```

- [ ] **Step 4: Smoke-test the wiring**

```bash
python3 -m compileall -q custom_components/dreame_a2_mower/dreame/device.py \
  custom_components/dreame_a2_mower/dreame/types.py
pytest tests/protocol/test_property_overlay.py -v
```

Expected: compile OK. Overlay tests still pass (the new MOWING_TELEMETRY entry doesn't break existing tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/dreame/device.py custom_components/dreame_a2_mower/dreame/types.py
git commit -m "feat(dreame): intercept s1p4 telemetry blob and decode via protocol.telemetry"
```

---

### Task 5: Intercept `s1p1` heartbeat + `s2p51` multiplexed config

**Files:**
- Modify: `custom_components/dreame_a2_mower/dreame/device.py` (`_decode_blob_properties` helper from Task 4)
- Modify: `custom_components/dreame_a2_mower/dreame/types.py` (enum + overlay)

- [ ] **Step 1: Extend `DreameMowerProperty` enum**

Append two more members (pick two unused integer values — `901` and `902` unless they collide):

```python
    HEARTBEAT = 901
    MULTIPLEXED_CONFIG = 902
```

Extend `_G2408_OVERLAY`:

```python
_G2408_OVERLAY: dict[DreameMowerProperty, dict[str, int]] = {
    DreameMowerProperty.STATE: {siid: 2, piid: 2},
    DreameMowerProperty.MOWING_TELEMETRY: {siid: 1, piid: 4},
    DreameMowerProperty.HEARTBEAT: {siid: 1, piid: 1},
    DreameMowerProperty.MULTIPLEXED_CONFIG: {siid: 2, piid: 51},
}
```

- [ ] **Step 2: Extend imports and helper in `device.py`**

Add to the import block at the top of `device.py`:

```python
from ..protocol.heartbeat import (
    Heartbeat,
    InvalidS1P1Frame,
    decode_s1p1,
)
from ..protocol.config_s2p51 import (
    S2P51DecodeError,
    S2P51Event,
    decode_s2p51,
)
```

Extend `_decode_blob_properties` to dispatch s1p1 and s2p51 as well:

```python
    def _decode_blob_properties(self, params: list[dict]) -> None:
        """Decode any blob-typed properties in-place into structured objects."""
        from .types import DreameMowerProperty
        telemetry_did = getattr(DreameMowerProperty, "MOWING_TELEMETRY", None)
        heartbeat_did = getattr(DreameMowerProperty, "HEARTBEAT", None)
        config_did = getattr(DreameMowerProperty, "MULTIPLEXED_CONFIG", None)
        telemetry_did_val = telemetry_did.value if telemetry_did else None
        heartbeat_did_val = heartbeat_did.value if heartbeat_did else None
        config_did_val = config_did.value if config_did else None

        for param in params:
            if not isinstance(param, dict):
                continue
            did = int(param.get("did", 0))
            value = param.get("value")
            try:
                if telemetry_did_val is not None and did == telemetry_did_val and isinstance(value, list):
                    param["value"] = decode_s1p4(bytes(value))
                elif heartbeat_did_val is not None and did == heartbeat_did_val and isinstance(value, list):
                    param["value"] = decode_s1p1(bytes(value))
                elif config_did_val is not None and did == config_did_val and isinstance(value, dict):
                    param["value"] = decode_s2p51(value)
            except (InvalidS1P4Frame, InvalidS1P1Frame, S2P51DecodeError) as e:
                _LOGGER.warning(
                    "Discarding malformed blob (did=%d): %s", did, e
                )
                param["value"] = None
```

- [ ] **Step 3: Compile-check and run existing tests**

```bash
python3 -m compileall -q custom_components/dreame_a2_mower/dreame/device.py \
  custom_components/dreame_a2_mower/dreame/types.py
pytest tests/protocol/ -v
```

Expected: compile OK, all ~70 pytest tests still pass (the Plan B test suite exercises the pure decoders; this task only adds wiring in device.py which isn't yet pytest-covered).

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/dreame/device.py custom_components/dreame_a2_mower/dreame/types.py
git commit -m "feat(dreame): wire s1p1 heartbeat + s2p51 config decoders into blob dispatch"
```

---

### Task 6: Expose decoded telemetry on the coordinator

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py` (or wherever the `DreameMowerDevice` data is surfaced to HA)

Entities currently read `coordinator.device.data[<did>]`. After Tasks 4-5, `data[<mowing_telemetry_did>]` is a `MowingTelemetry` dataclass, `data[<heartbeat_did>]` is a `Heartbeat` dataclass, and `data[<config_did>]` is an `S2P51Event`.

We want entities to read atomic fields like position, area_mowed, phase. This task adds typed helper properties on the device (or coordinator) so sensor entities bind to simple attribute reads.

- [ ] **Step 1: Add convenience properties to `DreameMowerDevice`**

In `custom_components/dreame_a2_mower/dreame/device.py`, near the bottom of the `DreameMowerDevice` class (after other `@property` definitions), append:

```python
    @property
    def mowing_telemetry(self) -> "MowingTelemetry | None":
        """Return the most recently decoded s1p4 telemetry, or None if not seen."""
        from .types import DreameMowerProperty
        did_member = getattr(DreameMowerProperty, "MOWING_TELEMETRY", None)
        if did_member is None:
            return None
        return self.data.get(did_member.value)

    @property
    def heartbeat(self) -> "Heartbeat | None":
        """Return the most recently decoded s1p1 heartbeat, or None if not seen."""
        from .types import DreameMowerProperty
        did_member = getattr(DreameMowerProperty, "HEARTBEAT", None)
        if did_member is None:
            return None
        return self.data.get(did_member.value)

    @property
    def last_config_event(self) -> "S2P51Event | None":
        """Return the most recently decoded s2p51 config event, or None."""
        from .types import DreameMowerProperty
        did_member = getattr(DreameMowerProperty, "MULTIPLEXED_CONFIG", None)
        if did_member is None:
            return None
        return self.data.get(did_member.value)
```

- [ ] **Step 2: Compile-check**

```bash
python3 -m compileall -q custom_components/dreame_a2_mower/dreame/device.py
```

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/dreame/device.py
git commit -m "feat(dreame): expose mowing_telemetry, heartbeat, last_config_event properties"
```

---

### Task 7: Add HA sensor entities for decoded telemetry

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor.py`

**Background:** Upstream already defines several sensor entities. We add new ones that read from the coordinator's `mowing_telemetry` property. Follow the existing sensor registration pattern.

- [ ] **Step 1: Inspect existing sensor structure**

```bash
grep -nE "^class |^def |async_setup_entry|SensorEntityDescription|class .*Sensor" \
  custom_components/dreame_a2_mower/sensor.py | head -30
```

This reveals whether sensors use `SensorEntityDescription` + a dict-based registry, or subclass `SensorEntity` per type.

- [ ] **Step 2: Add five new sensors — position X, position Y, phase, session area, session distance**

Locate the existing sensor-description list or sensor-class definitions. Append five new entries that each call `coordinator.device.mowing_telemetry` and expose one field.

If upstream uses `SensorEntityDescription` + a `SENSOR_TYPES` list pattern:

```python
# Near the list of existing SENSOR_TYPES entries
_A2_TELEMETRY_SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="mowing_telemetry_x_mm",
        translation_key="mowing_telemetry_x_mm",
        name="Position X",
        native_unit_of_measurement="mm",
        icon="mdi:axis-x-arrow",
    ),
    SensorEntityDescription(
        key="mowing_telemetry_y_mm",
        translation_key="mowing_telemetry_y_mm",
        name="Position Y",
        native_unit_of_measurement="mm",
        icon="mdi:axis-y-arrow",
    ),
    SensorEntityDescription(
        key="mowing_phase",
        translation_key="mowing_phase",
        name="Mowing Phase",
        icon="mdi:state-machine",
    ),
    SensorEntityDescription(
        key="session_area_mowed_m2",
        translation_key="session_area_mowed_m2",
        name="Session Area Mowed",
        native_unit_of_measurement="m²",
        icon="mdi:texture-box",
    ),
    SensorEntityDescription(
        key="session_distance_m",
        translation_key="session_distance_m",
        name="Session Distance",
        native_unit_of_measurement="m",
        icon="mdi:map-marker-distance",
    ),
)
```

And a companion entity class with `native_value` switching on `key`:

```python
class DreameA2TelemetrySensor(CoordinatorEntity, SensorEntity):
    """Sensor backed by the decoded s1p4 telemetry struct."""

    def __init__(self, coordinator, description: SensorEntityDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device.mac}_{description.key}"

    @property
    def native_value(self):
        telem = self.coordinator.device.mowing_telemetry
        if telem is None:
            return None
        key = self.entity_description.key
        if key == "mowing_telemetry_x_mm":
            return telem.x_mm
        if key == "mowing_telemetry_y_mm":
            return telem.y_mm
        if key == "mowing_phase":
            return telem.phase.name.lower() if telem.phase else "unknown"
        if key == "session_area_mowed_m2":
            return telem.area_mowed_m2
        if key == "session_distance_m":
            return telem.distance_m
        return None
```

In `async_setup_entry`, append entries for each description:

```python
    entities.extend(
        DreameA2TelemetrySensor(coordinator, description)
        for description in _A2_TELEMETRY_SENSORS
    )
```

Exact wiring depends on upstream's pattern — adjust integration points based on what Step 1 revealed.

- [ ] **Step 3: Compile-check**

```bash
python3 -m compileall -q custom_components/dreame_a2_mower/sensor.py
```

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/sensor.py
git commit -m "feat(sensor): expose g2408 mowing telemetry as HA sensor entities"
```

---

### Task 8: Add binary sensor for `s1p53` obstacle flag

**Files:**
- Modify: `custom_components/dreame_a2_mower/binary_sensor.py` (create if absent)

**Background:** `s1p53` is a boolean flag the mower asserts when near obstacles or exclusion-zone boundaries. It's a simple property — no blob decoding needed. Just need to:
  1. Add `OBSTACLE_FLAG` to `DreameMowerProperty` enum and `_G2408_OVERLAY`.
  2. Add a binary sensor entity that reads `coordinator.device.data[OBSTACLE_FLAG.value]`.

- [ ] **Step 1: Extend enum and overlay**

In `custom_components/dreame_a2_mower/dreame/types.py`:

```python
    OBSTACLE_FLAG = 903
```

Extend `_G2408_OVERLAY`:

```python
    DreameMowerProperty.OBSTACLE_FLAG: {siid: 1, piid: 53},
```

- [ ] **Step 2: Check if `binary_sensor.py` exists**

```bash
ls custom_components/dreame_a2_mower/binary_sensor.py 2>&1
```

If absent, create with:

```python
"""Binary sensor entities for Dreame A2 Mower."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DreameMowerDataUpdateCoordinator
from .dreame.types import DreameMowerProperty


_BINARY_SENSORS: tuple[BinarySensorEntityDescription, ...] = (
    BinarySensorEntityDescription(
        key="obstacle_detected",
        translation_key="obstacle_detected",
        name="Obstacle Detected",
        device_class=BinarySensorDeviceClass.MOTION,
        icon="mdi:alert-octagon",
    ),
)


class DreameA2BinarySensor(CoordinatorEntity, BinarySensorEntity):
    def __init__(
        self,
        coordinator: DreameMowerDataUpdateCoordinator,
        description: BinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device.mac}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        did_member = getattr(DreameMowerProperty, "OBSTACLE_FLAG", None)
        if did_member is None:
            return None
        value = self.coordinator.device.data.get(did_member.value)
        if value is None:
            return None
        return bool(value)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DreameMowerDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        DreameA2BinarySensor(coordinator, description)
        for description in _BINARY_SENSORS
    )
```

If `binary_sensor.py` already exists, follow its existing pattern and append one entity description + one class case for `OBSTACLE_FLAG`.

- [ ] **Step 3: Register the platform in `__init__.py` if absent**

```bash
grep -n "PLATFORMS" custom_components/dreame_a2_mower/__init__.py
```

If `Platform.BINARY_SENSOR` is not in the `PLATFORMS` tuple, add it:

```python
from homeassistant.const import Platform

PLATFORMS = (
    Platform.LAWN_MOWER,
    Platform.CAMERA,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,  # <-- add this line
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.TIME,
)
```

- [ ] **Step 4: Compile-check**

```bash
python3 -m compileall -q custom_components/dreame_a2_mower/binary_sensor.py \
  custom_components/dreame_a2_mower/__init__.py \
  custom_components/dreame_a2_mower/dreame/types.py
```

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/__init__.py \
        custom_components/dreame_a2_mower/binary_sensor.py \
        custom_components/dreame_a2_mower/dreame/types.py
git commit -m "feat(binary_sensor): g2408 s1p53 obstacle detection flag"
```

---

### Task 9: Fix g2408 state-code translation

**Files:**
- Modify: entity module that renders the state sensor (usually `sensor.py` or a dedicated `lawn_mower.py`)

**Background:** g2408's s2p2 emits values like 70 (mowing), 54 (returning), 48 (mowing_complete), 50 (session_started), 27 (idle). Upstream's `DreameMowerState` / `DreameMowerStatus` enums map different values. A sensor that renders the mower's state will read `self.coordinator.device.data[STATE.value]` and translate the integer to a string label.

This task ensures that translation uses `protocol.properties_g2408.state_label` for known g2408 codes.

- [ ] **Step 1: Find the state-rendering entity**

```bash
grep -nrE "DreameMowerState|STATE.*value|state.*label|state_label" \
  custom_components/dreame_a2_mower/sensor.py \
  custom_components/dreame_a2_mower/lawn_mower.py 2>&1 | head
```

- [ ] **Step 2: Inject the g2408 label helper into the sensor's `native_value`**

Wherever the existing code has something like:

```python
native_value = DreameMowerState(value).name.lower()
```

replace with:

```python
from ..protocol.properties_g2408 import state_label
# ...
if self.coordinator.device._model == "dreame.mower.g2408":
    native_value = state_label(value)
else:
    native_value = DreameMowerState(value).name.lower()
```

The exact patch depends on what Step 1 revealed. If the existing translation logic is deep inside a method, wrap it with a model-check and fall back to the g2408-specific `state_label` for known g2408 codes.

- [ ] **Step 3: Compile-check**

```bash
python3 -m compileall -q custom_components/dreame_a2_mower/sensor.py \
  custom_components/dreame_a2_mower/lawn_mower.py
```

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/sensor.py custom_components/dreame_a2_mower/lawn_mower.py
git commit -m "feat(sensor): use g2408 state_label for s2p2 codes on model dreame.mower.g2408"
```

---

### Task 10: Deploy, restart HA, verify entities populate

**No file changes in the repo.** Deploy loop against live HA.

- [ ] **Step 1: Push all Plan C commits to origin**

```bash
git push origin main 2>&1 | tail -3
```

- [ ] **Step 2: Pull on HA + restart**

```bash
export HA_HOST=$(sed -n '1p' /data/claude/homeassistant/ha-credentials.txt)
export HA_USER=$(sed -n '2p' /data/claude/homeassistant/ha-credentials.txt)
export HA_PASS=$(sed -n '3p' /data/claude/homeassistant/ha-credentials.txt)
sshpass -p "$HA_PASS" ssh -o StrictHostKeyChecking=no "$HA_USER@$HA_HOST" \
  'cd /config/custom_components/dreame_a2_mower && git pull --ff-only && ha core restart'
```

- [ ] **Step 3: Wait for HA ready, watch logs for errors**

```bash
until sshpass -p "$HA_PASS" ssh -o StrictHostKeyChecking=no "$HA_USER@$HA_HOST" \
  'curl -s -o /dev/null -w "%{http_code}" http://172.30.32.1:8123/' 2>/dev/null | grep -q 200; do
  sleep 5
done
echo "HA up"
sshpass -p "$HA_PASS" ssh -o StrictHostKeyChecking=no "$HA_USER@$HA_HOST" \
  'ha core logs 2>&1 | grep -iE "dreame_a2_mower|Traceback" | head -40'
```

Expected: zero tracebacks from `dreame_a2_mower`, several `INFO` lines confirming setup completed and entities registered.

- [ ] **Step 4: Verify a real entity value**

The user (in the HA UI or via WebSocket) should now see, for entity `sensor.dreame_a2_mower_battery_level` (or similar — the exact entity_id depends on upstream's pattern), a real integer rather than "Unavailable". Same for state, obstacle, etc.

For programmatic verification (requires a long-lived token — user's profile → Security → Long-Lived Access Tokens):

```bash
export TOKEN=<user-provided-token>
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://$HA_HOST:8123/api/states" \
  | jq '.[] | select(.entity_id | test("dreame_a2_mower")) | {id:.entity_id, state:.state}'
```

Expected: JSON list showing each g2408 entity with a real `state` value (not "unavailable").

- [ ] **Step 5: Fix any uncovered divergences**

If entities still show "unavailable" for properties other than the ones explicitly overlaid, that means the siid/piid mismatch catalog from Task 1 missed an entry. Follow-up: extend `_G2408_OVERLAY` with the missing entries, commit, push, pull on HA, restart, reverify.

If no issues: proceed.

No commit for this task (it's pure deployment verification).

---

### Task 11: Secret sweep + push + tag v2.0.0-alpha.4

**No file changes.** Final hygiene and release tag.

- [ ] **Step 1: Secret sweep on working tree and history**

```bash
git ls-files -co --exclude-standard | xargs grep -HInE \
  'sshpass[[:space:]]+-p[[:space:]]+[^"$ ]|BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY|ghp_[A-Za-z0-9]{30,}|gho_[A-Za-z0-9]{30,}|(api[_-]?key|secret|password|passwd|token|bearer)[[:space:]]*[:=][[:space:]]*["\x27][^"\x27$][^"\x27]{4,}["\x27]' \
  2>/dev/null || echo "TREE_CLEAN"

git log --all -p | grep -nE \
  'sshpass[[:space:]]+-p[[:space:]]+[^"$ ]|BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY|ghp_[A-Za-z0-9]{30,}|gho_[A-Za-z0-9]{30,}' \
  || echo "HISTORY_CLEAN"
```

Expected: `TREE_CLEAN` and `HISTORY_CLEAN`.

- [ ] **Step 2: Tag alpha.4**

```bash
git tag -a v2.0.0-alpha.4 -m "Plan C complete — g2408 property overlay + blob decoders wired into HA entities"
git push origin v2.0.0-alpha.4
```

- [ ] **Step 3: Verify tag on GitHub**

```bash
gh api repos/okolbu/ha-dreame-a2-mower/tags --jq '.[0:4] | .[].name'
```

Expected: `v2.0.0-alpha.4` at top, preceded by alpha.3/2/1.

---

## Done-definition for Plan C

- `protocol/properties_g2408.py` (from Plan B) is consumed by `dreame/types.py` via `property_mapping_for_model`.
- `DreameMowerDevice.__init__` applies the g2408 overlay when model matches.
- `_message_callback` routes `s1p4`/`s1p1`/`s2p51` blobs through `protocol/` decoders.
- New HA sensors expose decoded telemetry fields (position, phase, area, distance).
- New binary sensor exposes `s1p53` obstacle flag.
- `s2p2` state codes translate via `state_label` for g2408.
- `ha core logs` shows no new Traceback from `dreame_a2_mower` after restart.
- Pre-existing entities that were "Unavailable" now show real values.
- Tag `v2.0.0-alpha.4` pushed.

## What Plan C deliberately does NOT do

Deferred to later plans — do not scope-creep:

- **Plan D:** MQTT-first write path (`client.publish` on start/stop/dock/settings actions). Requires a research spike to verify the mower listens on a command topic; unverified today.
- **Plan E:** Live map overlay (position trail, obstacle markers, robot/charger icons) — per spec's Phase 2.
- **Plan F:** Stripping non-g2408 model code (Mi auth, vacuum entities, other mower models) — large refactor with its own spec cycle.

- Upstreaming to the original `nicolasglg/dreame-mova-mower` repo — out of scope for this fork forever per spec.
- Supporting commands via cloud HTTP `sendCommand` — currently broken for g2408 (error 80001); Plan D will evaluate whether to retire the cloud path entirely.
