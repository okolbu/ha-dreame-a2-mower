# Control-honesty markers — design (2026-06-04)

## Problem

Many control entities render an interactive HA control (number slider, select
dropdown, switch toggle) for a value the g2408 firmware does NOT apply. Dragging
`number.<map>_settings_mowing_height` moves and "sticks" but changes nothing on
the mower. The 2026-06-03 control-honesty audit
(`docs/research/control-honesty-audit-2026-06-03.md`) classified every control
entity and persisted the verdict as a `control_mode` field on each
`entity-inventory.yaml` row (shipped 2026-06-04, commit `2ca8d43`).

This design makes the integration **show** that verdict: a control that should be
writable but whose write path isn't unlocked **yet** wears a padlock and snaps
back instead of faking a save. The state is **temporal** — most read-only-today
controls are expected to become writable once their write path is found — so the
design optimises for *cheap, one-line flips* and keeps the read-only marker
distinct from inherently-observational sensors (lawn area, session totals), which
are `sensor` platform and never had a control affordance.

## Decisions (from brainstorm, user-approved)

- **Scope:** both integration + dashboard, but **integration-led** — the verdict
  lives on the entity so it's honest in every HA surface (voice, automations,
  every dashboard), not just one view.
- **Treatment:** **label + inert (snap-back)**, not "greyed/unavailable". The
  widget stays visible showing the live device value; a change reverts.
- **Marker:** a **padlock icon** (`mdi:lock-outline`) plus a `read_only` /
  `control_mode` extra-state-attribute — short, slug-safe, no verbose
  "(read-only)" name text, no entity_id churn.
- **Uniform snap-back for all three read-only modes, including `read_only_pending`.**
  The pending set (WRP/LANG/AI_HUMAN) is unproven-and-contradicted; blocking until
  a live probe settles it is the honest conservative default.
- **Architecture:** Approach 1 — a code-side `control_mode` source of truth + a
  shared mixin, with a CI test keeping code ↔ inventory in sync. (Rejected:
  codegen-from-inventory — too heavy for a single-user project; dashboard-only —
  not honest outside the one view.)

## The `control_mode` taxonomy

Six modes (already in `entity-inventory.yaml`):

| mode | audit bucket | operable? | padlock? |
|---|---|---|---|
| `device_writable` | A | yes — reaches & applies on firmware | no |
| `device_write_unproven` | B | yes — real RPC, not live-proven | no |
| `integration_local` | E | yes — controls integration state by design | no |
| `read_only_pending` | — | **no (snap-back)** — believed ineffective, unconfirmed | **yes** |
| `read_only_confirmed` | C | **no (snap-back)** — cloud accepts, firmware ignores | **yes** |
| `read_only_noop` | D | **no (snap-back)** — handler is a logged no-op | **yes** |

`READ_ONLY_MODES = {read_only_pending, read_only_confirmed, read_only_noop}`.

## Components

### 1. `control_honesty.py` (new) — code-side source of truth

A **pure-Python** module (no `homeassistant.*` imports, so it loads in the vanilla
stubbed-HA test venv):

```python
class ControlMode(StrEnum):
    DEVICE_WRITABLE = "device_writable"
    DEVICE_WRITE_UNPROVEN = "device_write_unproven"
    INTEGRATION_LOCAL = "integration_local"
    READ_ONLY_PENDING = "read_only_pending"
    READ_ONLY_CONFIRMED = "read_only_confirmed"
    READ_ONLY_NOOP = "read_only_noop"

READ_ONLY_MODES = frozenset({
    ControlMode.READ_ONLY_PENDING,
    ControlMode.READ_ONLY_CONFIRMED,
    ControlMode.READ_ONLY_NOOP,
})

# Keyed by the SAME entity-id templates as entity-inventory.yaml rows.
# Scalar for 1:1 entities; nested dict (keyed by CFG key) for the generic
# descriptor families (DreameA2Switch, DreameA2Number, DreameA2SettingSelect).
CONTROL_MODES: dict[str, ControlMode | dict[str, ControlMode]] = { ... }
```

`CONTROL_MODES` is the single place behaviour reads from. Keys mirror the inventory
rows exactly, so the sync test (below) is a direct comparison.

A resolver maps a live entity → its inventory-id template and returns the mode:

```python
def control_mode_for(*, platform: str, key_template: str,
                     cfg_key: str | None = None) -> ControlMode: ...
```

`key_template` is the entity's inventory id with the per-map index normalised to
`N` and the generic descriptor id collapsed to `<key>`. For the descriptor
families the nested `control_mode_by_key[cfg_key]` is used. The normalisation is
the one piece of mapping logic and is unit-tested directly.

### 2. `_ControlHonestyMixin` (in `control_honesty.py`)

Mixed into every control base class. It:

