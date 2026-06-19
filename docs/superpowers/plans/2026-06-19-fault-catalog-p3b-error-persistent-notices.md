# Error-tier persistent notices (P3b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Post a `persistent_notification` for each error-tier s2p2 fault (created on detect, dismissed on clear) with localized catalog solution text; no other tier gets a banner.

**Architecture:** Add a notice helper pair to `_DeviceSyncMixin` and call them inside the existing `_fire_fault_delta` loops (which already iterate newly-detected / newly-cleared error codes with `lang` resolved). `snapshot.errors` only ever holds error-tier codes, so no tier check is needed beyond excluding emergency-stop (code 23, owned by the dedicated PIN handler). No state-machine change.

**Tech Stack:** Python, Home Assistant custom integration, pytest. Test runner (from repo root): `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest`.

**Spec:** `docs/superpowers/specs/2026-06-19-fault-catalog-p3b-error-persistent-notices-design.md`

**Key facts (verified):**
- `_fire_fault_delta(self, prev_errors, new_errors, *, now_unix)` lives at `coordinator/_device_sync.py:336-359`; it resolves `lang = fault_catalog.resolve_lang(getattr(cfg,"language",None))` then loops `sorted(new_errors - prev_errors)` (detected) and `sorted(prev_errors - new_errors)` (cleared), firing `_fire_lifecycle(EVENT_TYPE_FAULT_DETECTED/CLEARED, {...})`.
- The emergency-stop notice (`_handle_emergency_stop_transition`, lines 146-194) uses `notification_id=f"{DOMAIN}_emergency_stop_{self.entry.entry_id}"` and lazily `from homeassistant.components import persistent_notification as _pn` inside try/except. `DOMAIN` is imported at `_device_sync.py:33`. `self.entry.entry_id` + `self.hass` are available on the real coordinator.
- `fault_catalog.fault_text(code, lang)` and `fault_catalog.fault_detail(code, lang)` (both `str | None`) are the title/body sources.
- Only error-tier codes latch (`is_fault(code)` ⟺ `fault_tier=="error"`), so the delta only ever carries error-tier codes.
- Test harness: `tests/coordinator/test_fault_events.py` builds a `types.SimpleNamespace` and binds mixin methods via `types.MethodType` (see `_make_coord`, lines 34-57). `_DeviceSyncMixin` imports fine in the venv (HA imports are lazy).

---

### Task 1: Persistent-notice helpers + hook into `_fire_fault_delta`

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_device_sync.py` (add helpers near `_handle_emergency_stop_transition` ~line 194; add two calls in `_fire_fault_delta` ~lines 348-358)
- Test: `tests/coordinator/test_fault_events.py` (append a harness + tests)

- [ ] **Step 1: Write the failing tests.** Append to `tests/coordinator/test_fault_events.py`:

```python
import sys


class _FakePN:
    """Records persistent_notification.async_create/async_dismiss calls."""
    def __init__(self):
        self.created: list[dict] = []
        self.dismissed: list[str] = []

    def async_create(self, hass, *, message, title, notification_id):
        self.created.append(
            {"message": message, "title": title, "notification_id": notification_id}
        )

    def async_dismiss(self, hass, *, notification_id):
        self.dismissed.append(notification_id)


def _install_fake_pn(monkeypatch) -> _FakePN:
    """Inject a fake homeassistant.components.persistent_notification so the
    lazy `from homeassistant.components import persistent_notification` inside
    the notice helpers resolves to our recorder."""
    fake = _FakePN()
    # Ensure the parent packages exist as modules, then bind the submodule.
    ha = sys.modules.get("homeassistant") or types.ModuleType("homeassistant")
    comp = sys.modules.get("homeassistant.components") or types.ModuleType(
        "homeassistant.components"
    )
    monkeypatch.setitem(sys.modules, "homeassistant", ha)
    monkeypatch.setitem(sys.modules, "homeassistant.components", comp)
    monkeypatch.setitem(
        sys.modules, "homeassistant.components.persistent_notification", fake
    )
    monkeypatch.setattr(comp, "persistent_notification", fake, raising=False)
    return fake


