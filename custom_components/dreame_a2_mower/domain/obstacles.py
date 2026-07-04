"""Live AIOBS obstacle-marker refresh service (layer 4) — refactor-v2 P3.9e.

Moved VERBATIM from ``coordinator/_refreshers.py`` (the mow-gated AIOBS marker
poll + the file-bridge photo-fetch loop). Each function takes the coordinator
(``coord``) as its first argument; the coordinator keeps thin
``_RefreshersMixin`` delegators so the public/test surface
(``coord._refresh_aiobs`` / ``coord._fetch_pending_obstacle_photos``, pinned by
``test_aiobs_sensor`` / ``test_aiobs_photo_fetch``) is unchanged. Internal
cross-method calls route through the coordinator delegators
(``coord._schedule_render_base`` / ``coord._fetch_pending_obstacle_photos``).
"""
from __future__ import annotations

import hashlib

from ..const import LOGGER


async def refresh_aiobs(coord) -> None:
    """Poll the live AIOBS obstacle markers — ONLY while a mow session is
    active. Mow-gated minutes cadence: the app polls AIOBS only while a human
    is viewing the live map (~281 reads across a multi-day capture); we have no
    "viewing" signal, so the safe analogue is session-gated, one read per timer
    tick. Do NOT poll at seconds cadence / 24-7.
    [cloud/captures/mitm_session_20260619/miio-13267.jsonl@2026-06-17]
    """
    from ..mower.state_snapshot import MowSession  # local import: avoid cycle

    snap = coord.state_machine.snapshot()
    mow_session = getattr(snap, "mow_session", None)
    # Gate: only proceed when a mow session is active.
    # The real integration path has MowSession.IN_SESSION; the unit-test stub
    # passes the string "IN_SESSION" — handle both with the positive check
    # (enum value = "in_session", enum name = "IN_SESSION").
    is_active = (
        mow_session == MowSession.IN_SESSION
        or (isinstance(mow_session, str)
            and mow_session in (MowSession.IN_SESSION.name, MowSession.IN_SESSION.value))
    )
    if not is_active:
        if coord._obstacle_markers:
            coord._obstacle_markers = []
            if getattr(coord, "hass", None) is not None:
                coord._schedule_render_base()
        return
    hass = getattr(coord, "hass", None)
    markers = (
        await hass.async_add_executor_job(coord._cloud.fetch_aiobs_markers)
        if hass is not None else coord._cloud.fetch_aiobs_markers()
    )
    if markers is None:
        return
    coord._obstacle_markers = markers
    for m in markers:
        coord._obstacle_marker_log.note(m)
    # Trigger a re-render so new markers paint on the live map immediately.
    if getattr(coord, "hass", None) is not None:
        coord._schedule_render_base()
    # Download photos for any pending markers (bounded: one pass per tick).
    try:
        await coord._fetch_pending_obstacle_photos()
    except Exception as exc:  # noqa: BLE001
        LOGGER.debug("[aiobs] _fetch_pending_obstacle_photos raised: %s", exc)


async def fetch_pending_obstacle_photos(coord) -> None:
    """Download photos for live-session AIOBS markers via the file-bridge client.

    Bounded: iterates coord._obstacle_markers (the CURRENT live-session set),
    which is volatile and cleared at session end — so this naturally does NOT
    retry ancient cross-session failures.  Within the current mow we attempt
    every marker whose stored status is not yet ready/gone on each 2-min tick.
    This retries backend_unavailable markers mid-session so photos are captured
    as soon as the backend recovers.  One attempt per marker per tick — not a
    tight inner retry.

    On backend failure → mark backend_unavailable; on success → store bytes
    in PhotoArchive (category obstacle_ephemeral) and flip to ready.
    Per-marker failures are isolated so one bad marker doesn't abort the loop.
    [UNVERIFIED signer — backend currently down; loop marks all attempts
    backend_unavailable until the backend is verified and returns bytes]
    """
    log = coord._obstacle_marker_log
    # Build a quick status-by-id map from the durable log so we can skip
    # markers that are already captured or confirmed gone.
    status_by_id = {r.id: r.image_status for r in log.all()}

    get_file = getattr(coord._cloud, "get_device_file", None)
    hass = getattr(coord, "hass", None)

    for marker in list(coord._obstacle_markers):
        # Skip already-captured or gone markers; default to "pending" if the
        # marker hasn't been noted yet (note() is called earlier in _refresh_aiobs
        # so this is a defensive fallback only).
        if status_by_id.get(marker.id, "pending") in {"ready", "gone"}:
            continue
        try:
            fn = f"{marker.filename}.jpg"
            if get_file is None:
                log.set_status(marker.id, "backend_unavailable")
                continue
            data = (
                await hass.async_add_executor_job(get_file, fn)
                if hass is not None else get_file(fn)
            )
            if not data:
                log.set_status(marker.id, "backend_unavailable")
                continue
            md5 = hashlib.md5(data).hexdigest()
            coord._photo_archive.archive(
                name=fn,
                unix_ts=int(marker.detection_epoch or 0),
                data=data,
                is_person=False,
                category="obstacle_ephemeral",
            )
            log.set_status(marker.id, "ready", image_md5=md5)
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("[aiobs] photo fetch failed for %s: %s", marker.id, exc)
