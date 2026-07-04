"""MowerState — composition of the eight domain containers (P3.6).

MowerState is a dataclass whose real fields are the eight frozen
sub-containers (see ``containers.py``). For the duration of the P3
migration it ALSO exposes a delegating read-property for every one of
the 164 legacy flat fields, plus flat-kwarg construction, so the ~59
prod ``.data.<field>`` sites, all entity descriptors, ``MowerState(...)``
test constructions and ``dataclasses.replace(state, field=…)`` writers
keep working UNCHANGED. Writers should migrate to container-scoped
access in P4+; reads via the delegating property are transitional.

Construction/mutation routes each flat field to its owning container:
  - ``MowerState(battery_level=5)``  — flat kwargs -> container
  - ``dataclasses.replace(state, battery_level=5)`` — works (see __init__)
  - ``state.with_updates(battery_level=5)`` — preferred flat writer
  - ``state.to_flat_dict()`` — the legacy flat asdict shape
"""
from __future__ import annotations

import dataclasses
from collections import defaultdict
from dataclasses import dataclass, fields as _dc_fields
from typing import Any

from .containers import (
    ActionMode as ActionMode,
    ChargingStatus as ChargingStatus,
    State as State,
    Identity,
    OtaState,
    Telemetry,
    Connectivity,
    Consumables,
    Settings,
    SessionRefs,
    Messages,
)

# Container attr -> container class. Order is the field-emission order used
# by to_flat_dict (matches the legacy flat MowerState field order).
_CONTAINER_CLASSES: dict[str, type] = {
    "identity": Identity,
    "ota": OtaState,
    "telemetry": Telemetry,
    "connectivity": Connectivity,
    "consumables": Consumables,
    "settings": Settings,
    "session_refs": SessionRefs,
    "messages": Messages,
}

# flat field name -> owning container attr, and the flat field order.
_FIELD_TO_CONTAINER: dict[str, str] = {}
_FLAT_FIELD_ORDER: list[str] = []
for _cattr, _cls in _CONTAINER_CLASSES.items():
    for _f in _dc_fields(_cls):
        _FIELD_TO_CONTAINER[_f.name] = _cattr
        _FLAT_FIELD_ORDER.append(_f.name)
_FLAT_FIELD_ORDER = tuple(_FLAT_FIELD_ORDER)  # type: ignore[assignment]

# Public: the 164 legacy flat field names in declaration order. Consumers that
# used to enumerate ``dataclasses.fields(MowerState)`` (which now yields the 8
# CONTAINER names) should read this instead — e.g. the state-machine audit's
# orphan-field derivation.
FLAT_FIELDS: tuple[str, ...] = _FLAT_FIELD_ORDER


@dataclass(init=False, eq=True, repr=False)
class MowerState:
    """Typed view of the mower state, composed of 8 domain containers."""

    identity: Identity
    ota: OtaState
    telemetry: Telemetry
    connectivity: Connectivity
    consumables: Consumables
    settings: Settings
    session_refs: SessionRefs
    messages: Messages

    def __init__(self, *, identity: Identity | None = None, ota: OtaState | None = None, telemetry: Telemetry | None = None, connectivity: Connectivity | None = None, consumables: Consumables | None = None, settings: Settings | None = None, session_refs: SessionRefs | None = None, messages: Messages | None = None, **flat: Any) -> None:
        """Build from container instances and/or flat field overrides.

        Flat overrides (e.g. ``battery_level=5``) are grouped by owning
        container and applied on top of the supplied/-default container.
        ``dataclasses.replace(state, field=…)`` funnels through here."""
        conts: dict[str, Any] = {
            "identity": identity if identity is not None else Identity(),
            "ota": ota if ota is not None else OtaState(),
            "telemetry": telemetry if telemetry is not None else Telemetry(),
            "connectivity": connectivity if connectivity is not None else Connectivity(),
            "consumables": consumables if consumables is not None else Consumables(),
            "settings": settings if settings is not None else Settings(),
            "session_refs": session_refs if session_refs is not None else SessionRefs(),
            "messages": messages if messages is not None else Messages(),
        }
        if flat:
            grouped: dict[str, dict[str, Any]] = defaultdict(dict)
            for _k, _v in flat.items():
                _cattr = _FIELD_TO_CONTAINER.get(_k)
                if _cattr is None:
                    raise TypeError(
                        f"MowerState got an unexpected field {_k!r}"
                    )
                grouped[_cattr][_k] = _v
            for _cattr, _kw in grouped.items():
                conts[_cattr] = dataclasses.replace(conts[_cattr], **_kw)
        self.identity = conts["identity"]
        self.ota = conts["ota"]
        self.telemetry = conts["telemetry"]
        self.connectivity = conts["connectivity"]
        self.consumables = conts["consumables"]
        self.settings = conts["settings"]
        self.session_refs = conts["session_refs"]
        self.messages = conts["messages"]

    def with_updates(self, **flat: Any) -> "MowerState":
        """Return a new MowerState with the given flat fields replaced,
        each routed to its owning container. Preferred flat writer;
        equivalent to ``dataclasses.replace(self, **flat)``."""
        return dataclasses.replace(self, **flat)

    def to_flat_dict(self) -> dict[str, Any]:
        """The legacy flat ``asdict(MowerState)`` shape: {field: value} for
        all 164 fields in their original declaration order. Used by
        diagnostics + the corpus-replay digest to stay byte-identical."""
        return {_n: getattr(self, _n) for _n in _FLAT_FIELD_ORDER}

    def __repr__(self) -> str:  # flat repr for readability/parity
        inner = ", ".join(f"{_n}={getattr(self, _n)!r}" for _n in _FLAT_FIELD_ORDER)
        return f"MowerState({inner})"


# --- transitional delegating properties (P3.6) — access via container in P4+ ---
# The former MowerState was a mutable (non-frozen) dataclass, so both reads
# (``state.battery_level``) and in-place writes (``state.battery_level = 5``)
# were used across prod + tests. Each delegate therefore has a getter AND a
# setter; the setter swaps the (frozen) owning container on ``self``.
def _make_delegate(_name: str, _cattr: str):
    def _getter(self: MowerState):
        return getattr(getattr(self, _cattr), _name)

    def _setter(self: MowerState, value: Any):
        setattr(
            self, _cattr, dataclasses.replace(getattr(self, _cattr), **{_name: value})
        )

    _getter.__name__ = _name
    return property(_getter, _setter)


for _fname, _fcattr in _FIELD_TO_CONTAINER.items():
    setattr(MowerState, _fname, _make_delegate(_fname, _fcattr))
del _fname, _fcattr
