"""Media-domain service (layer 4) — refactor-v2 P3.9c.

The OSS photo/video gallery: the hourly/boot OSS media sync
(``refresh_oss_gallery``), the signed-URL gallery manifest builder
(``rebuild_photo_gallery`` / ``sign_media_path``), the per-session photo
manifest (``session_photos_manifest``), the device-message snapshot-photo
linker (``link_message_snapshot_photos``), and the post-finalize gallery
refresh scheduler — plus the module-level OSS-summary helpers
(``fetch_photos_from_summary`` / ``merge_mow_type_fields``) that the finalize
service calls. Extracted VERBATIM from ``coordinator/_lidar_oss.py`` (§3).

Each function takes the coordinator (``coord``) as its first argument; the
coordinator keeps thin ``_LidarOssMixin`` delegators for its public + test
surface. The photo/video archives (``_photo_archive`` / ``_video_archive``),
the gallery manifest (``_photo_gallery``), and the cloud client (``_cloud``)
still live on ``_CoreMixin.__init__`` (T2-16: attrs move in 9e); these
functions read them on ``coord``.

The 7-category photo categorization (``protocol/photo_category.categorize``)
and the camera-token-rotation double-broadcast (the explicit
``async_update_listeners()`` after the quota push + manifest rebuild) are
preserved byte-for-byte.
"""
