---
name: Dreame A2 Mower HA Integration — Fork + Phase 1 Design
date: 2026-04-17
status: draft
---

# Dreame A2 Mower HA Integration

## Goals

Deliver a Home Assistant integration that exposes the Dreame A2 (`dreame.mower.g2408`) mower with working support for the protocol and properties already reverse-engineered, and — in later phases — a live visual map comparable to the Dreame iOS app.

Upstream `nicolasglg/dreame-mova-mower` recently narrowed its scope to A1 Pro only (commit `f700217`). The A2 has materially different siid/piid assignments, different transport semantics, and a large, separately-discovered config channel (`s2p51`). An upstream PR path is not viable; a clean fork is.

## Non-goals

- Support for any Dreame mower other than g2408. Other models, vacuums, and Mi devices are removed.
- Upstreaming changes back to `nicolasglg/dreame-mova-mower`.
- Reaching feature parity with the Dreame app for all settings. BT-only settings (per reverse-engineering findings) are read-only or absent.
- Cloud-first device control. The cloud HTTP `sendCommand` API consistently fails for g2408; MQTT is authoritative.

## Fork strategy

Fork `nicolasglg/dreame-mova-mower` on GitHub into the user's account as a new repository (working name: `ha-dreame-a2-mower`). Clone locally under `/data/claude/homeassistant/`. Rename the HA `DOMAIN` from `dreame_mower` to `dreame_a2_mower` in the first two commits so that HACS installs of the fork do not collide with existing `dreame_mower` installs (including the one currently running on the target HA instance).

The existing `/config/custom_components/dreame_mower/` on the HA server stays installed during development. The fork installs alongside as `dreame_a2_mower`, allowing A/B comparison until the new integration reaches parity and the old one can be removed.

Attribution to the upstream project is preserved in `README.md` and `LICENSE`. No license change.

## Architecture direction: MQTT-first

The current upstream integration treats MQTT as a secondary notification channel on top of a cloud HTTP control plane. For g2408 that model is broken: live logs on the target HA confirm the exact failure mode documented in the reverse-engineering findings — `Cloud send error 80001` with "device may be offline" from `custom_components.dreame_mower.dreame.protocol` on every command attempt.

The fork inverts this:

- **MQTT as control plane.** Commands, state, and property updates are read from and written to MQTT. The protocol encoder stays, but the dispatcher prefers MQTT publish over HTTP `sendCommand`.
- **Cloud HTTP reserved for login, device discovery, and token refresh.** These paths work and are the only ones used.
- **`s2p51` decoder as a first-class component.** Config settings arrive as a multiplexed payload whose shape depends on the setting; a dedicated decoder module converts these into typed HA entities rather than opaque blobs.
- **Telemetry decoder for `s1p4`.** The 33-byte mowing telemetry blob is fully decoded in the reverse-engineering findings and becomes a module with well-defined inputs (raw bytes) and outputs (position, phase, area, distance, obstacle flag).

## Component boundaries (Phase 1)

Each unit has one purpose, a narrow interface, and can be tested in isolation with fixtures drawn from the existing `.jsonl` probe logs.

- **`protocol/mqtt_client.py`** — connects, subscribes to the per-device topic, yields decoded messages. No HA dependencies.
- **`protocol/telemetry.py`** — parses `s1p4` bytes into a `MowingTelemetry` dataclass. Pure function.
- **`protocol/config_s2p51.py`** — decodes/encodes `s2p51` payloads per setting key, yielding typed values. Pure function.
- **`protocol/properties.py`** — the g2408-specific siid/piid property map. Replaces the multi-model registry in upstream's `types.py`.
- **`coordinator.py`** — bridges the protocol layer to HA. Owns reconnection and state caching. Thin.
- **Entity modules** (`sensor.py`, `switch.py`, `number.py`, `select.py`, `button.py`, `lawn_mower.py`) — each reads from the coordinator and exposes the entities for one HA platform. No protocol knowledge.

Existing upstream files for unrelated models, Mi auth paths, and vacuum-specific entity classes are removed in an early cleanup commit.

## Development workflow