def _make_coord_with_notice() -> types.SimpleNamespace:
    """_make_coord() + the attrs the notice helpers need (entry, hass)."""
    coord = _make_coord()
    coord.entry = types.SimpleNamespace(entry_id="e1")
    coord.hass = types.SimpleNamespace(config=types.SimpleNamespace(language="en"))
    for name in ("_fault_notification_id", "_post_fault_notice", "_dismiss_fault_notice"):
        setattr(coord, name, types.MethodType(getattr(_DeviceSyncMixin, name), coord))
    return coord


def test_error_fault_posts_persistent_notice_on_detect(monkeypatch):
    fake = _install_fake_pn(monkeypatch)
    coord = _make_coord_with_notice()
    coord._fire_fault_delta(frozenset(), frozenset({7}), now_unix=1000)  # 7 = cutter (error)
    assert len(fake.created) == 1
    n = fake.created[0]
    assert n["notification_id"] == "dreame_a2_mower_fault_7_e1"
    assert fc.fault_text(7, "en") in n["title"]
    assert n["message"] == (fc.fault_detail(7, "en") or fc.fault_text(7, "en"))
    assert fake.dismissed == []


def test_error_fault_dismisses_persistent_notice_on_clear(monkeypatch):
    fake = _install_fake_pn(monkeypatch)
    coord = _make_coord_with_notice()
    coord._fire_fault_delta(frozenset({7}), frozenset(), now_unix=1100)
    assert fake.dismissed == ["dreame_a2_mower_fault_7_e1"]
    assert fake.created == []


def test_emergency_stop_code_excluded_from_fault_notice(monkeypatch):
    fake = _install_fake_pn(monkeypatch)
    coord = _make_coord_with_notice()
    coord._fire_fault_delta(frozenset(), frozenset({23}), now_unix=1000)
    coord._fire_fault_delta(frozenset({23}), frozenset(), now_unix=1100)
    assert fake.created == [] and fake.dismissed == []  # PIN handler owns code 23


def test_fault_notice_body_falls_back_to_title_when_no_detail(monkeypatch):
    fake = _install_fake_pn(monkeypatch)
    coord = _make_coord_with_notice()
    # Pick an error-tier code whose catalog detail is empty; assert no crash and
    # message == title text. The implementer must choose such a code by checking
    # fc.fault_detail(code,"en") is falsy AND fc.fault_tier(code)=="error"; if none
    # exists, assert the general invariant instead: message is non-empty for every
    # error code.
    for code in sorted(fc.error_tier_codes("iot")):
        fake.created.clear()
        coord._fire_fault_delta(frozenset(), frozenset({code}), now_unix=1)
        if code == 23:
            continue
        assert fake.created, f"no notice for error code {code}"
        msg = fake.created[0]["message"]
        assert msg, f"empty notice body for code {code}"


def test_fault_notice_localized(monkeypatch):
    fake = _install_fake_pn(monkeypatch)
    coord = _make_coord_with_notice()
    coord.hass.config.language = "nb"
    # Choose an error-tier code whose nb text differs from en (verify in catalog).
    code = 7
    coord._fire_fault_delta(frozenset(), frozenset({code}), now_unix=1)
    assert fc.fault_text(code, "nb") in fake.created[0]["title"]
    # guard the test is meaningful: nb must differ from en for this code
    assert fc.fault_text(code, "nb") != fc.fault_text(code, "en")


def test_fault_notice_failure_does_not_break_delta(monkeypatch):
    fake = _install_fake_pn(monkeypatch)
    def _boom(*a, **k):
        raise RuntimeError("pn down")
    fake.async_create = _boom
    coord = _make_coord_with_notice()
    lc = _RecordingLifecycle()
    coord.register_event_entities(lifecycle=lc, notification=coord._notification_event)
    # Must not raise; the lifecycle event must still fire.
    coord._fire_fault_delta(frozenset(), frozenset({7}), now_unix=1)
    assert any(et == EVENT_TYPE_FAULT_DETECTED for et, _ in lc.fired)
