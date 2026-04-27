"""Regression test: g2408 capability snapshot.

Locks in the values DreameMowerDeviceCapability resolves to on g2408.
Source of truth is docs/superpowers/plans/2026-04-27-p1-capability-snapshot.md
(derived offline from 3 weeks of MQTT probe logs + decompression of the
DREAME_MODEL_CAPABILITIES blob).

If this test fails after a refactor, the refactor changed observed
capability state — investigate before silencing the test.

Import strategy: types.py only uses stdlib (math, json, enum, dataclasses,
etc.) so it can be loaded directly via importlib without triggering the
HA-dependent custom_components/__init__.py package chain.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# Load types.py directly, bypassing the HA-dependent package __init__.py.
# Register the module under its real dotted name so @dataclass decorators
# (which look up cls.__module__ in sys.modules) work correctly.
_TYPES_PATH = Path("custom_components/dreame_a2_mower/dreame/types.py")
_MODULE_NAME = "custom_components.dreame_a2_mower.dreame.types"
_spec = importlib.util.spec_from_file_location(_MODULE_NAME, _TYPES_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_MODULE_NAME] = _mod
_spec.loader.exec_module(_mod)

DreameMowerDeviceCapability = _mod.DreameMowerDeviceCapability
RobotType = _mod.RobotType


# From docs/superpowers/plans/2026-04-27-p1-capability-snapshot.md.
# DO NOT edit by hand — re-derive from the snapshot doc if needed.
G2408_CAPABILITY_SNAPSHOT = {
    'ai_detection': False,
    'auto_charging': False,
    'auto_rename_segment': False,
    'auto_switch_settings': False,
    'backup_map': False,
    'camera_streaming': False,
    'cleangenius': False,
    'cleangenius_auto': False,
    'cleaning_route': False,
    'customized_cleaning': False,
    'disable_sensor_cleaning': True,
    'dnd': False,
    'dnd_task': False,
    'extended_furnitures': False,
    'fill_light': False,
    'floor_direction_cleaning': False,
    'floor_material': False,
    'fluid_detection': False,
    'gen5': False,
    'large_particles_boost': False,
    'lensbrush': False,
    'lidar_navigation': True,
    'list': None,
    'map_object_offset': False,
    'max_suction_power': False,
    'multi_floor_map': False,
    'new_furnitures': False,
    'new_state': False,
    'obstacle_image_crop': False,
    'obstacles': False,
    'off_peak_charging': False,
    'pet_detective': False,
    'pet_furniture': False,
    'pet_furnitures': False,
    'robot_type': RobotType.LIDAR,
    'saved_furnitures': False,
    'segment_slow_clean_route': False,
    'segment_visibility': False,
    'shortcuts': False,
    'task_type': False,
    'voice_assistant': False,
    'wifi_map': False,
}


def _public_flag_dict(cap):
    """Reflect the public flags off a DreameMowerDeviceCapability instance."""
    cls = type(cap)
    return {
        p: getattr(cap, p)
        for p in dir(cap)
        if not p.startswith("_")
        and not callable(getattr(cap, p))
        and not isinstance(getattr(cls, p, None), property)
    }


def test_g2408_capability_constructor_matches_snapshot():
    """A bare DreameMowerDeviceCapability() (post-flattening) equals the snapshot.

    After P1.4.3 lands, refresh() is a no-op and __init__ sets the
    g2408-specific constants directly. So a no-arg construction
    produces the snapshot.
    """
    cap = DreameMowerDeviceCapability()
    actual = _public_flag_dict(cap)
    for key, expected in G2408_CAPABILITY_SNAPSHOT.items():
        assert actual.get(key) == expected, (
            f"{key} drifted: snapshot={expected!r} actual={actual.get(key)!r}"
        )
    # Also flag any new public flag we added but forgot to record:
    extra = set(actual) - set(G2408_CAPABILITY_SNAPSHOT)
    assert not extra, (
        f"capability has new public attribute(s) {extra} not in the snapshot — "
        f"update docs/superpowers/plans/2026-04-27-p1-capability-snapshot.md"
    )
