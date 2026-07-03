"""Version sensor: integration_version must read manifest.json from the
package root.

Bug (R-6 / T5-1, docs/.../track-5-entity-surface.md): `_read_manifest_version()`
resolved `Path(__file__).parent / "manifest.json"` from
`entities/sensor/device.py`, which lands in `entities/sensor/` — two levels
short of the package root (`custom_components/dreame_a2_mower/`) where
manifest.json actually lives. The lookup always failed and the sensor read
"unknown" since the Phase-3c entities/ package move. Fix: resolve from
`Path(__file__).parents[2]`.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

_MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "custom_components" / "dreame_a2_mower" / "manifest.json"
)


def _real_version() -> str:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))["version"]


def _coord() -> MagicMock:
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    return coord


def test_read_manifest_version_resolves_package_root():
    from custom_components.dreame_a2_mower.entities.sensor.device import (
        _read_manifest_version,
    )
    assert _read_manifest_version() == _real_version()


def test_read_manifest_version_is_not_unknown():
    from custom_components.dreame_a2_mower.entities.sensor.device import (
        _read_manifest_version,
    )
    assert _read_manifest_version() != "unknown"


def test_integration_version_sensor_native_value_matches_manifest():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2IntegrationVersionSensor,
    )
    s = DreameA2IntegrationVersionSensor(_coord())
    assert s.native_value == _real_version()