The HA server is HAOS 2026.4.2 at `10.0.0.30`. SSH via `sshpass` into the `core-ssh` addon container gives read-write access to `/config/`, `git`, `python`, `vim/nano`, and the `ha` CLI (core restart, core logs, core info). No `docker`/`systemctl`, but none is needed.

Single-Claude workflow, all driven from `/data/claude/homeassistant/`:

1. Author in the local clone of the fork.
2. Run protocol unit tests here against `.jsonl` probe-log fixtures. No HA required for this loop.
3. For integration testing: `git push` → SSH to HA, `git pull` in `/config/custom_components/dreame_a2_mower/` → `ha core restart` → tail `ha core logs`.
4. Keep `dreame_mower` (upstream) installed in parallel for A/B comparison.

The `.jsonl` probe logs in `/data/claude/homeassistant/` become the test-fixture corpus. A replay harness reads them and drives the protocol modules end-to-end without a running mower — this catches 80% of bugs before HA round-trips are needed.

Diagnostic tools (`probe_a2.py`, `probe_a2_mqtt.py`, `probe_a2_analyze.py`) stay external to the module. They are research tools, not integration code, and mixing them would bloat the HACS payload.

## Phase 1 scope: property mapping + telemetry

This spec covers Phase 1 only. Later phases (live map overlay, config entity completeness, post-mow `s6p1` MAP_DATA processing, obstacle photos) each get their own design cycle.

Phase 1 delivers:

- Clean fork with renamed domain, scope stripped to g2408-only.
- MQTT-first dispatcher.
- `s1p4` telemetry decoded into position (charger-relative mm), phase (edge / transit / mowing / returning), session area mowed, session distance. Battery and dock state come from their own siid/piid, not `s1p4`.
- `s1p53` obstacle flag as a binary sensor.
- `s2p51` decoder covering the settings confirmed in the reverse-engineering findings (DnD, Low-Speed Nighttime, Navigation Path, Charging config, Auto Recharge Standby, LED Period, Anti-Theft, Child Lock, Rain Protection, Frost Protection, AI Obstacle Photos, Human Presence Alert).
- Corrected state-code mapping for g2408 (`s2p2` 70/54/48/50, `s3p2` charging enum).
- Replay-harness tests driven by the existing `.jsonl` probe logs.

Not in Phase 1: live map overlay, BT-only settings, camera onboard, human-presence photos, post-mow MAP_DATA processing.

## Testing

- **Unit tests** — protocol modules tested with `.jsonl` fixtures. Run locally in the project venv; no HA dependency.
- **Replay integration tests** — the replay harness feeds full probe-log sessions through the coordinator with a mock MQTT client, verifying the entity state transitions match the app's observed behavior (session start → MOWING → low-battery RETURN → CHARGING).
- **Live HA smoke tests** — after deploy, a short checklist: config flow completes, entities populate, a manual mow start/stop round-trips, `s1p4` updates flow to the telemetry sensors. Run against the live mower.

No mocking of the cloud auth endpoints for Phase 1; login is exercised against the real Dreame cloud.

## Risks

- **Dreame cloud auth token invalidation.** Running the upstream `dreame_mower` and the new `dreame_a2_mower` side-by-side uses the same account. Dreame's auth may invalidate the older session when a newer login happens. Mitigation: use separate Dreame accounts if available, or accept occasional re-auth on one integration during development.
- **`home-assistant/brands`.** The fork needs a brand-repo PR for the logo/name to render in the HA UI. Minor, but required before a polished release.
- **HA version drift.** Development targets 2026.4.2. Upstream API deprecations across minor versions are common — pin dev to the running version and bump deliberately.
- **Probe-log fixture coverage.** The `.jsonl` corpus covers two mowing sessions. Edge cases outside those sessions (rain interrupt, manual override mid-mow, LiDAR recovery, etc.) are not in the fixtures and will only surface in live testing.

## Deferred for later phases

- Live mowing map with position, trail, obstacles, and heading (Phase 2).
- Charger absolute-position calibration (Phase 2 prerequisite).
- `s6p1` MAP_DATA decoding and post-mow map updates (Phase 2).
- Full settings coverage for BT-only parameters (Phase 3, if a BT transport is added).
- Onboard camera live view (Phase 4).
- Human-presence detection photos from cloud push (Phase 4).
