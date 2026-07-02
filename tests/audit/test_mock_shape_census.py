"""AST census (T7-2 / R-4 permanent gate): a test fake must not define as a
plain method something the production class it stands in for defines as a
``@property``.

This is exactly how the ``mqtt_is_fresh`` bug (R-4 / T3-1 / T7-1) hid for
months: ``mqtt_client.py``'s ``is_connected`` is a ``@property``;
``coordinator/_core.py`` called it as a method (``mqtt.is_connected()``),
which raises ``TypeError`` on the REAL client — swallowed by a bare
``except``, silently degrading ``mqtt_is_fresh`` to ``cloud_is_fresh``
forever. ``tests/integration/test_availability.py``'s ``_FakeMqtt`` hand-
rolled ``is_connected`` as a callable ``def``, so the same call site was a
normal successful call against the fake — the bug never surfaced in the
unit suite, only against the real class. The fake's *shape* diverged from
the production class it stood in for.

Scope (seeded, name-heuristic based — extend ``_PROD_CLASSES`` below if a
new hand-rolled fake for one of these classes appears):

- ``DreameA2MqttClient``       (``mqtt_client.py``)        — fake name /mqtt/i
- ``DreameA2CloudClient``      (``cloud_client/`` package)  — fake name /cloud/i
- ``DreameA2MowerCoordinator`` (``coordinator/`` package)   — fake name /coord/i

A class defined anywhere under ``tests/`` is treated as a "fake stand-in" for
one of the above when its name starts with ``Fake``/``_Fake``/``Mock`` AND
matches that production class's name heuristic (e.g. ``_FakeMqtt``,
``FakeCloudClient``, ``MockCoordinator``). Real ``unittest.mock.MagicMock()``
instances are exempt — they don't hard-code a wrong shape, they absorb any
attribute access (a different, already-tracked risk: T7-3/T7-8). For every
matched fake, every attribute it defines as a ``def``/``async def`` sharing a
name with a ``@property`` on the mapped production class is a shape mismatch
and fails the test.

This deliberately does not attempt full inheritance/type resolution across
the whole codebase — it collects ``@property`` names from the known files
that make up each production class (mirroring the file tables in the
top-level ``CLAUDE.md`` "Coordinator structure" / "Cloud client structure"
sections) and compares by name only. That is sufficient to catch the exact
failure class above without building a type checker.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CC = REPO_ROOT / "custom_components" / "dreame_a2_mower"
TESTS_DIR = REPO_ROOT / "tests"

# Production class name -> (fake-name heuristic regex, [source files that may
# contribute @property definitions to that class]).
_PROD_CLASSES: dict[str, tuple[re.Pattern[str], list[Path]]] = {
    "DreameA2MqttClient": (
        re.compile(r"mqtt", re.IGNORECASE),
        [CC / "mqtt_client.py"],
    ),
    "DreameA2CloudClient": (
        re.compile(r"cloud", re.IGNORECASE),
        [CC / "cloud_client" / "__init__.py"]
        + sorted((CC / "cloud_client").glob("_*.py")),
    ),
    "DreameA2MowerCoordinator": (
        re.compile(r"coord", re.IGNORECASE),
        [CC / "coordinator" / "__init__.py"]
        + sorted((CC / "coordinator").glob("_*.py")),
    ),
}

# A test class counts as a "fake" candidate when its name looks hand-rolled
# for a specific production type (as opposed to e.g. `_FakeHass`, which never
# matches any of the heuristics above and is correctly ignored).
_FAKE_NAME_RE = re.compile(r"^_?(Fake|Mock)")


def _property_names(files: list[Path]) -> set[str]:
    """Collect all ``@property``-decorated method names across ``files``."""
    names: set[str] = set()
    for fpath in files:
        if not fpath.exists():
            continue
        tree = ast.parse(fpath.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and any(
                    isinstance(d, ast.Name) and d.id == "property"
                    for d in item.decorator_list
                ):
                    names.add(item.name)
    return names


def _method_names(node: ast.ClassDef) -> set[str]:
    """Names the fake class defines as a plain (non-property) method."""
    out: set[str] = set()
    for item in node.body:
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        is_property = any(
            isinstance(d, ast.Name) and d.id == "property"
            for d in item.decorator_list
        )
        if not is_property:
            out.add(item.name)
    return out


def _fake_classes_in_tests() -> list[tuple[str, str, ast.ClassDef]]:
    """Return ``(class_name, relfile, node)`` for every Fake/Mock class
    defined anywhere under ``tests/``."""
    out: list[tuple[str, str, ast.ClassDef]] = []
    for fpath in TESTS_DIR.rglob("*.py"):
        try:
            tree = ast.parse(fpath.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and _FAKE_NAME_RE.match(node.name):
                out.append((node.name, str(fpath.relative_to(REPO_ROOT)), node))
    return out


def test_seed_sanity_finds_known_properties_and_fakes():
    """Guards the census itself from silently going vacuous (e.g. a path
    typo in ``_PROD_CLASSES`` that makes ``_property_names`` return empty)."""
    props = {
        cls_name: _property_names(files)
        for cls_name, (_pat, files) in _PROD_CLASSES.items()
    }
    assert "is_connected" in props["DreameA2MqttClient"]
    assert props["DreameA2CloudClient"], "expected >=1 @property on DreameA2CloudClient"
    assert props["DreameA2MowerCoordinator"], "expected >=1 @property on DreameA2MowerCoordinator"

    fakes = _fake_classes_in_tests()
    assert fakes, "expected >=1 Fake/Mock class under tests/ — scan is broken"
    assert any(name == "_FakeMqtt" for name, _relfile, _node in fakes)


def test_no_fake_defines_a_prod_property_as_a_method():
    """The permanent gate: no ``Fake*``/``Mock*`` class in tests/ may define
    a name as a plain method that the production class it stands in for
    defines as a ``@property``.

    Ablated 2026-07-03 by reverting ``_FakeMqtt.is_connected`` back to a
    plain ``def`` — this test failed with exactly the
    ``tests/integration/test_availability.py`` violation before the fix
    landed; restored to ``@property`` it passes.
    """
    prod_props = {
        cls_name: _property_names(files)
        for cls_name, (_pat, files) in _PROD_CLASSES.items()
    }

    violations: list[str] = []
    for name, relfile, node in _fake_classes_in_tests():
        for cls_name, (pattern, _files) in _PROD_CLASSES.items():
            if not pattern.search(name):
                continue
            clash = _method_names(node) & prod_props[cls_name]
            if clash:
                violations.append(
                    f"{relfile}: class {name} defines {sorted(clash)} as a "
                    f"plain method, but {cls_name} defines "
                    f"{sorted(clash)} as a @property (mock-mask risk — see "
                    f"R-4 / T3-1 / T7-1)"
                )

    assert not violations, (
        "test fake shape mismatch(es) found — a fake defines as a method\n"
        "what the production class defines as a @property (the class of bug\n"
        "that hid the mqtt_is_fresh/is_connected TypeError):\n"
        + "\n".join(violations)
    )
