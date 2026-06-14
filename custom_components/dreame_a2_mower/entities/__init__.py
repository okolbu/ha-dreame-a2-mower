"""Entity implementation package — sensor / switch / select entity classes.

Split out of the flat root entity-impl modules (Phase 3c, 2026-06-14). The thin
HA platform loaders (``sensor.py``, ``switch.py``, ``select.py``) stay at the
package root and import the entity classes / description tables from here. The
old flat root paths remain as 1-line re-export shims so the deep test imports
resolve unchanged. The FAT single-platform files (``number.py``,
``binary_sensor.py``, ``button.py``, ``time.py``, ``device_tracker.py``,
``lawn_mower.py``, ``calendar.py``, ``event.py``) are themselves the platform
entry and stay at root.
"""
