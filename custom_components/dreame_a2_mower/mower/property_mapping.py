"""Back-compat re-export shim (P3.6): the ``(siid, piid) -> field`` mapping
table moved to ``protocol/property_mapping.py`` — it is pure wire knowledge
(architecture §2), so it belongs in the protocol layer.

New code should import from ``..protocol.property_mapping`` directly.
Retired with the P3.10 import-path rewrite.
"""
from __future__ import annotations

from ..protocol.property_mapping import (  # noqa: F401 — re-export
    PROPERTY_MAPPING as PROPERTY_MAPPING,
    PropertyMappingEntry as PropertyMappingEntry,
    resolve_field as resolve_field,
)

__all__ = ["PROPERTY_MAPPING", "PropertyMappingEntry", "resolve_field"]
