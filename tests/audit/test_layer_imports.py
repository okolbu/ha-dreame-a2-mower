"""Durable back-edge gate (P3 Task 4, R-30/T2-5 + R-29a/T2-4): AST-based check
that every module-level import inside ``custom_components/dreame_a2_mower/``
points DOWNWARD per the target layer model
(``docs/superpowers/specs/2026-07-02-refactor-v2-target-architecture.md`` §1):

    6  presentation   render/ (map_render), camera/, dashboard/
    5  entities       descriptor-driven platforms, services (HA API)
    4  domain         session/, writes/, media/, wifi/, lidar/, notifications/,
                      device_sync, ingress — realized today by coordinator/,
                      archive/, wifi/ (+ their root re-export shims)
    3  state          MowerState, StateSnapshot, MowerStateMachine, CloudState,
                      apply — realized today by mower/, cloud_state.py, live_map/
    2  transport      mqtt, cloud RPC/OSS/file-bridge, fetch families
    1  protocol       pure decode/encode; zero HA imports; zero upward imports
    0  foundation     const.py, observability/, inventory/ loader, and the
                      handful of true zero-dependency leaves (control_honesty,
                      _devices, _png, _resources) that are imported from
                      multiple layers and therefore cannot be pinned to any
                      one of them

A module may import same-layer siblings and anything at a NUMERICALLY LOWER
layer; importing a numerically HIGHER layer is a back-edge and fails this
test. This is exactly the shape of T2-3 (protocol -> map_render, already
fixed pre-Task-4), T2-4 (protocol -> cloud_state, fixed by Task 4) and T2-5
(const -> mower.error_codes, fixed by Task 4) — this gate is what keeps them
fixed.

Scope, precisely (deliberately narrower than "every import anywhere"):

- Only MODULE-LEVEL (import-time) edges are checked: top-of-file imports,
  plus imports nested in module-level ``if``/``try``/``with``/``for``/
  ``while``/class bodies (all of which execute at import time). Imports
  inside ``if TYPE_CHECKING:`` blocks are excluded (they never execute) and
  imports inside ``def``/``async def`` bodies are excluded (function-local
  imports are a real but DIFFERENT risk — see T2-4 finding #4, "mitigated by
  being function-local" — deferred to the P3.5-3.9 service extraction rather
  than gated here; gating them now would flood this ratchet with the FN-level
  laziness/circular-import-avoidance imports that are already established
  and intentional patterns in this codebase, e.g. ``coordinator/_rendering.py``
  lazily reaching into ``map_render``).
- Only intra-package imports are resolved (``from . import x`` /
  ``from .sub import y`` / ``from ..pkg import z``); imports of third-party
  or stdlib modules, and of ``homeassistant.*``, are not layer-checked.
- Untracked filesystem artifacts (dotfile-shaped paths, e.g. the known junk
  ``coordinator/.__core.py`` — T2-14) are skipped, matching
  ``test_no_coordinator_private_getattr.py``.

Update this file's ``MODULE_LAYER`` dict whenever a P3 sub-task MOVES a
module to a different package (P3.5 transport split, P3.6 state containers,
P3.7 ingress funnel, P3.8 domain services, P3.9 thin coordinator, P3.10
renames/shim retirement) — the comment on the dict says so inline. Prefer
adding/adjusting a prefix entry over special-casing individual files.

KNOWN EXCEPTIONS: an intentional, currently-unfixed upward edge goes in
``KNOWN_EXCEPTIONS`` below with a comment explaining why it exists and which
future task fixes it. Per this task's brief, const.py and protocol/* back-
edges must NOT appear in that list — if one shows up here, fix the source,
don't add an exception.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CC = REPO_ROOT / "custom_components" / "dreame_a2_mower"

# ---------------------------------------------------------------------------
# Layer map. Keys are dotted module paths RELATIVE TO ``CC`` (the package
# root is the empty string ``""``). Lookup is by longest-prefix match against
# the dotted module path of the file being scanned, so a package entry (e.g.
# ``"protocol"``) covers every submodule (``protocol.settings``,
# ``protocol.map.types``, ...) unless a more specific prefix overrides it.
#
# UPDATE WHEN A MODULE CHANGES LAYER (P3.5-3.10). Each P3 sub-task that moves
# files between packages should add/adjust entries here in the SAME commit,
# and re-run this test before checkpointing.
# ---------------------------------------------------------------------------
MODULE_LAYER: dict[str, int] = {
    # ---- 0: foundation ---------------------------------------------------
    # const.py itself, the inventory loader, and the small set of true
    # zero-internal-dependency leaves that are imported from more than one
    # numbered layer (state AND domain AND entities AND presentation all reach
    # these) and therefore cannot be pinned to any single layer above 0
    # without creating a false back-edge. (observability/ is NOT here — it has
    # its own internal dependency on protocol/ and is pinned to layer 1; see
    # below.)
    "const": 0,
    "inventory": 0,
    "control_honesty": 0,  # CONTROL_MODES table; zero internal imports; read by entities+domain
    "_devices": 0,  # device_info/unique_id builders; zero internal imports besides const;
                     # imported by BOTH coordinator/_device_sync.py (domain) and every
                     # entity/camera platform (entities+presentation) — a true shared leaf
    "_png": 0,  # pure Pillow PNG encode/decode; imported by protocol/pcd_render.py (1),
                # wifi/map_render.py (4), and camera+map_render (6) — must sit at/below all
    "_resources": 0,  # static resource loader; zero internal imports

    # ---- 1: protocol (pure decode/encode; zero HA imports) ---------------
    "protocol": 1,
    "map_decoder": 1,  # root re-export shim -> protocol/map/ (T2-4 autopsy #8 split)
    # observability/ sits at layer 1 alongside protocol: its only internal
    # dependency is observability/registry.py -> protocol/unknown_watchdog.py
    # (a pure dataclass), so pinning it here makes that a legal SAME-layer
    # edge. Verified nothing at layer 0/1 imports observability back — its
    # only importers are __init__.py (6), coordinator/_core.py (4), and
    # coordinator/_property_apply.py (4), all strictly downward. This is why
    # the gate needs NO known-exception for that edge.
    "observability": 1,

    # ---- 2: transport (mqtt, cloud RPC/OSS/file-bridge, fetchers) --------
    "cloud_client": 2,
    "mqtt_client": 2,

    # ---- 3: state (MowerState, CloudState, StateSnapshot, state machine) -
    "mower": 3,
    "state": 3,  # P3.6: state/ package — containers, mower_state, snapshot,
                 # machine, cloud_state, apply (moved from mower/ + coordinator/)
    "cloud_state": 3,
    "live_map": 3,

    # ---- 4: domain (session/writes/media/wifi/lidar/notifications/ota/
    #        device_sync/ingress) — today realized by coordinator/ (the
    #        fused god-object per T2-1, not yet split by P3.8) plus the
    #        already-separate archive/ and wifi/ domain packages ----------
    "coordinator": 4,
    "domain": 4,  # P3.7+: domain/ package — ingress + session (signals,
                  # lifecycle_events, finalize, persistence, replay) services
                  # extracted from coordinator/ (P3.9a folded session_card.py's
                  # derivation into domain/session/replay.py; the T2-13 misnomer
                  # module is DELETED — covered by the "domain" prefix)
    "archive": 4,
    "wifi": 4,
    "wifi_archive_store": 4,  # root shim -> wifi/archive_store.py
    "wifi_match": 4,  # root shim -> wifi/match.py
    "wifi_map_render": 4,  # root shim -> wifi/map_render.py

    # ---- 5: entities (descriptor-driven platforms + services (HA API)) ---
    "entities": 5,
    "services": 5,
    "_availability": 5,
    "_settings_writes": 5,
    "sensor": 5,
    "switch": 5,
    "select": 5,
    "number": 5,
    "binary_sensor": 5,
    "button": 5,
    "time": 5,
    "device_tracker": 5,
    "lawn_mower": 5,
    "calendar": 5,
    "event": 5,
    "device_trigger": 5,
    "update": 5,
    "logbook": 5,

    # ---- 6: presentation (render/ [map_render], camera/, dashboard) ------
    "map_render": 6,
    "_render_stripes": 6,  # root shim -> map_render/stripes.py
    "camera": 6,

    # ---- entry points (setup/unload, config flow, diagnostics): these
    #      compose across every layer below presentation, so they are
    #      pinned at the top of the current ladder (6) same as presentation.
    "": 6,  # root __init__.py (module path "" = the package root itself)
    "config_flow": 6,
    "diagnostics": 6,
}

# Explicit upward edges that are known and NOT fixed by this task. Each entry
# is ``(importer_prefix, imported_prefix)`` and MUST carry a comment with the
# reason + the fixing task. const.py and protocol/* back-edges are NEVER
# allowed here (this task's brief: "const and protocol/map back-edges MUST be
# clean") — if a violation touches either, fix the import, don't add an
# exception.
#
# EMPTY BY DESIGN. The one edge that would have needed an exception —
# observability/registry.py -> protocol/unknown_watchdog.py — was eliminated
# structurally instead: observability is pinned to layer 1 (same as protocol,
# see MODULE_LAYER), which makes that a legal same-layer edge. This is a real
# fix, not deferred debt: it was verified that nothing at layer 0/1 imports
# observability back (its only importers are __init__.py=6 and two
# coordinator/=4 modules, all strictly downward), so the pin creates no new
# violation. Keep this set empty; add an entry only if you hit an upward edge
# you genuinely cannot fix in your task, with a comment + the fixing task.
KNOWN_EXCEPTIONS: set[tuple[str, str]] = set()


def _module_path(file: Path) -> str:
    """Dotted module path of ``file``, relative to ``CC``. Package ``__init__.py``
    files map to their PACKAGE's dotted path (e.g. ``coordinator/__init__.py``
    -> ``"coordinator"``, root ``__init__.py`` -> ``""``)."""
    rel = file.relative_to(CC)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][: -len(".py")]
    return ".".join(parts)


def _is_package_init(file: Path) -> bool:
    return file.name == "__init__.py"


def _package_of(mod: str, is_init: bool) -> str:
    if is_init:
        return mod
    if "." in mod:
        return mod.rsplit(".", 1)[0]
    return ""


def _resolve_relative(mod: str, is_init: bool, level: int, name: str | None) -> str:
    """Resolve a relative ``from ... import ...`` to an absolute dotted path
    within the CC package, following the same algorithm as CPython's
    importlib (``_bootstrap._resolve_name``)."""
    pkg = _package_of(mod, is_init)
    if level > 1:
        parts = pkg.split(".") if pkg else []
        trim = level - 1
        parts = parts[: len(parts) - trim] if trim <= len(parts) else []
        pkg = ".".join(parts)
    if name:
        return f"{pkg}.{name}" if pkg else name
    return pkg


def _is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    if isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
        return True
    return False


def _iter_module_level_imports(body: list[ast.stmt]):
    """Yield Import/ImportFrom nodes that execute at module-import time:
    top-level statements, plus nested if/try/with/for/while/class bodies
    (all execute immediately on import). Skips ``if TYPE_CHECKING:`` bodies
    and does NOT descend into function/async-function/lambda bodies (those
    only execute when called, a different — and deliberately unscoped —
    risk; see the module docstring)."""
    for stmt in body:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            yield stmt
        elif isinstance(stmt, ast.If):
            if _is_type_checking(stmt.test):
                continue
            yield from _iter_module_level_imports(stmt.body)
            yield from _iter_module_level_imports(stmt.orelse)
        elif isinstance(stmt, ast.Try):
            yield from _iter_module_level_imports(stmt.body)
            for handler in stmt.handlers:
                yield from _iter_module_level_imports(handler.body)
            yield from _iter_module_level_imports(stmt.orelse)
            yield from _iter_module_level_imports(stmt.finalbody)
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            yield from _iter_module_level_imports(stmt.body)
        elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
            yield from _iter_module_level_imports(stmt.body)
            yield from _iter_module_level_imports(stmt.orelse)
        elif isinstance(stmt, ast.ClassDef):
            # A class body executes at class-definition time (import time).
            yield from _iter_module_level_imports(stmt.body)
        # FunctionDef/AsyncFunctionDef bodies are function-local scope —
        # deliberately not descended into (see docstring).


def _layer_of(mod: str) -> int | None:
    """Longest-prefix lookup into MODULE_LAYER. Returns None for anything not
    an internal CC module (stdlib, third-party, homeassistant.*)."""
    if mod in MODULE_LAYER:
        return MODULE_LAYER[mod]
    parts = mod.split(".") if mod else [""]
    for i in range(len(parts) - 1, 0, -1):
        prefix = ".".join(parts[:i])
        if prefix in MODULE_LAYER:
            return MODULE_LAYER[prefix]
    return None


def _collect_edges() -> list[tuple[str, str, str]]:
    """Returns a list of (importer_module, imported_module, file) for every
    resolved intra-package module-level import edge."""
    edges: list[tuple[str, str, str]] = []
    for file in sorted(CC.rglob("*.py")):
        rel = file.relative_to(CC)
        if any(part.startswith(".") for part in rel.parts):
            continue  # dotfile-shaped filesystem junk (T2-14), not tracked/importable
        if "__pycache__" in rel.parts:
            continue
        mod = _module_path(file)
        is_init = _is_package_init(file)
        try:
            tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        except SyntaxError:
            continue
        for node in _iter_module_level_imports(tree.body):
            if isinstance(node, ast.ImportFrom):
                if node.level == 0:
                    # Absolute import. Only in-scope if it targets our own
                    # package explicitly (tests do this; production code
                    # doesn't — see module docstring's "Scope" section).
                    target = node.module or ""
                    prefix = "custom_components.dreame_a2_mower"
                    if target == prefix:
                        imported = ""
                    elif target.startswith(prefix + "."):
                        imported = target[len(prefix) + 1 :]
                    else:
                        continue  # third-party / stdlib / homeassistant.*
                else:
                    imported = _resolve_relative(mod, is_init, node.level, node.module)
            else:  # ast.Import — "import X" has no relative form
                names = [alias.name for alias in node.names]
                prefix = "custom_components.dreame_a2_mower"
                for n in names:
                    if n == prefix or n.startswith(prefix + "."):
                        imported = n[len(prefix) :].lstrip(".")
                        edges.append((mod, imported, str(rel)))
                continue
            edges.append((mod, imported, str(rel)))
    return edges


def test_no_upward_layer_imports():
    """No module-level import may reach a numerically HIGHER layer than its
    own (see module docstring for the six-layer + foundation model)."""
    edges = _collect_edges()
    violations: list[str] = []
    for importer, imported, file in edges:
        importer_layer = _layer_of(importer)
        imported_layer = _layer_of(imported)
        if importer_layer is None or imported_layer is None:
            continue  # not a module we've mapped (shouldn't happen — see the
                       # coverage assertion below) or not an internal module
        if imported_layer <= importer_layer:
            continue  # downward or same-layer: fine
        key = (importer, imported)
        if key in KNOWN_EXCEPTIONS or any(
            importer.startswith(exc_importer) and imported.startswith(exc_imported)
            for exc_importer, exc_imported in KNOWN_EXCEPTIONS
        ):
            continue
        violations.append(
            f"  {file}: `{importer}` (layer {importer_layer}) imports "
            f"`{imported}` (layer {imported_layer}) — UPWARD"
        )
    assert not violations, (
        f"{len(violations)} module-level upward import(s) found (back-edges "
        f"per the target layer model — see module docstring):\n"
        + "\n".join(sorted(violations))
        + "\n\nFix the import direction, or — only if you cannot fix it in "
        "this task — add a KNOWN_EXCEPTIONS entry with a comment + the task "
        "that will fix it. const.py and protocol/* back-edges may NEVER go "
        "in KNOWN_EXCEPTIONS."
    )


def test_every_scanned_module_is_mapped():
    """Coverage guard: every internal import edge must resolve through
    MODULE_LAYER on BOTH ends. If this fails, a new top-level file/package
    was added and MODULE_LAYER needs a new entry (see the dict's header
    comment) — the layer gate above only protects modules it knows about."""
    edges = _collect_edges()
    unmapped: set[str] = set()
    for importer, imported, _file in edges:
        if _layer_of(importer) is None:
            unmapped.add(importer)
        if _layer_of(imported) is None:
            unmapped.add(imported)
    assert not unmapped, (
        f"MODULE_LAYER has no entry (or prefix) covering: {sorted(unmapped)}. "
        f"Add an entry to tests/audit/test_layer_imports.py:MODULE_LAYER."
    )
