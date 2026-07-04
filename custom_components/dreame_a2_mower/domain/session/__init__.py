"""Session-domain services (layer 4).

- ``signals.py``          — session-TYPE signal capture (s2p50 op latch,
                            s2p56 multi-target ids, patrol-start latch, mode).
- ``lifecycle_events.py`` — the ``_on_state_update`` lifecycle-edge detectors
                            (dock / charging / rain / shutdown / session
                            begin-end inference / telemetry sampling), moved
                            VERBATIM (corpus-validated behaviour).

Finalize / persistence / replay land here in later P3 sub-tasks (P3.8).
"""
