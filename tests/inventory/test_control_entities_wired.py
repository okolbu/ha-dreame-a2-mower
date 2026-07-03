"""CI guard: every concrete control-platform entity class must include _ControlHonestyMixin.

This test would have caught the six classes that were missed in the initial
control-honesty wiring (DreameA2AiHumanDetectionSwitch, DreameA2EdgeMowingAutoSwitch,
DreameA2EdgeMowingSafeSwitch, DreameA2EdgeMowingObstacleAvoidanceSwitch,
DreameA2ObstacleAvoidanceEnabledSwitch, DreameA2MapEdgemasterSwitch).

Strategy:
  1. AST-scan the package to find concrete DreameA2* entity classes on control
     platforms (switch / number / select / time). Sensor/camera/binary_sensor/
     button/lawn_mower are excluded — no read-only members and not wired.
  2. For each class found, import it from the actual module and assert
     issubclass(cls, _ControlHonestyMixin).

The AST scan mirrors the one in tools/inventory/entity_inventory_audit.py (same
_derives_from_entity / _class_graph logic), but filtered to control platforms
whose platform modules are in the known set.
"""
from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Repo / package paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
CC = REPO_ROOT / "custom_components" / "dreame_a2_mower"

# Make the package importable (the conftest already does this, but be safe).
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ---------------------------------------------------------------------------
# Control-platform source files to scan
# (sensor / camera / binary_sensor / button / lawn_mower are excluded)
# ---------------------------------------------------------------------------
_CONTROL_FILES: list[str] = [
    "switch_global.py",
    "switch_map.py",
    "_switch_base.py",
    "number.py",
    "_number_base.py",
    "select.py",
    "select_map_settings.py",
    "time.py",
]

# Classes that inherit from these HA base names are control-platform entities.
_CONTROL_HA_BASES = frozenset({
    "SwitchEntity",
    "NumberEntity",
    "SelectEntity",
    "TimeEntity",
})

# Classes used as a base by other classes in the scanned files (mixin/abstract).
# We filter them out dynamically below, but some are known non-leaf bases that
# aren't prefixed with "Dreame" or "_Dreame":
# _AiRecognitionBitSwitch, DreameA2Switch, DreameA2Number, etc.
# The dynamic leaf-detection handles these.


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _base_names(node: ast.ClassDef) -> list[str]:
    out: list[str] = []
    for b in node.bases:
        if isinstance(b, ast.Name):
            out.append(b.id)
        elif isinstance(b, ast.Attribute):
            out.append(b.attr)
    return out


def _is_control_ha_base(name: str) -> bool:
    return name in _CONTROL_HA_BASES


def _collect_classes_from_files() -> dict[str, tuple[str, list[str]]]:
    """Return {class_name: (relfile, [direct_base_names])} for all scanned files."""
    result: dict[str, tuple[str, list[str]]] = {}
    for fname in _CONTROL_FILES:
        fpath = CC / fname
        if not fpath.exists():
            continue
        try:
            tree = ast.parse(fpath.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                result[node.name] = (fname, _base_names(node))
    return result


def _derives_from_control_base(
    name: str,
    classes: dict[str, tuple[str, list[str]]],
    seen: set[str] | None = None,
) -> bool:
    """True if name transitively derives from a control HA entity base."""
    seen = seen or set()
    if name in seen:
        return False
    seen.add(name)
    if name not in classes:
        return _is_control_ha_base(name)
    _, bases = classes[name]
    for b in bases:
        if _is_control_ha_base(b):
            return True
        if _derives_from_control_base(b, classes, seen):
            return True
    return False


def _find_concrete_control_classes() -> list[tuple[str, str]]:
    """Return [(class_name, relfile)] for concrete DreameA2* control entities."""
    classes = _collect_classes_from_files()
    # Build set of all classes used as a base (abstract / mixin bases)
    used_as_base: set[str] = {b for (_fname, bases) in classes.values() for b in bases}
    result: list[tuple[str, str]] = []
    for name, (fname, _bases) in classes.items():
        if not name.startswith("DreameA2"):
            continue
        if name in used_as_base:
            continue  # abstract / mixin base — not a leaf entity
        if _derives_from_control_base(name, classes):
            result.append((name, fname))
    return sorted(result)


# ---------------------------------------------------------------------------
# Import helper
# ---------------------------------------------------------------------------

def _module_for_file(relfile: str) -> str:
    """Convert a relative filename to a Python module path."""
    stem = relfile.replace(".py", "").replace("/", ".")
    return f"custom_components.dreame_a2_mower.{stem}"


def _import_class(class_name: str, relfile: str):
    """Import and return the class object, or raise ImportError."""
    module_path = _module_for_file(relfile)
    # The switch.py platform re-exports everything; use that for switch_global/map.
    # For other files, import directly. Try both.
    try:
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name, None)
        if cls is not None:
            return cls
    except Exception:
        pass
    # Fallback: the platform entry switch.py re-exports all switch classes
    if "switch" in relfile:
        try:
            mod = importlib.import_module("custom_components.dreame_a2_mower.switch")
            cls = getattr(mod, class_name, None)
            if cls is not None:
                return cls
        except Exception:
            pass
    raise ImportError(f"Could not import {class_name} from {relfile}")