```
> NOTE: if `register_event_entities`'s signature differs, set `coord._lifecycle_event = lc` directly (the harness already pre-sets `_lifecycle_event`/`_notification_event`). Adapt to the existing `_make_coord` wiring — don't invent a new lifecycle harness.

- [ ] **Step 2: Run to verify failure.**
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_fault_events.py -k "persistent_notice or fault_notice or emergency_stop_code_excluded" -q`
Expected: FAIL (`_post_fault_notice` / `_fault_notification_id` not defined; AttributeError).

- [ ] **Step 3: Implement the helpers.** In `coordinator/_device_sync.py`, add right after `_handle_emergency_stop_transition` (~line 194), inside `class _DeviceSyncMixin`:
```python
    # Codes the generic fault-notice path must NOT touch: emergency-stop (23)
    # has its own PIN-entry persistent notice via _handle_emergency_stop_transition.
    _EMERGENCY_STOP_CODE = 23

    def _fault_notification_id(self, code: int) -> str:
        return f"{DOMAIN}_fault_{int(code)}_{self.entry.entry_id}"

    def _post_fault_notice(self, code: int, lang: str) -> None:
        """Post a persistent_notification for a newly-detected error-tier fault.

        Title = the catalog fault_text; body = the catalog detail (solution
        steps) when present, else the fault_text. Skips emergency-stop (its
        dedicated PIN notice owns code 23). Wrapped in try/except so a UI-notice
        failure never breaks fault handling (mirrors _handle_emergency_stop_transition)."""
        if int(code) == self._EMERGENCY_STOP_CODE:
            return
        from ..mower import fault_catalog
        title = fault_catalog.fault_text(int(code), lang) or f"Fault {int(code)}"
        body = fault_catalog.fault_detail(int(code), lang) or title
        try:
            from homeassistant.components import persistent_notification as _pn
            _pn.async_create(
                self.hass,
                message=body,
                title=f"Dreame A2 Mower — {title}",
                notification_id=self._fault_notification_id(code),
            )
            LOGGER.info("fault %d active — persistent_notification posted", int(code))
        except Exception as ex:
            LOGGER.warning("fault %d notice create failed: %s", int(code), ex)

    def _dismiss_fault_notice(self, code: int) -> None:
        """Dismiss the persistent_notification for a cleared error-tier fault."""
        if int(code) == self._EMERGENCY_STOP_CODE:
            return
        try:
            from homeassistant.components import persistent_notification as _pn
            _pn.async_dismiss(
                self.hass, notification_id=self._fault_notification_id(code)
            )
            LOGGER.info("fault %d cleared — persistent_notification dismissed", int(code))
        except Exception as ex:
            LOGGER.warning("fault %d notice dismiss failed: %s", int(code), ex)
```

- [ ] **Step 4: Hook into `_fire_fault_delta`.** In the same file, add the two calls inside the existing loops (lines ~348-358) so the method becomes:
```python
        for code in sorted(new_errors - prev_errors):
            self._fire_lifecycle(
                EVENT_TYPE_FAULT_DETECTED,
                {"code": int(code), "description": describe_error(int(code), lang),
                 "at_unix": int(now_unix)},
            )
            self._post_fault_notice(int(code), lang)
        for code in sorted(prev_errors - new_errors):
            self._fire_lifecycle(
                EVENT_TYPE_FAULT_CLEARED,
                {"code": int(code), "description": describe_error(int(code), lang),
                 "at_unix": int(now_unix)},
            )
            self._dismiss_fault_notice(int(code))
```

