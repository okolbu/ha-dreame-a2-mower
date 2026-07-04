"""WiFi archive mixin — thin delegators (refactor-v2 P3.9e).

The WiFi-heatmap archive-refresh + fingerprint-matcher LOGIC moved VERBATIM to
the ``domain/`` layer (``domain/wifi/service.py``, consolidating the 9c-deferred
refresh orchestration alongside the body-cache/render-entry helpers that landed
there in 9c). Each domain function takes the coordinator (``coord``) as its
first argument; this mixin keeps thin delegating methods so the public/test
surface (``coord.refresh_wifi_archive`` / ``coord._periodic_archive_refresh`` /
``coord.active_map_wifi_overlay`` / ``coord._resolve_active_map_wifi_entry`` /
``coord._schedule_active_map_wifi_load`` / ``coord._download_and_archive_wifi``
/ ``coord._read_session_wifi_samples`` / ``coord._tag_wifi_archive_map_ids``,
read by ``camera/map.py`` and pinned by ``test_wifi_archive_refresh`` /
``test_active_map_wifi_overlay`` / ``test_wifi_matcher_plumbing`` /
``test_card_contract``) is unchanged.

See docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md and
the refactor-v2 P3 plan.
"""
from __future__ import annotations

from ..domain.wifi import service as _wifi


class _WifiArchiveMixin:
    """Thin delegators to ``domain.wifi.service`` (P3.9e) — see module docstring."""

    # How many recent sessions to score against each heatmap. 30 is a
    # generous ceiling — beyond that the dock has typically moved or
    # the mower was reset and old samples no longer reflect the
    # current RF environment. Tuneable if user feedback indicates
    # otherwise. Read by ``domain.wifi.service.tag_wifi_archive_map_ids`` via
    # ``coord._WIFI_MATCH_RECENT_SESSIONS`` (a test instance-override applies).
    _WIFI_MATCH_RECENT_SESSIONS = 30

    async def _periodic_archive_refresh(self) -> None:
        """Delegates to ``domain.wifi.service.periodic_archive_refresh`` (P3.9e)."""
        await _wifi.periodic_archive_refresh(self)

    async def refresh_wifi_archive(self) -> dict:
        """Delegates to ``domain.wifi.service.refresh_wifi_archive`` (P3.9e)."""
        return await _wifi.refresh_wifi_archive(self)

    def _resolve_active_map_wifi_entry(self):
        """Delegates to ``domain.wifi.service.resolve_active_map_wifi_entry`` (P3.9e)."""
        return _wifi.resolve_active_map_wifi_entry(self)

    @property
    def active_map_wifi_overlay(self) -> "dict | None":
        """Delegates to ``domain.wifi.service.active_map_wifi_overlay`` (P3.9e)."""
        return _wifi.active_map_wifi_overlay(self)

    def _schedule_active_map_wifi_load(self) -> None:
        """Delegates to ``domain.wifi.service.schedule_active_map_wifi_load`` (P3.9e)."""
        _wifi.schedule_active_map_wifi_load(self)

    def _download_and_archive_wifi(
        self, object_name: str, first_seen_unix: int
    ) -> dict | None:
        """Delegates to ``domain.wifi.service.download_and_archive_wifi`` (P3.9e)."""
        return _wifi.download_and_archive_wifi(self, object_name, first_seen_unix)

    def _read_session_wifi_samples(
        self, filename: str
    ) -> list[tuple[float, float, int, int]]:
        """Delegates to ``domain.wifi.service.read_session_wifi_samples`` (P3.9e)."""
        return _wifi.read_session_wifi_samples(self, filename)

    def _tag_wifi_archive_map_ids(self) -> int:
        """Delegates to ``domain.wifi.service.tag_wifi_archive_map_ids`` (P3.9e)."""
        return _wifi.tag_wifi_archive_map_ids(self)
