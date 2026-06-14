"""WiFi heatmap package — archive store, fingerprint matcher, PNG renderer.

Split out of the flat ``wifi_*`` root modules (Phase 3c, 2026-06-14). These are
NOT entity classes (no HA platform / audit interaction) — just the WiFi-heatmap
archive + matcher + renderer used by the coordinator and the camera/wifi
entities. The old root ``wifi_*.py`` paths remain as 1-line re-export shims so
the ~10 coordinator importers + test importers resolve unchanged.
"""