- [ ] **Step 5: Run to verify pass.**
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_fault_events.py -q`
Expected: PASS (new + existing). If `test_fault_notice_localized` fails because code 7's nb text equals en, switch `code` to another error-tier code that differs (verify with `fc.fault_text(code,"nb") != fc.fault_text(code,"en")`).

- [ ] **Step 6: Commit** (stage only the two files by path; never `git add -A`; do NOT stage `tools/probes/*`):
```bash
git add custom_components/dreame_a2_mower/coordinator/_device_sync.py tests/coordinator/test_fault_events.py
git commit -m "feat(p3b): error-tier faults post/dismiss a persistent_notification"
```

---

### Task 2: Guard test, docs, full suite, release

**Files:**
- Test: `tests/coordinator/test_fault_events.py` (one guard test) — or `tests/mower/`
- Modify: `custom_components/dreame_a2_mower/inventory.yaml` (note the surfacing)
- Regenerate: `docs/research/inventory/generated/g2408-canonical.md`

- [ ] **Step 1: Guard test — attention/alert/info are never persisted.** Append to `tests/coordinator/test_fault_events.py`:
```python
def test_only_error_tier_latches_so_only_error_tier_persists():
    """Persistent notices ride snapshot.errors, which latches ONLY error-tier
    codes (is_fault ⟺ fault_tier=='error'). This pins the invariant so a future
    change that latches attention/alert codes can't silently start persisting them."""
    from custom_components.dreame_a2_mower.mower.error_codes import is_fault
    for code in fc.known_codes("iot"):
        tier = fc.fault_tier(code)
        assert is_fault(code) == (tier == "error"), (
            f"code {code} tier={tier} but is_fault={is_fault(code)}"
        )
    # And attention exemplars are NOT error-tier (so never latched/persisted):
    for attn in (28, 30):  # blade_loss, maintain_loss (FAULT + consumable/work_message)
        if attn in fc.known_codes("iot"):
            assert fc.fault_tier(attn) == "attention"
            assert not is_fault(attn)
```

- [ ] **Step 2: Run the guard + the fault suite.**
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_fault_events.py -q`
Expected: PASS. (If 28 or 30 is not "attention" in the catalog, adjust to the actual attention-tier codes — verify with `fc.fault_tier`.)

- [ ] **Step 3: Inventory note + canonical regen.** In `inventory.yaml § s2p2`, add a 2026-06-19 `verified` note: error-tier faults (`fault_tier=="error"`, the latched `snapshot.errors` set) now surface a `persistent_notification` (id `dreame_a2_mower_fault_<code>_<entry>`, title=catalog fault_text, body=catalog detail), created on fault_detected and dismissed on fault_cleared; emergency-stop (23) excluded (its PIN notice owns it); attention/alert/info stay transient (notification event + logbook), app-faithful `[apk:g2408-plugin-ext1423]`. Then validate + regenerate:
```bash
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py
```
Inspect `git diff` on the canonical doc; exclude unrelated churn (wire-census etc.).

- [ ] **Step 4: Full suite.**
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q`
Expected: all pass (baseline 2602 passed / 5 skipped + the new P3b tests; zero failures).

- [ ] **Step 5: Commit.** (stage by explicit path)
```bash
git add tests/coordinator/test_fault_events.py custom_components/dreame_a2_mower/inventory.yaml docs/research/inventory/generated/g2408-canonical.md
git commit -m "docs(p3b): inventory note for error-tier persistent notices + canonical regen"
```

- [ ] **Step 6: Release + live-verify (controller).** The controller (not a subagent) merges the P3b branch to main, pushes (after reconciling origin if a concurrent process advanced it), and runs `tools/release/release.sh <next-version>` — note the HACS digit-boundary rule (next after 1.0.30a1 is 1.0.30a2, which sorts fine). Then installs via HACS + restarts HA and verifies: a still-active error fault posts a "Dreame A2 Mower — …" persistent notification with solution text; attention/alert codes show only in logbook/history (no banner). Until a live error fault occurs, the behavior is verified by the test suite.

---

## Self-Review notes
- **Spec coverage:** A (helpers) → T1 step 3; B (hook) → T1 step 4; C (restart idempotency) → inherent (same notification_id re-creates in place; covered conceptually, exercised live). Testing bullets → T1 steps 1–5 + T2 step 1.
- **Type consistency:** `_fault_notification_id(code:int)->str`, `_post_fault_notice(code:int, lang:str)`, `_dismiss_fault_notice(code:int)`, `_EMERGENCY_STOP_CODE=23` — consistent across tasks and tests.
- **No state-machine change.** Only `_device_sync.py` + tests + inventory/docs.
- **Test-env HA:** the lazy `from homeassistant.components import persistent_notification` is intercepted by injecting a fake module into `sys.modules` (T1 `_install_fake_pn`); mirrors how the mixin already imports it lazily.
- **Risk:** localization test depends on a code whose nb≠en — the plan says verify/swap the code. The detail-fallback test iterates all error codes asserting non-empty body, which doubles as a "every error code produces a usable notice" check.
