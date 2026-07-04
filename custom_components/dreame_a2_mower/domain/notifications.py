"""Cloud-notification resolver service (layer 4) — refactor-v2 P3.9d.

Moved VERBATIM from ``coordinator/_notifications.py``. Replaces the previous
hardcoded ``S2P2_NOTIFICATION_MAP[code] = (slug, text)`` inline-firing model
with a cloud-as-source-of-truth flow:

  - On every MQTT s2p2 transition, schedule ``resolve_s2p2_notification``.
  - That task waits ~10 s for the cloud to finish writing its push record,
    then fetches ``/dreame-messaging/user/device-messages/v2`` (latest 10).
  - It finds the first record matching ``(siid, piid, value)`` whose
    ``messageId`` is NOT in ``_notif_seen_ids``.
  - On match: fire ``event.dreame_a2_mower_notification`` with the cloud's
    authoritative text (account-language-localised) + the s2p2 slug.
  - On no match: cloud didn't push (e.g. wear%-gated 28 with fresh blades) —
    no event fires.

Each function takes the coordinator (``coord``) as its first argument; the
coordinator keeps thin ``_NotificationsMixin`` delegators so the public/test
surface is unchanged.

In-memory state only (per the 2026-05-26 design call):
  - ``_notif_text_cache: {(siid,piid,value) -> text}``  display fallback.
  - ``_notif_seen_ids: OrderedDict[messageId, True]``   replay suppression,
                                                    capped at 100 (FIFO).
  - ``_notif_baseline_done: bool``                     one-shot startup flag.

Cache and seen_ids are NEVER persisted — restart wipes them. On startup the
baseline fetch silently seeds ``_notif_seen_ids`` with whatever the cloud
currently holds, so old records don't replay as fresh events when HA boots.

See docs/research/app-api-surface-2026-05-25.md § device-messages/v2 and
docs/research/app-notification-history-2026-05-16.md § Empirical s2p2 mapping.
"""
from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

from ..const import CONF_MESSAGES_KEEP, DEFAULT_MESSAGES_KEEP, LOGGER
from ..mower import fault_catalog
from ..protocol import message_record
from ..state.apply import S2P2_EVENT_TYPES, S2P2_UNKNOWN_EVENT_TYPE

# Tunables. The cloud push lands a few seconds after the MQTT s2p2 event,
# so we delay before fetching. 10s is comfortable; if it's too short we'll
# miss the record and fire nothing (which is correct).
#
# NOTE: the effective delay is passed in by the coordinator delegator
# (``coordinator/_notifications.py:_FETCH_DELAY_S``) so the established test
# monkeypatch of that module attribute still applies. This module-level
# constant is the fallback default only.
_FETCH_DELAY_S: float = 10.0

# Debounce window for persisting the accumulated device-message list.
DEVICE_MESSAGES_SAVE_DELAY_S = 5
_FETCH_PAGE_SIZE: int = 10
_SEEN_IDS_CAP: int = 100


async def establish_notification_baseline(coord) -> None:
    """One-shot at setup. Populate seen_ids + warm text cache.

    NEVER fires events — these records are the pre-history snapshot.
    Subsequent s2p2 transitions only fire when a NEW messageId arrives.
    """
    if coord._notif_baseline_done:
        return
    cloud = coord.cloud
    if cloud is None:
        return
    did = getattr(cloud, "device_id", None) or getattr(cloud, "_did", None)
    if not did:
        return
    records = await coord.hass.async_add_executor_job(
        cloud.fetch_device_messages, did, _FETCH_PAGE_SIZE,
    )
    if records is None:
        LOGGER.debug(
            "[notif] baseline: cloud unreachable; will retry on next s2p2"
        )
        return
    for r in records:
        mid = r.get("messageId")
        if mid:
            coord._mark_notification_seen(mid)
        key = _source_key(r.get("source"))
        if key is None:
            continue
        text = _english_text(r)
        if text:
            coord._notif_text_cache[key] = text
    coord._notif_baseline_done = True
    LOGGER.info(
        "[notif] baseline established: %d records seen, %d distinct sources cached",
        len(records), len(coord._notif_text_cache),
    )


def mark_notification_seen(coord, message_id: str) -> None:
    """FIFO insert into ``_notif_seen_ids`` with ``_SEEN_IDS_CAP``."""
    d = coord._notif_seen_ids
    if message_id in d:
        d.move_to_end(message_id)
    else:
        d[message_id] = True
    while len(d) > _SEEN_IDS_CAP:
        d.popitem(last=False)


def apply_device_messages(coord, records: list | None) -> None:
    """Reactively refresh ``MowerState.device_messages`` from a freshly
    fetched device-messages/v2 page (called by the s2p2 resolver), merging
    it into the accumulated list so the sensor reflects new notifications
    immediately. No-op on an empty page."""
    if not records:
        return
    fresh = [m.as_dict() for m in message_record.normalize_device(records)]
    merged = coord._merge_device_messages(fresh)
    new = dataclasses.replace(coord.data, device_messages=merged)
    if new != coord.data:
        coord.async_set_updated_data(new)


