"""Back-compat re-export shim (P3.6): the pure property/CFG apply funnel
moved to ``state/apply.py`` (the state layer — it is a pure
``(siid,piid,value)/CFG -> MowerState`` transform, not a coordinator
concern; T2-2 also purged its rotted import header on the way).

New code should import from ``..state.apply`` directly. Retired with the
P3.10 import-path rewrite. All names below (public + the underscore
helpers/constants consumed by the coordinator mixins + tests) are
re-exported verbatim.
"""
from __future__ import annotations

from ..state.apply import (  # noqa: F401 — re-export
    S2P2_EVENT_TYPES as S2P2_EVENT_TYPES,
    S2P2_UNKNOWN_EVENT_TYPE as S2P2_UNKNOWN_EVENT_TYPE,
    _BLOB_SLOTS as _BLOB_SLOTS,
    _INVENTORY as _INVENTORY,
    _SESSION_SUMMARY_CHECK as _SESSION_SUMMARY_CHECK,
    _SETTINGS_TRIPWIRE_SLOTS as _SETTINGS_TRIPWIRE_SLOTS,
    _SUPPRESSED_SLOTS as _SUPPRESSED_SLOTS,
    _coerce_blob as _coerce_blob,
    _project_north_east as _project_north_east,
    apply_property_to_state as apply_property_to_state,
    cfg_to_state_updates as cfg_to_state_updates,
)

__all__ = [
    "apply_property_to_state",
    "cfg_to_state_updates",
    "_BLOB_SLOTS",
    "_SUPPRESSED_SLOTS",
    "_SETTINGS_TRIPWIRE_SLOTS",
    "_INVENTORY",
    "_coerce_blob",
    "_project_north_east",
    "_SESSION_SUMMARY_CHECK",
    "S2P2_EVENT_TYPES",
    "S2P2_UNKNOWN_EVENT_TYPE",
]