- Resolves `self.control_mode` once (via `control_mode_for`).
- Exposes `self.read_only -> bool` (`control_mode in READ_ONLY_MODES`).
- When `read_only`: overrides `icon` to `mdi:lock-outline` (unless the entity sets
  an explicit honesty-aware override) and contributes
  `{"control_mode": <mode>, "read_only": True}` to `extra_state_attributes`.
- Provides:

  ```python
  async def _reject_readonly_write(self) -> None:
      _LOGGER.info("%s: write ignored — no device write path yet (control_mode=%s)",
                   self.entity_id, self.control_mode)
      self.async_write_ha_state()   # re-publish unchanged state → widget snaps back
  ```

  No coordinator write, no optimistic MowerState mutation.

Operable modes contribute nothing — entity behaves exactly as today.

### 3. Per-platform integration (one guard per write handler)

Each control write handler short-circuits when read-only, *before* any coordinator
write or optimistic update:

```python
async def async_set_native_value(self, value: float) -> None:   # number
    if self.read_only:
        return await self._reject_readonly_write()
    ...existing write...
```

Same one-liner in `async_select_option` (select) and `async_turn_on` /
`async_turn_off` (switch). Applied at the **base** classes
(`_PerMapSettingsNumberBase`, `_select_base`, `_switch_base`, the per-map setting
bases, `DreameA2SettingSelect`, the AI/SETTINGS hand-coded classes) so it's uniform.
`time` is already read-only. `button` / `lawn_mower` have no read-only members; they
carry their `control_mode` only for the sync test.

This is where the misleading "it stuck" dies: read-only per-map settings never reach
`_settings_optimistic_write`.

### 4. CI sync gate — `tests/inventory/test_control_mode_code_sync.py` (new)

Asserts `CONTROL_MODES` (code) equals the `control_mode` / `control_mode_by_key`
verdicts in `entity-inventory.yaml`, **both directions** — every inventory control
row has a matching code entry and vice-versa, with equal values. Runs in the vanilla
venv (imports the pure module + `yaml.safe_load`s the inventory). Complements the
existing `test_control_mode_gate.py`, which enforces that every inventory control row
*has* a valid mode.

### 5. Dashboard (the "both")

No restructure — the padlock icon and `read_only` attribute flow into every card
automatically. One addition: a markdown note on the **Settings & Zones** tab header,
e.g. `🔒 = control present, device write path not unlocked yet`. The bundled
dashboard ships via the existing SCP deploy procedure
(`reference_ha_dashboard_deploy`); no HA restart.

## The flip workflow (load-bearing requirement)

When a probe unlocks a write path for an entity:

1. Change its line in `CONTROL_MODES` (`READ_ONLY_* → DEVICE_WRITABLE`).
2. Update the matching `entity-inventory.yaml` row (the sync test fails until you do
   — it *reminds* you, so the two SoTs can't silently drift).

Result: padlock, `read_only` attribute, and snap-back all vanish; the widget becomes
live. **No platform change, no entity_id change, no migration.** This is the whole
point of keeping the entity on its control platform rather than swapping it to a
`sensor`.

## Testing (TDD)

- Mixin unit tests: `control_mode_for` normalisation (per-map `N`, generic `<key>`,
  cfg-key families); padlock icon + attributes appear only for read-only modes;
  operable modes are untouched; `_reject_readonly_write` re-publishes state and does
  **not** call any coordinator write.
- Per-platform: a read-only number/select/switch write is a no-op + reverts; an
  operable one still writes (regression guard).
- CI sync gate + the existing presence gate.
- Full suite stays green (baseline 1878 passed / 4 skipped after step (a)).

## Scope / non-goals

- Does **not** resolve the WRP/LANG/AI_HUMAN A-vs-C contradiction — that's the
  separate live re-probe; they ride at `read_only_pending` and snap back until then.
- Does **not** touch observational sensors (`sensor` platform — never had a control;
  the distinction the user drew falls out structurally).
- Does **not** unlock any new writable surface — honesty-of-representation only.
- `device_write_unproven` (B: stop/pause/dock/op=200/op=10/op=12) renders as a
  normal operable control (no padlock). Marking B as "provisional" is deferred (TODO
  done-when #3).

## Files touched

- New: `custom_components/dreame_a2_mower/control_honesty.py`
- Edit (mixin + guard + per-descriptor/class `control_mode`): `number.py`,
  `select.py` / `select_global.py` / `select_map_settings.py` / `_select_base.py`,
  `switch.py` / `switch_global.py` / `switch_map.py` / `_switch_base.py`, `time.py`,
  `lawn_mower.py`, `button.py`
- New test: `tests/inventory/test_control_mode_code_sync.py` + mixin/platform behaviour tests
- Edit: bundled `dashboards/mower/dashboard.yaml` (one header note)
- Already done in (a): `entity-inventory.yaml` `control_mode` + `tests/inventory/test_control_mode_gate.py`

## Lifecycle

Per repo doc-canonicity: this spec is in-tree during implementation and moves to
`OLD/ha-dreame-a2-mower-docs/superpowers/specs/` when the branch is finished.