def merge_device_messages(coord, fresh_dicts: list[dict]) -> list[dict]:
    """Merge a freshly-fetched device-message page into the accumulated list.

    Unions by id with the persisted list (existing wins → keeps linked
    ``photos`` + immutable text), newest-first, capped at CONF_MESSAGES_KEEP,
    links snapshot photos, and schedules a debounced persist. Returns the
    merged list. The cloud windows device-messages/v2 to the latest ~10, so
    accumulation is the only way to retain more.
    """
    entry = getattr(coord, "entry", None)
    cap = int(
        entry.options.get(CONF_MESSAGES_KEEP, DEFAULT_MESSAGES_KEEP)
        if entry is not None else DEFAULT_MESSAGES_KEEP
    )
    existing = list(getattr(coord.data, "device_messages", None) or [])
    merged = message_record.merge_device_messages(existing, fresh_dicts, cap)
    coord.link_message_snapshot_photos(merged)
    store = coord._device_messages_store if hasattr(coord, "_device_messages_store") else None
    if store is not None:
        store.async_delay_save(lambda: merged, DEVICE_MESSAGES_SAVE_DELAY_S)
    return merged


async def resolve_s2p2_notification(
    coord, *, siid: int, piid: int, value: int, now_unix: int,
    fetch_delay_s: float = _FETCH_DELAY_S,
) -> None:
    """Cloud resolver — called from ``_on_state_update`` per s2p2 transition.

    Sleeps ``fetch_delay_s``, fetches the latest device-messages page,
    finds the first record with source matching ``(siid, piid, value)`` and
    an unseen messageId. Fires the notification event with cloud text.
    """
    cloud = coord.cloud
    if cloud is None:
        return
    did = getattr(cloud, "device_id", None) or getattr(cloud, "_did", None)
    if not did:
        return

    # If we haven't established baseline yet, do it now (silent — this
    # s2p2's record will be among the baselined ones and no event will
    # fire for it; subsequent transitions will).
    if not coord._notif_baseline_done:
        await coord._establish_notification_baseline()
        return

    await asyncio.sleep(fetch_delay_s)

    records = await coord.hass.async_add_executor_job(
        cloud.fetch_device_messages, did, _FETCH_PAGE_SIZE,
    )
    if records is None:
        LOGGER.debug(
            "[notif] s%dp%d=%d resolver: cloud unreachable; no event fired",
            siid, piid, value,
        )
        return

    # Reactively refresh the device-messages list sensor from this freshly
    # fetched page so the Info-tab Device card updates immediately, instead
    # of lagging up to an hour for the next _refresh_messages cycle.
    coord._apply_device_messages(records)

    # Find the FIRST unseen record whose source matches.
    target_key = (siid, piid, value)
    matching: dict[str, Any] | None = None
    for r in records:
        key = _source_key(r.get("source"))
        if key != target_key:
            continue
        mid = r.get("messageId")
        if not mid or mid in coord._notif_seen_ids:
            continue
        matching = r
        break

    if matching is None:
        LOGGER.debug(
            "[notif] s%dp%d=%d transition: cloud did not push (or already seen)",
            siid, piid, value,
        )
        return

    # Prefer the cloud's authoritative English push text; fall back to the
    # bundled app catalog so the payload (and logbook) still get a real
    # string when the cloud push briefly lacks one.
    text = _english_text(matching) or fault_catalog.fault_text(value, "en") or ""
    message_id = matching["messageId"]
    send_time = matching.get("sendTime")

    is_novel_source = target_key not in coord._notif_text_cache
    coord._notif_text_cache[target_key] = text
    coord._mark_notification_seen(message_id)

    if is_novel_source:
        if value in S2P2_EVENT_TYPES:
            # Code is already mapped (e.g. s2p2=54 low_battery_return); this
            # is just the first time we've seen its cloud text THIS session
            # (the text cache is per-process, so it re-fires every restart).
            # Not novel — debug only.
            LOGGER.debug(
                "[notif] first cloud text this session for known "
                "s%dp%d=%d: text=%r (message_id=%s)",
                siid, piid, value, text, message_id,
            )
        else:
            LOGGER.warning(
                "[notif] novel s%dp%d=%d source from cloud: text=%r "
                "(message_id=%s) — please report this code+text to the "
                "integration maintainer so it can be added to S2P2_EVENT_TYPES.",
                siid, piid, value, text, message_id,
            )

    event_type = S2P2_EVENT_TYPES.get(value, S2P2_UNKNOWN_EVENT_TYPE)
    coord._fire_notification(
        event_type=event_type,
        text=text,
        code=value,
        siid=siid,
        piid=piid,
        send_time=send_time,
        message_id=message_id,
        now_unix=now_unix,
    )


# Module-level helpers (pure, no `coord`) so they're trivially testable.

def _source_key(src: Any) -> tuple[int, int, int] | None:
    """Normalise a record's `source` dict to (siid, piid, value) ints.

    The cloud returns siid/piid/value as STRINGS (e.g. ``"2"``, ``"28"``).
    Returns None if any field is missing or non-numeric.
    """
    if not isinstance(src, dict):
        return None
    try:
        return (int(src["siid"]), int(src["piid"]), int(src["value"]))
    except (KeyError, TypeError, ValueError):
        return None


def _english_text(record: Any) -> str | None:
    """Pull the English localisation from a notification record.

    Falls back to ``en-US`` if ``en`` is absent. Returns None if neither
    exists or `record` isn't shaped right. The cloud uses account-language
    for the user-facing app push; for now the integration's event payload
    uses ``en`` as a stable default (HA UI shows what the user reads in
    their language separately, via translation_key).
    """
    if not isinstance(record, dict):
        return None
    loc = record.get("localizationContents")
    if not isinstance(loc, dict):
        return None
    return loc.get("en") or loc.get("en-US") or None
