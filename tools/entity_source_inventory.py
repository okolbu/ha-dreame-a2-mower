"""Canonical entity-source file inventory — the move-lockstep target.

Single source of truth for WHICH source files under
``custom_components/dreame_a2_mower/`` define Home-Assistant entities for
each platform. Extracted (Phase 0.5 of the 2026-06-13 cleanup/refactor)
from the formerly-inline ``PLATFORMS`` + ``PLATFORM_SIBLINGS`` constants in
``tools/state_machine/state_machine_audit_discover.py`` so the file list
lives in exactly one editable place.

WHY THIS EXISTS / WHEN TO EDIT
------------------------------
The state-machine audit walker (``state_machine_audit_discover.py``) scans
these files *by path* to discover every entity description / class. When a
refactor RENAMES, MOVES, or SPLITS an entity source file — e.g. Phase 3c
packages the entity layer into ``entities/sensor/``, ``camera/``,
``wifi/`` — the walker would silently stop discovering the moved entities
and the audit would under-report or go red. This module is the ONE place
to update on such a move: change the paths here and every consumer follows.

It is referenced in the refactor plan's CI-lockstep table
(``refactor-2026-06-13/plan.md`` — "state_machine_audit" row).

WHAT THIS DOES *NOT* COVER
--------------------------
File *location* is centralized here, but a class *rename* is a different
coupling: the audit's ``_STANDALONE_CLASS_REGISTRY`` (in the discover
module) is keyed by class name and is deliberately file-agnostic — the AST
walker matches class names across whatever files this inventory lists, so
moving a class between listed files needs no change there. If you RENAME a
standalone entity class, update ``_STANDALONE_CLASS_REGISTRY`` too.

Paths are relative to the package dir and include the primary
``"{platform}.py"`` loader file plus any helper/sibling modules that carry
entity classes or description tables but are NOT named after the HA
platform domain (so HA won't try to load them directly).
"""
from __future__ import annotations

# HA platform domains the state-machine audit discovers entities for.
PLATFORMS: tuple[str, ...] = (
    "binary_sensor",
    "sensor",
    "switch",
    "select",
    "number",
    "time",
)

# Per-platform source files (relative to the package dir). The primary
# loader "{platform}.py" comes first, followed by any sibling/helper
# modules (B3a flat-sibling splits). Keep this the single editable list
# when entity source files move.
ENTITY_SOURCE_FILES: dict[str, tuple[str, ...]] = {
    "binary_sensor": ("binary_sensor.py",),
    "sensor": (
        "sensor.py",
        "sensor_device.py",
        "sensor_map.py",
        "sensor_session.py",
        "_sensor_base.py",
    ),
    "switch": (
        "switch.py",
        "switch_global.py",
        "switch_map.py",
        "_switch_base.py",
    ),
    "select": (
        "select.py",
        "select_global.py",
        "select_map_settings.py",
        "_select_base.py",
    ),
    "number": ("number.py",),
    "time": ("time.py",),
}


def source_files_for(platform: str) -> tuple[str, ...]:
    """Return the source-file list for a platform (empty tuple if unknown)."""
    return ENTITY_SOURCE_FILES.get(platform, ())
