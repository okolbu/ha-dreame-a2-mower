# Observability surface — F6

This file documents what the integration self-reports about itself.
Use it to debug or to file a clean bug report.

## Diagnostic sensors

| Entity | Default state | What |
|---|---|---|
| `sensor.dreame_a2_mower_novel_observations` | enabled | Count of unfamiliar protocol shapes seen this process. Attribute `observations` lists each: category (`property` / `value` / `event` / `key`), detail string, first-seen unix timestamp. |
| `sensor.dreame_a2_mower_data_freshness` | disabled | Age in seconds of the OLDEST tracked field. Attributes: per-field age in seconds (`{field_name}_age_s`). |
| `sensor.dreame_a2_mower_api_endpoints_supported` | disabled | Count of routed-action opcodes the cloud accepted. Attributes: `accepted`, `rejected_80001`, `error` lists by op key. |
| `sensor.dreame_a2_mower_archived_session_count` | enabled | (from F4) total archived session entries on disk. |

The disabled sensors can be enabled per-entity via Settings → Devices & Services → Dreame A2 Mower → Entities. They are off by default because the freshness map is chatty (every field change triggers an attribute update) and the endpoint log is an opt-in protocol-debugging surface.

## Log prefixes that mean something

| Prefix | Triggers when |
|---|---|
| `[NOVEL/property]` | A property push arrived for an `(siid, piid)` slot the integration doesn't recognize. Once per slot per process. |
| `[NOVEL/value]` | A property push arrived with a value the integration has never seen for a known slot. Once per `(siid, piid, value)` per process. |
| `[NOVEL_KEY/session_summary]` | The OSS session-summary JSON contained a key not in the parser's schema. Once per key per process. |

All three are emitted at WARNING level. They are gated on a process-scoped registry — a single restart re-arms every gate, so the integration re-flags drift after upgrades.

## Downloading a diagnostics dump

Settings → Devices & Services → Dreame A2 Mower → "Download Diagnostics".

The dump is built from an **allowlist** (default-deny): only fields known to be
safe for a bug report are emitted. Everything else is omitted outright, or — for
the `config_entry` section, so a reader can see credentials *were* present but
scrubbed — replaced with a `**REDACTED**` marker. Secrets, GPS coordinates,
WiFi SSID/IP, the hardware serial, and cloud/MQTT identifiers (did / uid / host /
subscribe topic) are never included.

The dump is JSON with these top-level keys:

| Key | Contents |
|---|---|
| `config_entry` | Only the safe keys (`country`, `model`) are shown; known-sensitive keys (`username`, `password`, `token`, `did`, `sn`, `mac`, `host`) become a `**REDACTED**` marker; anything else is dropped |
| `versions` | Integration + firmware version |
| `state` | An allowlisted subset of the `MowerState` snapshot — GPS, exact map/dock coordinates, and other sensitive fields are excluded, not merely redacted |
| `capabilities` | Fixed g2408 capability flags (constants, not runtime-resolved) |
| `cloud_state` | Allowlisted subset only — transport identifiers (did / uid / uuid / host) are dropped entirely |
| `mqtt_state` | Allowlisted subset only — the subscribe topic / first topics (which embed the serial) are dropped entirely |
| `entity_counts` / `archive_counts` | Counts only, never contents |
| `novel_observations` | List from the registry: `[{category, detail, first_seen_unix}]` |
| `freshness` | Per-field last-updated unix timestamps: `{field_name: ts}` |
| `endpoint_log` | Cloud-RPC accept/reject map: `{routed_action_op=N: "accepted" | "rejected_80001" | "error"}` |
| `recent_novel_log_lines` | Tail of NOVEL log lines (capped at 200) |

Attach the dump to bug reports — the allowlist keeps secrets, location, and
device/cloud identifiers out. (The gated wire-trace file below is the exception:
it is **not** pre-redacted.)

## Wire-trace instrument (gated, off by default)

A developer-facing tracing instrument for diffing the integration's outgoing
device writes against app↔mower captures. It ships OFF and adds no overhead
beyond one file-existence check per write when disabled.

- **What it captures.** Every device RPC *write* the integration sends (an
  `action` call — `routed_action` / `set_cfg` and friends) is appended as one
  JSON line: the outgoing `siid`/`aiid`/parameters plus the device's response,
  with a timestamp. See `cloud_client/_helpers.py` (`wire_trace_enabled` /
  `wire_trace`) and its call site in `cloud_client/_rpc.py`. It is a raw
  request/response capture, not a decoded interpretation — no protocol
  semantics are added by the instrument itself.
- **Not pre-redacted.** Unlike the diagnostics dump, this file is **not**
  scrubbed — the captured records can include the device id and full
  write payloads. Review the file yourself before sharing or attaching it
  anywhere; treat it the same as a raw packet capture.
- **Enable:** `touch /config/dreame_a2_wire_trace.enabled` on the HA host (no
  code change or restart required — the check is per-call).
- **Disable:** delete that same sentinel file. No writes are captured once
  it's gone.
- **Output:** appended to `/config/dreame_a2_wire_trace.jsonl`. The file
  self-rotates to a `.1` sibling once it grows past a fixed size cap, so it
  can't fill the disk if left enabled.

## Operational notes

- Registry and log buffer are process-scoped. A HA restart drops them. This is intentional — version upgrades may add new known shapes, and re-arming the novelty gates surfaces leftover drift.
- The novel-observation registry caps at 200 entries. On a chronically-misconfigured device, additional novel tokens are tracked by the underlying watchdog (so the same token still won't log twice) but won't appear in the sensor attribute list.
- Schema fingerprints live in `observability/schemas.py` as Python constants, not on disk. A drift in a config file would itself be a worse failure mode than drift in the code.
- Per-field freshness is computed from `MowerState` dataclass fields — a field is "stamped" only when its value actually changes, so a stale-but-correct field reads as old, while a noisy field that re-publishes the same value every tick stays at its first-real-change timestamp.
