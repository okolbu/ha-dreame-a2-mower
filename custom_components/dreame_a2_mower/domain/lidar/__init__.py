"""LiDAR-domain service (layer 4) — refactor-v2 P3.9c.

The per-map LiDAR archive accessors + the two cloud-fetch paths (the live
``s99p20`` object-name handler and the one-shot ``3dmap`` startup backfill),
extracted VERBATIM from ``coordinator/_lidar_oss.py``. Each function takes the
coordinator (``coord``) as its first argument; the coordinator keeps thin
``_LidarOssMixin`` delegators for its public + test surface
(``coord.lidar_archive_for`` / ``.list_lidar_archive_entries`` /
``.set_lidar_render_entry`` / ``._handle_lidar_object_name`` /
``._backfill_lidar_from_3dmap``).

The archive/render-selection state (``lidar_archives``, ``_lidar_render_entry``,
``_last_lidar_object_name``, ``_lidar_backfill_done``, the archive root/retention
option attrs) still lives on ``_CoreMixin.__init__`` (T2-16: attrs move with the
full thin-coordinator collapse in 9e); these functions read/write it on
``coord``.
"""
