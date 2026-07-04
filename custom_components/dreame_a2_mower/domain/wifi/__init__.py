"""WiFi-domain service (layer 4) — refactor-v2 P3.9c.

The WiFi archive-camera BODY CACHE + render-entry selection, extracted VERBATIM
from ``coordinator/_lidar_oss.py`` (§4), plus the map-extent geometry hint
(``build_map_extents``) that ``coordinator/_wifi_archive.py:refresh_wifi_archive``
feeds to ``cloud_client.list_wifi_candidates`` for heatmap→map matching.

**Consolidation note (P3.9c).** WiFi handling is split across three homes and
this module is the DOMAIN-service seam of it:

- ``wifi/`` (package, layer 4) — the pure support layer: ``archive_store`` (disk
  store), ``match`` (fingerprint matcher), ``map_render`` (heatmap→PNG). STAYS —
  no coordinator dependency.
- ``coordinator/_wifi_archive.py`` (``_WifiArchiveMixin``) — the archive-refresh
  orchestration. STAYS as a coordinator mixin for now (its full extraction is
  out of 9c scope; it calls this module's functions via the ``_LidarOssMixin``
  delegators, e.g. ``self._get_wifi_body_cached`` / ``self._build_map_extents``).
- ``domain/wifi/service.py`` (this module) — the render-entry SELECTION + the
  body cache load/read that used to live in ``_lidar_oss.py``, now consolidated
  here at the domain layer.

Each function takes the coordinator (``coord``) as its first argument; the
coordinator keeps thin ``_LidarOssMixin`` delegators for its public + test
surface (``coord._get_wifi_body_cached`` / ``._async_load_wifi_body`` /
``.set_wifi_render_entry`` / ``._build_map_extents``). The cache/selection state
(``_wifi_body_cache``, ``_wifi_render_entry``, ``_wifi_archive_store``) still
lives on ``_CoreMixin.__init__`` (T2-16: attrs move in 9e); these functions read
it on ``coord``.
"""