# ---------------------------------------------------------------------------
# Collection logic (factored out so the ImportError-handling behavior below
# is independently testable — T7-17)
# ---------------------------------------------------------------------------

def _collect_wiring_issues(
    concrete: list[tuple[str, str]], import_class=_import_class
) -> tuple[list[str], list[str]]:
    """Return (import_errors, mixin_failures) for the given concrete classes.

    ``import_class`` is injectable so tests can simulate a broken module
    without needing an actually-broken module in the repo.
    """
    from custom_components.dreame_a2_mower.control_honesty import _ControlHonestyMixin

    import_errors: list[str] = []
    failures: list[str] = []
    for class_name, relfile in concrete:
        try:
            cls = import_class(class_name, relfile)
        except ImportError as exc:
            import_errors.append(f"{class_name} ({relfile}): {exc}")
            continue
        if not issubclass(cls, _ControlHonestyMixin):
            failures.append(f"{class_name} ({relfile}) is missing _ControlHonestyMixin")
    return import_errors, failures


# ---------------------------------------------------------------------------
# The actual test
# ---------------------------------------------------------------------------

def test_every_control_entity_has_honesty_mixin() -> None:
    """All concrete control-platform DreameA2* classes must subclass _ControlHonestyMixin."""
    concrete = _find_concrete_control_classes()
    assert concrete, "No concrete control entity classes found — scan is broken"

    import_errors, failures = _collect_wiring_issues(concrete)

    # T7-17: an ImportError used to be silently `continue`d, so a broken/
    # renamed entity module quietly dropped out of this gate's coverage
    # with zero signal. Now it's a hard failure naming the module.
    assert not import_errors, (
        "The following control entity classes could not be imported — a "
        "broken module would silently skip its own wiring gate:\n"
        + "\n".join(f"  - {e}" for e in import_errors)
    )

    assert not failures, (
        "The following control entity classes are not wired with _ControlHonestyMixin:\n"
        + "\n".join(f"  - {f}" for f in failures)
    )


def test_import_error_is_reported_not_swallowed() -> None:
    """T7-17 regression: a class that fails to import must surface as a
    named import error, not silently vanish from the scan's coverage."""

    def _always_fails(class_name: str, relfile: str):
        raise ImportError(f"simulated broken module for {class_name}")

    import_errors, failures = _collect_wiring_issues(
        [("DreameA2FakeBrokenSwitch", "switch_global.py")],
        import_class=_always_fails,
    )
    assert failures == []
    assert len(import_errors) == 1
    assert "DreameA2FakeBrokenSwitch" in import_errors[0]
    assert "switch_global.py" in import_errors[0]
