"""OSS photo/video gallery service (layer 4) — refactor-v2 P3.9c.

Moved VERBATIM from ``coordinator/_lidar_oss.py`` (§3 photo/video gallery). Each
function that needs the coordinator takes it (``coord``) as its first argument.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from ..timers import schedule_self_cleaning
from ...const import LOGGER
from ...protocol import photo_meta
from ...protocol.photo_category import categorize

# Delay before the post-finalize gallery sync. Long enough for the device's
# async media upload to land on OSS, short enough to beat the hourly cycle.
_POST_SESSION_GALLERY_DELAY_S = 60

# A "View snapshots in the app." notification carries no photo reference —
# only its timestamp; the AI-detection photo lands a few seconds LATER
# (e.g. a human-detection alert at T had its ai_human photo at T+5s,
# app-mitm corpus 2026-06-15). So link by a timestamp window over the
# AI-detection categories (NOT patrol, which has its own "view work log"
# notification and its own per-session linkage).
_SNAPSHOT_MARKER = "view snapshots"
_SNAPSHOT_CATEGORIES = ("ai_human", "obstacle", "person")
_SNAPSHOT_WINDOW_BEFORE_S = 120
_SNAPSHOT_WINDOW_AFTER_S = 600


def merge_mow_type_fields(raw_dict: dict, *, mode: int, start_mode: int) -> None:
    """Write mow_type / mow_type_raw / start_mode_label from the OSS summary."""
    from ...protocol.session_summary import mow_type_from_mode, start_mode_label
    label = mow_type_from_mode(mode)
    if label is not None:
        raw_dict["mow_type"] = label
    raw_dict["mow_type_raw"] = mode
    sm = start_mode_label(start_mode)
    if sm is not None:
        raw_dict["start_mode_label"] = sm


def _photo_ts_from_name(name: str) -> int:
    import re
    m = re.match(r"(\d{9,11})", name)
    return int(m.group(1)) if m else 0


def _iso_to_unix(value: Any) -> int | None:
    """Parse a Message.date ISO-8601 string (e.g. '2026-06-15T21:27:59+00:00')
    to a unix timestamp; None on anything unparseable."""
    if not isinstance(value, str) or not value:
        return None
    from datetime import datetime
    try:
        return int(datetime.fromisoformat(value).timestamp())
    except (ValueError, TypeError):
        return None


def fetch_photos_from_summary(cloud, archive, raw_dict, *, sign) -> int:
    """Fetch every photo_list leaf into the PhotoArchive. Returns count added.

    [dreame-app-implementation-guide-2026-06-09.md] photo_list entries are
    <ts>[_person].jpg leaves; the OSS key is built via protocol/photo_keys.
    `sign(cloud, key)` is the signing endpoint (get_interim_file_url or
    get_file_url) — injected so this stays testable and so the live-confirmed
    endpoint can be swapped in. Cloud I/O here is synchronous; callers run the
    whole coroutine in an executor job.
    """
    from ...protocol.photo_keys import build_photo_object_key, is_person_photo
    names = raw_dict.get("photo_list") or []
    if not isinstance(names, list):
        return 0
    added = 0
    for name in names:
        if not isinstance(name, str) or not name:
            continue
        ts = _photo_ts_from_name(name)
        key = build_photo_object_key(uid=str(cloud._uid), did=str(cloud._did), name=name)
        url = sign(cloud, key)
        if not url:
            continue
        body = cloud.get_file(url)
        if not body:
            continue
        meta = photo_meta.parse_jpeg_com(body)
        category = categorize(name=name, record={"type": "jpg"}, com=meta)
        detections = (meta or {}).get("detections") or []
        entry = archive.archive(
            name=name, unix_ts=ts, data=body, is_person=is_person_photo(name),
            category=category, detections=detections,
        )
        if entry is not None:
            added += 1
    return added


def schedule_post_session_gallery_refresh(coord, async_call_later) -> None:
    """Schedule a single OSS gallery sync ``_POST_SESSION_GALLERY_DELAY_S``
    after a session finalizes. Bounded (one per finalize) and idempotent
    (``refresh_oss_gallery`` dedups by name/id), so it is safe even if it
    overlaps the hourly sync. No-op when hass is unavailable.

    ``async_call_later`` is passed IN by the coordinator delegator (its own
    module-local binding) so a test monkeypatch of
    ``coordinator._lidar_oss.async_call_later`` still intercepts — the
    ``timers`` "callers pass their own async_call_later" convention.
    """
    hass = getattr(coord, "hass", None)
    if hass is None:
        return

    async def _run(_now: Any) -> None:
        try:
            await coord._refresh_oss_gallery()
        except Exception:  # noqa: BLE001 — a sync failure must not propagate
            LOGGER.exception("post-session OSS gallery refresh failed")

    # T3-8 + P2-inherit (P3.8): schedule via the self-cleaning canceller
    # registry so a reload/unload within the delay window cancels this
    # one-shot AND the config-entry's unload-listener list does not grow by
    # one on every finalize — the timer self-removes on fire and a single
    # unload hook cancels all outstanding timers. See domain/timers.py.
    schedule_self_cleaning(
        coord, async_call_later, _POST_SESSION_GALLERY_DELAY_S, _run
    )


async def refresh_oss_gallery(coord, max_pages: int = 20) -> None:
    """Canonical OSS media sync: archive new photos (categorized via COM
    metadata) + videos, and update quota. Runs hourly + at startup (the
    per-session photo_list fetch remains the immediate session-end path).

    ``max_pages`` caps how deep ``list_oss_media`` pages into the cloud's
    media history. The hourly call uses the default (recent items, cheap);
    the boot call passes a large value (full backfill) — ``list_oss_media``
    stops at the first short page, so the cap is just a ceiling.
    """
    if not hasattr(coord, "_cloud") or coord._cloud is None:
        return
    import json as _json
    from datetime import datetime, timezone

    def _ts(rec):
        ut = rec.get("uploadTime")
        try:
            return int(datetime.strptime(ut, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
        except (TypeError, ValueError):
            return 0

    def _leaf(url):
        # the OSS object leaf, e.g. ".../ali_dreame/1780952775_person.jpg?Expires=..."
        base = (url or "").split("?", 1)[0]
        return base.rsplit("/", 1)[-1] if base else ""

    # --- photos ---
    photos = await coord.hass.async_add_executor_job(
        lambda: coord._cloud.list_oss_media("jpg", max_pages=max_pages)
    )
    for rec in (photos or []):
        name = _leaf(rec.get("filepath"))
        if not name or coord._photo_archive.has_name(name):
            continue
        data = await coord.hass.async_add_executor_job(coord._cloud.get_file, rec.get("filepath"))
        if not data:
            continue
        # Guard against corrupt/non-JPEG downloads (observed: OSS occasionally
        # returns garbage bytes). Archiving them produces a broken thumbnail
        # in the gallery; skip so the next sync can retry cleanly.
        if data[:2] != b"\xff\xd8":
            LOGGER.warning(
                "[PHOTOS] skipping non-JPEG download for %s (%d bytes, magic=%s)",
                name, len(data), data[:4].hex(),
            )
            continue
        meta = photo_meta.parse_jpeg_com(data)
        is_person = name.lower().endswith("_person.jpg")
        category = categorize(name=name, record=rec, com=meta)
        detections = (meta or {}).get("detections") or []
        await coord.hass.async_add_executor_job(
            lambda d=data, n=name, t=_ts(rec), ip=is_person, c=category, det=detections:
            coord._photo_archive.archive(name=n, unix_ts=t, data=d, is_person=ip, category=c, detections=det))

    # --- videos ---
    videos = await coord.hass.async_add_executor_job(
        lambda: coord._cloud.list_oss_media("thumb", max_pages=max_pages)
    )
    for rec in (videos or []):
        vid = str(rec.get("id") or rec.get("key") or "")
        if not vid or coord._video_archive.has(vid):
            continue
        thumb = await coord.hass.async_add_executor_job(coord._cloud.get_file, rec.get("filepath"))
        mp4 = await coord.hass.async_add_executor_job(coord._cloud.get_file, rec.get("videoPath"))
        if not mp4 or not thumb:
            continue
        try:
            duration = int(_json.loads(rec.get("ext") or "{}").get("duration") or 0)
        except (ValueError, TypeError):
            duration = 0
        await coord.hass.async_add_executor_job(
            lambda v=vid, m=mp4, th=thumb, t=_ts(rec), du=duration:
            coord._video_archive.archive(video_id=v, mp4=m, thumb=th, unix_ts=t, duration=du))

    # --- quota ---
    quota = await coord.hass.async_add_executor_job(coord._cloud.fetch_oss_quota)
    if quota:
        import dataclasses
        new = dataclasses.replace(coord.data, oss_storage_used=quota.get("used"),
                                  oss_storage_total=quota.get("total"))
        if new != coord.data:
            coord.async_set_updated_data(new)

    # --- gallery manifest (newest-first, signed media URLs) ---
    coord._rebuild_photo_gallery()


def sign_media_path(coord, path: str) -> str:
    """Sign a local media API path so an ``<img>``/``<video>`` tag can load
    it without an auth header.

    ``PhotoFileView`` / ``VideoFileView`` / ``VideoThumbView`` are
    ``requires_auth = True`` (the JPEGs contain people), so the gallery card
    needs a signed URL. ``async_sign_path`` is a MODULE-LEVEL function taking
    ``hass`` first (NOT a method on ``hass.http`` — that attribute does not
    exist and raised AttributeError, leaving the manifest empty). The
    manifest is built in a background task with no request/websocket context,
    so ``use_content_user=True`` signs with HA's content user (the same path
    camera ``entity_picture`` uses) and validates for all frontend sessions.
    """
    # async_sign_path lives in http.auth and is NOT re-exported at the
    # http package level (importing from `homeassistant.components.http`
    # raises ImportError on 2026.6).
    from homeassistant.components.http.auth import async_sign_path
    return async_sign_path(
        coord.hass, path, timedelta(days=7), use_content_user=True
    )


def rebuild_photo_gallery(coord) -> None:
    """Rebuild ``coord._photo_gallery`` from the photo + video archives.

    Each item is a self-describing dict the gallery card consumes — see the
    manifest shape in docs/superpowers/specs/2026-06-12-photo-gallery.md.
    URLs are signed via ``sign_media_path`` (the module-level
    ``homeassistant.components.http.async_sign_path``, content-user signed)
    with a 7-day window; the manifest is rebuilt hourly so the signatures are
    always fresh. Wrapped in try/except so a signing or index-IO hiccup never
    breaks the OSS sync.
    """
    from datetime import datetime

    def _date(ts: int) -> str:
        try:
            return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")
        except (OverflowError, OSError, ValueError):
            return ""

    try:
        items: list[dict[str, Any]] = []
        for p in coord._photo_archive.list_photos():
            url = coord._sign_media_path("/api/dreame_a2_mower/photo/" + p.filename)
            items.append({
                "type": "photo",
                "id": p.filename,
                "ts": int(p.unix_ts),
                "date": _date(p.unix_ts),
                "category": p.category,
                "detections": p.detections or [],
                "url": url,
                "thumb_url": url,
            })
        for v in coord._video_archive.list_videos():
            items.append({
                "type": "video",
                "id": v.video_id,
                "ts": int(v.unix_ts),
                "date": _date(v.unix_ts),
                "category": "video",
                "duration": int(v.duration),
                "url": coord._sign_media_path("/api/dreame_a2_mower/video/" + v.video_id),
                "thumb_url": coord._sign_media_path("/api/dreame_a2_mower/video_thumb/" + v.video_id),
            })
        items.sort(key=lambda it: it["ts"], reverse=True)
        coord._photo_gallery = items
    except Exception as ex:  # noqa: BLE001 — manifest never breaks the sync
        LOGGER.warning("[PHOTOS] gallery manifest build failed: %s", ex)
    # The OSS sync runs outside the coordinator's push cycle (and the quota
    # push above fires BEFORE this rebuild), so notify entities explicitly
    # or the gallery sensor never reflects the freshly-built manifest.
    update = getattr(coord, "async_update_listeners", None)
    if callable(update):
        update()
    LOGGER.debug(
        "[PHOTOS] manifest rebuilt: %d items", len(coord._photo_gallery),
    )


def session_photos_manifest(coord, raw_dict: dict) -> list[dict]:
    """Signed thumbnails for ONE session's photos, for the replay screen.

    Matching is photo_list-only for now: the session summary's authoritative
    per-session filenames (covers patrol + 'to point' auto-capture). Matches
    by CAPTURE TIMESTAMP (shared by the bare `<ts>.jpg` photo_list name and the
    `<ts>_person.jpg` gallery variant) so md5-dedup storing either name still
    links. AI-obstacle photos that fall OUTSIDE photo_list are NOT included
    yet — a timestamp-window union is the planned follow-up (todo6 #6) once
    their appearance relative to photo_list is understood.

    Returns ``[{id, ts, category, detections, url, thumb_url}]`` (oldest-first)
    — the same item shape the gallery card consumes; empty on any problem.
    """
    names = raw_dict.get("photo_list") or []
    archive = coord._photo_archive if hasattr(coord, "_photo_archive") else None
    if not isinstance(names, list) or not names or archive is None:
        return []
    by_ts: dict[int, list] = {}
    for p in archive.list_photos():
        by_ts.setdefault(int(p.unix_ts), []).append(p)
    seen: set[str] = set()
    items: list[dict] = []
    for name in names:
        if not isinstance(name, str) or not name:
            continue
        ts = int(_photo_ts_from_name(name))
        for p in by_ts.get(ts, ()):  # >1 only on same-second captures
            if p.filename in seen:
                continue
            seen.add(p.filename)
            items.append(coord._signed_photo_thumb(p))
    items.sort(key=lambda it: it["ts"])
    return items


def signed_photo_thumb(coord, p) -> dict:
    """One archived photo → a signed gallery item dict (thumb == full URL)."""
    url = coord._sign_media_path("/api/dreame_a2_mower/photo/" + p.filename)
    return {
        "id": p.filename,
        "ts": int(p.unix_ts),
        "category": p.category,
        "detections": p.detections or [],
        "url": url,
        "thumb_url": url,
    }


def _is_snapshot_message(msg: dict) -> bool:
    return _SNAPSHOT_MARKER in str(msg.get("title") or "").lower()


def link_message_snapshot_photos(coord, messages: list[dict]) -> None:
    """Attach matched snapshot thumbnails (signed) to device-message dicts
    IN PLACE, as ``msg['photos']``. Messages without the "View snapshots in
    the app." marker, or with no photo in the time window, are left
    untouched (no ``photos`` key). Matching is timestamp-window over the
    AI-detection photo categories — see the module constants above."""
    archive = coord._photo_archive if hasattr(coord, "_photo_archive") else None
    if archive is None or not messages:
        return
    if not any(_is_snapshot_message(m) for m in messages):
        return  # avoid the archive read when nothing needs linking
    det_photos = [
        p for p in archive.list_photos()
        if p.category in _SNAPSHOT_CATEGORIES
    ]
    if not det_photos:
        return
    for m in messages:
        if not _is_snapshot_message(m):
            continue
        ts = _iso_to_unix(m.get("date"))
        if ts is None:
            continue
        lo = ts - _SNAPSHOT_WINDOW_BEFORE_S
        hi = ts + _SNAPSHOT_WINDOW_AFTER_S
        matched = sorted(
            (p for p in det_photos if lo <= int(p.unix_ts) <= hi),
            key=lambda p: int(p.unix_ts),
        )
        if matched:
            m["photos"] = [coord._signed_photo_thumb(p) for p in matched]
