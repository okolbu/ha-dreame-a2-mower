"""Conftest for event tests.

Event tests import event.py which requires homeassistant.components.event.EventEntity.
We inject minimal stubs so the event module can be imported without a full HA environment.
"""
from __future__ import annotations

import sys
import types


def _stub_logbook() -> None:
    """Insert stub for homeassistant.components.logbook (used by logbook.py)."""
    if "homeassistant.components.logbook" in sys.modules:
        return

    # Ensure parent stubs exist.
    if "homeassistant" not in sys.modules:
        ha = types.ModuleType("homeassistant")
        sys.modules["homeassistant"] = ha

    if "homeassistant.components" not in sys.modules:
        ha_components = types.ModuleType("homeassistant.components")
        sys.modules["homeassistant.components"] = ha_components

    ha_logbook = types.ModuleType("homeassistant.components.logbook")
    ha_logbook.LOGBOOK_ENTRY_MESSAGE = "message"
    ha_logbook.LOGBOOK_ENTRY_NAME = "name"
    sys.modules["homeassistant.components.logbook"] = ha_logbook

    # homeassistant.core symbols needed by logbook.py
    if "homeassistant.core" not in sys.modules:
        ha_core = types.ModuleType("homeassistant.core")
        sys.modules["homeassistant.core"] = ha_core
    else:
        ha_core = sys.modules["homeassistant.core"]
    if not hasattr(ha_core, "callback"):
        ha_core.callback = lambda fn: fn  # type: ignore[attr-defined]
    if not hasattr(ha_core, "Event"):
        ha_core.Event = type("Event", (), {})  # type: ignore[attr-defined]
    if not hasattr(ha_core, "HomeAssistant"):
        ha_core.HomeAssistant = type("HomeAssistant", (), {})  # type: ignore[attr-defined]


def _stub_event_entity() -> None:
    """Insert stub for homeassistant.components.event.EventEntity."""
    if "homeassistant.components.event" in sys.modules:
        return

    ha_ce = types.ModuleType("homeassistant.components.event")

    class EventEntity:  # noqa: D101
        """Minimal stub for EventEntity base class."""

        def __init__(self):
            self.entity_id = "event.test"

        def _trigger_event(self, event_type: str, event_data: dict) -> None:
            """Stub for firing an event."""
            pass

        def async_write_ha_state(self) -> None:
            """Stub for writing state."""
            pass

    ha_ce.EventEntity = EventEntity

    sys.modules["homeassistant.components.event"] = ha_ce


_stub_logbook()
_stub_event_entity()
