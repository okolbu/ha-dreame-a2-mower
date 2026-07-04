"""lidar_oss mixin — thin delegators (refactor-v2 P3.9c).

The LiDAR archive + OSS photo/video gallery + WiFi body-cache LOGIC moved
VERBATIM to the ``domain/`` layer (autopsy #10 §2/§3/§4/§5):

- ``domain/lidar/service.py``  — per-map LiDAR archive accessors +
                                 ``_handle_lidar_object_name`` (s99p20 fetch) +
                                 ``_backfill_lidar_from_3dmap``.
- ``domain/media/gallery.py``  — the OSS photo/video gallery: hourly/boot sync,
                                 signed-URL manifest, per-session manifest,
                                 device-message snapshot linking + the
                                 module-level ``fetch_photos_from_summary`` /
                                 ``merge_mow_type_fields`` OSS-summary helpers.
- ``domain/wifi/service.py``   — the WiFi archive-camera body cache +
                                 render-entry selection + ``_build_map_extents``.

Each domain function takes the coordinator (``coord``) as its first argument;
this mixin keeps thin delegating methods so the public/test surface
(``coord.lidar_archive_for``, ``coord._refresh_oss_gallery``,
``coord.set_wifi_render_entry``, the unbound ``_LidarOssMixin._X`` methods, the
``import coordinator._lidar_oss as L`` module handle) is unchanged. The
OSS-finalize assembly (``_inject_live_map_into_raw_dict`` / ``_do_oss_fetch[_body]``)
already delegates to ``domain/session/finalize.py`` (P3.9a).

See spec docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md
(original decomposition) + the refactor-v2 P3 plan.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

# Kept module-level so a test monkeypatch of ``_lidar_oss.async_call_later`` still
# intercepts: ``_schedule_post_session_gallery_refresh`` passes THIS binding into
# the domain gallery function (the domain/timers.py "callers pass their own
# async_call_later" convention). Also kept: ``photo_meta`` — test_oss_gallery_sync
# patches ``L.photo_meta.parse_jpeg_com`` (same module object the gallery uses).
from homeassistant.helpers.event import async_call_later  # noqa: F401

from ..archive.lidar import LidarArchive
from ..protocol import photo_meta  # noqa: F401

from ..domain.lidar import service as _lidar
from ..domain.media import gallery as _gallery
from ..domain.wifi import service as _wifi

from ..domain.session import finalize as _finalize
# P3.9a: the OSS-finalize assembly (finalize_classify_raw_dict,
# _inject_live_map_into_raw_dict, _do_oss_fetch[_body]) moved VERBATIM to
# domain/session/finalize.py. Re-export finalize_classify_raw_dict so the
# established ``coordinator._lidar_oss import finalize_classify_raw_dict`` test
# import path keeps resolving.
from ..domain.session.finalize import finalize_classify_raw_dict  # noqa: F401

# P3.9c: back-compat re-exports — tests import the module-level OSS-summary
# helpers from their old ``coordinator._lidar_oss`` home (test_archive_mow_type,
# test_photo_fetch). They now live in domain/media/gallery.py.
merge_mow_type_fields = _gallery.merge_mow_type_fields
fetch_photos_from_summary = _gallery.fetch_photos_from_summary

if TYPE_CHECKING:
    pass  # cross-mixin type imports added as needed


class _LidarOssMixin:
    """Thin delegators to ``domain.{lidar,media,wifi}`` (P3.9c) — see module docstring."""

    # ------------------------------------------------------------------
    # session/finalize (P3.9a) — OSS-finalize assembly
    # ------------------------------------------------------------------

    def _inject_live_map_into_raw_dict(self, raw_dict: dict[str, Any]) -> None:
        """Delegates to ``domain.session.finalize.inject_live_map_into_raw_dict`` (P3.9a)."""
        _finalize.inject_live_map_into_raw_dict(self, raw_dict)

    async def _do_oss_fetch(self, now_unix: int) -> None:
        """Delegates to ``domain.session.finalize.do_oss_fetch`` (P3.9a).

        The single finalize latch (P3e.4) is preserved VERBATIM in the domain
        module; concurrent same-session entries de-dupe there.
        """
        await _finalize.do_oss_fetch(self, now_unix)

    async def _do_oss_fetch_body(self, now_unix: int) -> None:
        """Delegates to ``domain.session.finalize.do_oss_fetch_body`` (P3.9a).

        Always invoked through _finalize_with_latch (never call directly). The
        OSS-summary download/parse/inject/archive assembly moved VERBATIM.
        """
        await _finalize.do_oss_fetch_body(self, now_unix)

    # ------------------------------------------------------------------
    # lidar service (P3.9c) — domain/lidar/service.py
    # ------------------------------------------------------------------

    def lidar_archive_for(self, map_id: int) -> LidarArchive:
        """Delegates to ``domain.lidar.service.lidar_archive_for`` (P3.9c)."""
        return _lidar.lidar_archive_for(self, map_id)

    def list_lidar_archive_entries(self) -> list[tuple[int, Any]]:
        """Delegates to ``domain.lidar.service.list_lidar_archive_entries`` (P3.9c)."""
        return _lidar.list_lidar_archive_entries(self)

    def set_lidar_render_entry(self, map_id: int | None, filename: str | None) -> None:
        """Delegates to ``domain.lidar.service.set_lidar_render_entry`` (P3.9c)."""
        _lidar.set_lidar_render_entry(self, map_id, filename)

    async def _handle_lidar_object_name(
        self, object_name: str, now_unix: int
    ) -> None:
        """Delegates to ``domain.lidar.service.handle_lidar_object_name`` (P3.9c)."""
        await _lidar.handle_lidar_object_name(self, object_name, now_unix)

    async def _backfill_lidar_from_3dmap(self, now_unix: int) -> None:
        """Delegates to ``domain.lidar.service.backfill_lidar_from_3dmap`` (P3.9c)."""
        await _lidar.backfill_lidar_from_3dmap(self, now_unix)

    # ------------------------------------------------------------------
    # media/gallery service (P3.9c) — domain/media/gallery.py
    # ------------------------------------------------------------------

    @property
    def photo_archive(self):
        """Return the shared PhotoArchive (album photos — not map-scoped)."""
        return self._photo_archive

    @property
    def video_archive(self):
        """Return the shared VideoArchive (patrol/AI-obstacle video clips)."""
        return self._video_archive

    # Re-exposed from the gallery service so the existing test surface
    # (``c._POST_SESSION_GALLERY_DELAY_S``) resolves; single source of truth.
    _POST_SESSION_GALLERY_DELAY_S = _gallery._POST_SESSION_GALLERY_DELAY_S

    def _schedule_post_session_gallery_refresh(self) -> None:
        """Delegates to ``domain.media.gallery.schedule_post_session_gallery_refresh``
        (P3.9c). Passes the module-local ``async_call_later`` so a test
        monkeypatch of ``_lidar_oss.async_call_later`` still intercepts."""
        _gallery.schedule_post_session_gallery_refresh(self, async_call_later)

    async def _refresh_oss_gallery(self, max_pages: int = 20) -> None:
        """Delegates to ``domain.media.gallery.refresh_oss_gallery`` (P3.9c)."""
        await _gallery.refresh_oss_gallery(self, max_pages)

    def _sign_media_path(self, path: str) -> str:
        """Delegates to ``domain.media.gallery.sign_media_path`` (P3.9c)."""
        return _gallery.sign_media_path(self, path)

    def _rebuild_photo_gallery(self) -> None:
        """Delegates to ``domain.media.gallery.rebuild_photo_gallery`` (P3.9c)."""
        _gallery.rebuild_photo_gallery(self)

    def session_photos_manifest(self, raw_dict: dict) -> list[dict]:
        """Delegates to ``domain.media.gallery.session_photos_manifest`` (P3.9c)."""
        return _gallery.session_photos_manifest(self, raw_dict)

    def _signed_photo_thumb(self, p) -> dict:
        """Delegates to ``domain.media.gallery.signed_photo_thumb`` (P3.9c)."""
        return _gallery.signed_photo_thumb(self, p)

    def link_message_snapshot_photos(self, messages: list[dict]) -> None:
        """Delegates to ``domain.media.gallery.link_message_snapshot_photos`` (P3.9c)."""
        _gallery.link_message_snapshot_photos(self, messages)

    # ------------------------------------------------------------------
    # wifi service (P3.9c) — domain/wifi/service.py
    # ------------------------------------------------------------------

    def _build_map_extents(self) -> dict[int, tuple[float, float, float, float]]:
        """Delegates to ``domain.wifi.service.build_map_extents`` (P3.9c)."""
        return _wifi.build_map_extents(self)

    def _get_wifi_body_cached(self, object_name: str) -> "dict | None":
        """Delegates to ``domain.wifi.service.get_wifi_body_cached`` (P3.9c)."""
        return _wifi.get_wifi_body_cached(self, object_name)

    async def _async_load_wifi_body(self, object_name: str) -> None:
        """Delegates to ``domain.wifi.service.async_load_wifi_body`` (P3.9c)."""
        await _wifi.async_load_wifi_body(self, object_name)

    def set_wifi_render_entry(
        self, map_id: int | None, object_name: str | None
    ) -> None:
        """Delegates to ``domain.wifi.service.set_wifi_render_entry`` (P3.9c)."""
        _wifi.set_wifi_render_entry(self, map_id, object_name)
