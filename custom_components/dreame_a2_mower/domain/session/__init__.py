"""Session-domain services (layer 4).

- ``signals.py``          — session-TYPE signal capture (s2p50 op latch,
                            s2p56 multi-target ids, patrol-start latch, mode).
- ``lifecycle_events.py`` — the ``_on_state_update`` lifecycle-edge detectors
                            (dock / charging / rain / shutdown / session
                            begin-end inference / telemetry sampling), moved
                            VERBATIM (corpus-validated behaviour).
- ``finalize.py``         — the finalize state machine (P3.9a): routing, the
                            single latch, the dock-return wait, and the
                            OSS-summary assembly. Moved VERBATIM.
- ``persistence.py``      — the in_progress.json restore/persist lifecycle
                            (P3.9a).
- ``replay.py``           — session replay + work-log render orchestration +
                            the picked-session derivation folded in from the
                            deleted root ``session_card.py`` (T2-13; P3.9a).

The coordinator keeps thin ``_SessionMixin`` / ``_LidarOssMixin`` delegators for
its public + test surface.
"""
