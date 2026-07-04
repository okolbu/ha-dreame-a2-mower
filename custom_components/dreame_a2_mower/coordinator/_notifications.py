"""notifications mixin — thin delegators (refactor-v2 P3.9d).

The cloud-notification resolver LOGIC moved VERBATIM to the ``domain/`` layer
(``domain/notifications.py``). Each domain function takes the coordinator
(``coord``) as its first argument; this mixin keeps thin delegating methods so
the public/test surface (``coord._resolve_s2p2_notification``,
``coord._merge_device_messages``, the unbound ``_NotificationsMixin._X``
methods, the ``coordinator._notifications`` module handle + its
``_FETCH_DELAY_S`` monkeypatch target, and the re-exported ``_source_key`` /
``_english_text`` helpers) is unchanged.

See docs/research/app-api-surface-2026-05-25.md § device-messages/v2 and the
refactor-v2 P3 plan.
"""
from __future__ import annotations

from ..domain import notifications as _notif

# ``_FETCH_DELAY_S`` stays defined HERE (not just in the domain module) so the
# established test monkeypatch — ``monkeypatch.setattr(_notifications,
# "_FETCH_DELAY_S", 0)`` — still applies: the resolver delegator reads THIS
# binding and passes it into the domain function (the "caller passes its own
# module-local reference" convention shared with _managed_timers).
_FETCH_DELAY_S: float = 10.0

# Back-compat re-exports — tests import these pure helpers from their old
# ``coordinator._notifications`` home (test_notification_synthesizer).
_source_key = _notif._source_key
_english_text = _notif._english_text
# Constants preserved for readers of the old module surface.
DEVICE_MESSAGES_SAVE_DELAY_S = _notif.DEVICE_MESSAGES_SAVE_DELAY_S
_FETCH_PAGE_SIZE = _notif._FETCH_PAGE_SIZE
_SEEN_IDS_CAP = _notif._SEEN_IDS_CAP


class _NotificationsMixin:
    """Thin delegators to ``domain.notifications`` (P3.9d) — see module docstring.

    Expected on ``self`` (initialised by ``_CoreMixin.__init__``):
      - ``_notif_text_cache: dict[tuple[int,int,int], str]``
      - ``_notif_seen_ids: collections.OrderedDict[str, Any]``
      - ``_notif_baseline_done: bool``
      - ``_cloud: DreameA2CloudClient``
      - ``hass: HomeAssistant``

    Expected on ``self`` (provided by ``_DeviceSyncMixin``):
      - ``_fire_notification(*, event_type, text, code, siid, piid,
                            send_time, message_id, now_unix)``
    """

    async def _establish_notification_baseline(self) -> None:
        """Delegates to ``domain.notifications.establish_notification_baseline`` (P3.9d)."""
        await _notif.establish_notification_baseline(self)

    def _mark_notification_seen(self, message_id: str) -> None:
        """Delegates to ``domain.notifications.mark_notification_seen`` (P3.9d)."""
        _notif.mark_notification_seen(self, message_id)

    def _apply_device_messages(self, records: list | None) -> None:
        """Delegates to ``domain.notifications.apply_device_messages`` (P3.9d)."""
        _notif.apply_device_messages(self, records)

    def _merge_device_messages(self, fresh_dicts: list[dict]) -> list[dict]:
        """Delegates to ``domain.notifications.merge_device_messages`` (P3.9d)."""
        return _notif.merge_device_messages(self, fresh_dicts)

    async def _resolve_s2p2_notification(
        self, *, siid: int, piid: int, value: int, now_unix: int,
    ) -> None:
        """Delegates to ``domain.notifications.resolve_s2p2_notification`` (P3.9d).

        Passes the module-local ``_FETCH_DELAY_S`` so a test monkeypatch of
        ``_notifications._FETCH_DELAY_S`` still applies.
        """
        await _notif.resolve_s2p2_notification(
            self, siid=siid, piid=piid, value=value, now_unix=now_unix,
            fetch_delay_s=_FETCH_DELAY_S,
        )
