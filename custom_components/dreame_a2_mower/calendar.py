"""Calendar entity exposing archived sessions as events.

Each ArchivedSession becomes a CalendarEvent. Read-only — there is no
add/edit/delete; HA's calendar UI surfaces them in agenda/day/week/month
views via the built-in calendar card.
"""
from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._devices import _MowerScopedEntity
from ._experimental import filter_experimental
from .const import DOMAIN
from .coordinator import DreameA2MowerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        filter_experimental(entry, [DreameA2SessionCalendar(coordinator)])
    )


class DreameA2SessionCalendar(
    _MowerScopedEntity, CoordinatorEntity[DreameA2MowerCoordinator], CalendarEntity
):
    """Read-only calendar of archived mow sessions."""

    _attr_has_entity_name = True
    _attr_name = "Sessions"
    _attr_translation_key = "session_calendar"
    _attr_icon = "mdi:calendar-clock"
    _MOWER_KEY = "session_calendar"

    @property
    def event(self) -> CalendarEvent | None:
        """Most-recent session — HA shows this in the entity state line."""
        archive = getattr(self.coordinator, "session_archive", None)
        if archive is None:
            return None
        entries = archive.list_sessions()
        if not entries:
            return None
        # list_sessions returns most-recent-first by end_ts; take the head.
        return _event_from_entry(entries[0])

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return events within [start_date, end_date]."""
        archive = getattr(self.coordinator, "session_archive", None)
        if archive is None:
            return []
        start_ts = start_date.timestamp()
        end_ts = end_date.timestamp()
        events: list[CalendarEvent] = []
        for entry in archive.list_sessions():
            if entry.start_ts < start_ts or entry.start_ts > end_ts:
                continue
            events.append(_event_from_entry(entry))
        return events


def _event_from_entry(entry) -> CalendarEvent:
    """Render an ArchivedSession as a CalendarEvent.

    The `summary` field is formatted to MATCH the session-replay select's
    option label EXACTLY:

        ``[Mowing] [Map N] YYYY-MM-DD HH:MM — A.A m² / Dmin``

    This lets a Lovelace tap_action pipe `{{ summary }}` straight into
    `select.select_option` (entity_id: select.dreame_a2_mower_session_replay,
    renamed from ..._work_log in P4.5 — unique_id key "work_log" is
    unchanged) so tapping a calendar event jumps the Replay picker to that
    session. Format must stay in lock-step with
    `select.DreameA2WorkLogSelect._build_options_from_sessions`.
    """
    from .domain.session.replay import format_session_label

    start = datetime.fromtimestamp(entry.start_ts, tz=timezone.utc)
    end = datetime.fromtimestamp(entry.end_ts, tz=timezone.utc)
    # Single source of truth — same format the picker dropdown uses, so
    # tapping a calendar event jumps the picker to a label that matches
    # one of its options byte-for-byte.
    summary = format_session_label(entry)
    description_parts = [
        f"Duration: {entry.duration_min} min",
        f"Area mowed: {entry.area_mowed_m2:.1f} m²",
    ]
    if entry.session_distance_m:
        description_parts.append(f"Distance: {entry.session_distance_m:.0f} m")
    description_parts.append(f"Map area: {entry.map_area_m2} m²")
    return CalendarEvent(
        start=start,
        end=end,
        summary=summary,
        description="\n".join(description_parts),
        uid=f"dreame_a2_session_{entry.md5}_{entry.start_ts}",
    )
