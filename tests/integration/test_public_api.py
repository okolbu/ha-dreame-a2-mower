"""Public-import contract: the package ``__init__`` re-export shields.

CLAUDE.md (§ "Public-import preservation", § "Cloud client structure",
§ "Rendering structure") documents a set of names that callers — tests,
entity platforms, tools — import through each package's ``__init__``
re-exports rather than from the private submodules they actually live
in. That re-export surface is what keeps the deep-import sites stable
when the refactor moves files around underneath (105 coordinator / 22
map_render / 24 cloud_client deep-import sites per the review).

This test converts that prose contract into an executable guard: it
asserts every documented re-export still resolves, and pins the explicit
``__all__`` surfaces so a removal fails loudly here instead of silently
breaking a downstream importer.

If a refactor legitimately changes the public surface, update BOTH this
test and the CLAUDE.md contract section in the same change.
"""
from __future__ import annotations

import importlib

import pytest

# Documented re-export surface, keyed by the package callers import from.
# Sourced from CLAUDE.md; verified against each package's __init__ at
# baseline (commit 34806ac).
_COORDINATOR_EXPORTS = (
    "DreameA2MowerCoordinator",
    "apply_property_to_state",
    "_BLOB_SLOTS",
    "_SUPPRESSED_SLOTS",
    # NOTE: the re-export is S2P2_EVENT_TYPES. CLAUDE.md's public-import
    # paragraph and the refactor plan both say "S2P2_NOTIFICATION_MAP" —
    # that name does NOT exist; the real symbol is S2P2_EVENT_TYPES (see
    # coordinator/__init__.py __all__). This test pins reality.
    "S2P2_EVENT_TYPES",
    "_project_north_east",
)

_CLOUD_CLIENT_EXPORTS = ("DreameA2CloudClient",)

# map_render publishes an explicit, curated __all__ (CLAUDE.md: "Public
# surface = __init__.py re-exports ONLY the names real callers import").
_MAP_RENDER_EXPORTS = (
    "render_base",
    "render_base_map",
    "render_work_log",
    "extract_projection",
    # T2-17 map-unification: the render-side Projection builder + zone rotation
    # helper (the decoder carries raw geometry; render owns the transform).
    "build_projection",
    "MapProjection",
    "zone_render_points",
    "BackgroundMode",
    "background_mode_for",
    "_DEFAULT_PALETTE",
    "_OBSTACLE_FILL",
    "_OBSTACLE_OUTLINE",
    "_cloud_to_px",
    "_renderer_to_px",
)

_PKG = "custom_components.dreame_a2_mower"

_CASES = [
    (f"{_PKG}.coordinator", _COORDINATOR_EXPORTS),
    (f"{_PKG}.cloud_client", _CLOUD_CLIENT_EXPORTS),
    (f"{_PKG}.map_render", _MAP_RENDER_EXPORTS),
]


@pytest.mark.parametrize(
    "module_name,export",
    [(mod, name) for mod, names in _CASES for name in names],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_documented_reexport_resolves(module_name: str, export: str) -> None:
    """Each documented name must resolve through the package __init__."""
    module = importlib.import_module(module_name)
    assert hasattr(module, export), (
        f"{module_name} no longer re-exports {export!r}. If this move is "
        f"intentional, update CLAUDE.md and this test together; otherwise "
        f"restore the re-export in {module_name}/__init__.py."
    )


def test_coordinator_all_covers_documented_surface() -> None:
    """coordinator.__all__ must contain every documented re-export."""
    mod = importlib.import_module(f"{_PKG}.coordinator")
    missing = [n for n in _COORDINATOR_EXPORTS if n not in mod.__all__]
    assert not missing, f"coordinator.__all__ missing: {missing}"


def test_map_render_all_is_exactly_the_documented_surface() -> None:
    """map_render.__all__ is curated — pin it exactly (no drift, no
    'just in case' re-exports per CLAUDE.md)."""
    mod = importlib.import_module(f"{_PKG}.map_render")
    assert set(mod.__all__) == set(_MAP_RENDER_EXPORTS), (
        "map_render.__all__ drifted from the documented public surface.\n"
        f"  in __all__ but undocumented: {set(mod.__all__) - set(_MAP_RENDER_EXPORTS)}\n"
        f"  documented but missing:      {set(_MAP_RENDER_EXPORTS) - set(mod.__all__)}"
    )
