"""Grep-gate (P3 Task 2, T2-16 pre-step): zero string-getattr on coordinator
PRIVATE attrs from the entity/camera/service layers.

Why this exists: ``getattr(coordinator, "_foo", default)`` in an entity,
camera, or service-layer file reaches into the coordinator's private state by
STRING NAME. When the domain-service extraction (P3.8) moves ``_foo`` off the
coordinator and onto its owning service, a plain string getattr does not
break loudly — it silently keeps returning ``default`` forever, because
``getattr`` treats "attribute renamed/removed" and "attribute genuinely
absent right now" identically. That's the exact "silent breakage" trap
track-2 §d2 documents (top offenders were ``_cloud``x9, ``_active_map_id``x8,
``_wifi_archive_index``x4, ``_render_base``x3 — see
``refactor-2026-07-02/findings/track-2-architecture.md``).

The fix (already applied by this task): every such site was converted to a
typed accessor/property on the coordinator (``coordinator/_core.py``, each
tagged "transitional accessor (P3.2)"). A typed accessor is a normal
attribute/property reference — when P3.8 moves the backing attr into a
service, the accessor moves with it (or the reference breaks LOUDLY with an
``AttributeError``/``mypy`` error instead of silently degrading).

This test is a ratchet, not a one-time check: it re-greps production code on
every run so a NEW string-getattr on a coordinator private attr in the
entity/camera/service layers fails CI immediately, the same day it's added.

Scope, precisely:
- Scans every ``*.py`` under ``custom_components/dreame_a2_mower/`` EXCEPT
  the ``coordinator/`` package itself. Mixins reaching sibling-mixin attrs
  via ``getattr(self, "_foo", ...)`` are the same object reaching its own
  state — not the bypass this gate targets — so ``coordinator/`` is exempt.
- Flags ``getattr(<var>, "_name", ...)`` only when ``<var>`` is one of the
  coordinator-reference spellings actually used across the codebase:
  ``self.coordinator``, ``coordinator``, ``coord``. This deliberately does
  NOT flag ``getattr(cloud, "_foo", ...)`` / ``getattr(mqtt, "_foo", ...)`` —
  getattr on a NON-coordinator object (the cloud client, the mqtt client, an
  archive) is a different, not-yet-scoped risk; sweeping it in here would
  blur what this gate actually guarantees.
- Attr name must start with ``_`` (private-by-convention). Public accessors
  (``coordinator.sn``, ``coordinator.cloud_state``, ...) are the coordinator's
  real contract and are unaffected by this rule.

BASELINE is 0 and must stay 0. If you have a new legitimate reason to reach a
coordinator private attr by string from outside `coordinator/`, add a typed
accessor to ``coordinator/_core.py`` instead (see the "Transitional
accessors (P3.2 string-getattr burn-down...)" block) and call the accessor.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CC = REPO_ROOT / "custom_components" / "dreame_a2_mower"

# Coordinator-reference spellings observed across the codebase (grep census,
# 2026-07-04): the bound entity attribute, and the two common local-variable/
# parameter names used in module-level helper functions and services.py
# handlers.
_COORD_REFS = (r"self\.coordinator", r"coordinator", r"coord")

_BYPASS_PATTERN = re.compile(
    r'getattr\(\s*(?:' + "|".join(_COORD_REFS) + r')\s*,\s*"(_[A-Za-z0-9_]+)"'
)

# Ratchet baseline — total occurrence count across custom_components/, minus
# the coordinator/ package itself. P3 Task 2 pin. Must stay 0.
BASELINE = 0


def _census() -> tuple[int, dict[str, list[str]]]:
    per_file: dict[str, list[str]] = {}
    for path in sorted(CC.rglob("*.py")):
        rel = path.relative_to(CC)
        if rel.parts[0] == "coordinator":
            continue
        if "__pycache__" in rel.parts:
            continue
        if any(part.startswith(".") for part in rel.parts):
            # Stray filesystem artifacts (e.g. macOS AppleDouble
            # `.__foo.py` / `._foo.py` resource-fork files) are not
            # importable modules and are not tracked by git — skip
            # anything dotfile-shaped rather than choke on binary bytes.
            continue
        text = path.read_text(encoding="utf-8")
        hits = _BYPASS_PATTERN.findall(text)
        if hits:
            per_file[str(rel)] = hits
    total = sum(len(v) for v in per_file.values())
    return total, per_file


def test_no_coordinator_private_getattr():
    total, per_file = _census()
    listing = "\n".join(f"  {f}: {names}" for f, names in sorted(per_file.items()))
    assert total == BASELINE, (
        f"String-getattr on a coordinator private attr found OUTSIDE "
        f"coordinator/: {total} > baseline {BASELINE}.\n"
        f"Add a typed accessor/property to coordinator/_core.py (see the "
        f"'Transitional accessors (P3.2 string-getattr burn-down)' block) "
        f"and call the accessor instead of getattr(coordinator, \"_foo\", "
        f"default) — a string getattr silently returns the default forever "
        f"once the P3.8 domain-service extraction moves the attr off the "
        f"coordinator.\nOffending sites:\n{listing}"
    )
