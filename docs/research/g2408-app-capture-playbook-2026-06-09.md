# Dreame A2 (`g2408`) — App-capture playbook (2026-06-09)

> **Status — TIMELINE DOC, NOT CURRENT TRUTH.** Each topic's *"Quick answer"* line at the top is the current reading. Everything below it is **historical: hypotheses, deprecated readings, dated findings.** Don't cite a paragraph from the timeline as authoritative — verify against the appropriate live-verified doc first:
>
> - Per-entity read/write paths → **`custom_components/dreame_a2_mower/entity-inventory.yaml`** (the matrix it replaced is archived in OLD/)
> - Per-slot semantic / structure → **`inventory/generated/g2408-canonical.md`**
> - Cloud transport / endpoints / response codes → **`cloud-write-reference.md`**
> - Architecture overview → **`g2408-protocol.md`**
> - Wire-capture evidence → **`wire-captures/*.md`**
>
> The journal exists for traceability ("how did we figure this out?", "why was the old reading wrong?") and to keep deprecated hypotheses *visible but clearly labelled* so future contributors don't accidentally restate them. **A claim being in this doc does not mean it is currently true.**

---

## Purpose

This is the running shopping list of in-app actions for the next Mac MITM capture
session (rig at `/Users/ok/dreame-mitm/`). The 2026-06-08/09 session captured
reads, the spot-mow `o=103` write, and two CFG writes (`PRE` ON-state, `TIME`),
but did **not** capture: schedule writes, the EdgeMaster OFF/ON diff, the full
TASK opcode set, real-mow obstacle photos, or patrol photos. This playbook is the
deliberate, ordered list of app actions to close those gaps so the next session is
a checklist rather than improvisation. **The capture is ongoing** — close items as
they land and add new gaps as they appear.

**Results of the 2026-06-09 session** (the one this playbook was written for) are
condensed in `docs/research/wire-captures/app-settings-sweep-2026-06-09.md`.

Cross-links: extends `docs/research/g2408-capture-procedures.md` (general
how-to); each entry references the `inventory.yaml open_questions` ID it closes.

---

## Entry-format key

| Column | Meaning |
|---|---|
| **Need** | What we don't know |
| **App action** | The exact thing to do in the app |
| **Expected wire** | Host / method / `t`-key / `o`-opcode to grep for |
| **Unblocks** | The Phase 2 item this enables |
| **Closes** | `inventory.yaml` open-question ID (t-key like `MPOS`/`AIOBS` for read-key gaps; string-prefixed token like `pre-layout` for gaps inside multi-purpose entries; `open_questions` are plain strings in this inventory, not `{id,text}`) |

---

## Tier 1 — closeable from the HA box (no Mac rig)

These are **reads** the integration can already issue via its routed-`get` path
(`tools/probes/read_key_probe.py`). Listed here so we don't block on MITM for
things we can read today.

| Need | Probe (`m:"g"` `t:`) | Expected wire | Unblocks | Closes |
|---|---|---|---|---|
| `MPOS` live-position response shape (MQTT-down fallback) | `MPOS` | `{"m":"g","t":"MPOS","d":null}` → position blob [UNKNOWN — to capture] | Live-position fallback path | `mpos-decode` |
| `PRE`/`PREI` live array vs our 10-elem builder | `PRE`, `PREI` | `{"m":"g","t":"PREI","d":null}` → array shape [UNKNOWN — to capture] | PRE layout validation | `PREI` + token `pre-layout` |
| `AIOBS` shape (is this the photo index?) | `AIOBS` | `{"m":"g","t":"AIOBS","d":null}` → shape TBD [UNKNOWN — to capture] | Photo-index durable path | `AIOBS` + token `aiobs-photo-index` |
| `RGBPSTA` LED state | `RGBPSTA` | `{"m":"g","t":"RGBPSTA","d":null}` → LED state blob [UNKNOWN — to capture] | LED-state entity | `RGBPSTA` + token `rgbpsta-decode` |
| `MITRC` paging `{idx,size}` semantics | `MITRC` | `{"m":"g","t":"MITRC","d":{"idx":0,"size":10}}` → paginated blob [UNKNOWN — to capture] | History/track pagination | `MITRC` + token `mitrc-decode` |
| `SCHDTV3` GET shape (vs our SCHEDULE CFG blob) | `SCHDTV3` | `{"m":"g","t":"SCHDTV3","d":null}` → schedule list blob [UNKNOWN — to capture] | Schedule read | `SCHDTV3` + token `schdtv3-shape` |

Closes by row:
- Row 1 — **Closes** `mpos-decode`
- Row 2 — **Closes** `PREI` + token `pre-layout`
- Row 3 — **Closes** `AIOBS` + token `aiobs-photo-index`
- Row 4 — **Closes** `RGBPSTA` + token `rgbpsta-decode`
- Row 5 — **Closes** `MITRC` + token `mitrc-decode`
- Row 6 — **Closes** `SCHDTV3` + token `schdtv3-shape`

> If any read returns a pre-signed photo URL set, it also closes the
> `aiobs-photo-index` gap in Tier 2 §4.6.

---

## Tier 2 — needs the Mac app-MITM (writes / app-only flows)

All control writes ride `:13267/dreame-iot-com-10000/device/sendCommand` as
`action(siid:2, aiid:50)` with inner envelope `params.in[0]` [dreame-app-implementation-guide-2026-06-09.md].
MQTT `/w/<did>/` carries the same commands toward the device; watch both.

---

### 4.1 SCHDTV3 SET — schedule write

**Need:** The write format for adding/editing/deleting a schedule (only GET seen
this session).

**App action:** Add a schedule (time, day, area), then edit it (change time/day),
then delete it — three distinct writes.

**Expected wire:** `:13267 …/device/sendCommand` `action siid:2 aiid:50`
`{"m":"s","t":"SCHDTV3","d":<schedule-blob>}` [UNKNOWN — to capture] — repeat
for edit and delete to diff the `d` field.

**Unblocks:** Phase 2 SCHDTV3 SET entity (T7 schedule deferred since
`multi_map_phase2`).

**Closes:** token `schdtv3-set`

---

### 4.2 PRE OFF→ON diff + full layout (EdgeMaster bit + height + direction)

**Need:** Only the EdgeMaster-ON state of PRE was captured this session
(`d:[0,0,0,0,55,1,8,1,0,1,1,2,1,20,10,7,1,2,0]` [dreame-app-implementation-guide-2026-06-09.md],
19 elements). The EdgeMaster bit position and the height/direction indices need
an OFF diff to confirm.

**App action:** Toggle **EdgeMaster OFF**, capture the PRE write; toggle
**EdgeMaster ON**, capture; then change **mowing height** one step and capture;
then change **mowing direction** and capture.

**Expected wire:** Repeated `{"m":"s","t":"PRE","d":[…19 elements…]}`
[UNKNOWN — to capture] — diff the arrays to pin the EdgeMaster bit(s), height
index (`d[4]` hypothesis from `iobroker_write_paths`), and direction index.

**Unblocks:** PRE-write entities for EdgeMaster, height, direction; resolves the
19-vs-10 layout discrepancy.

**Closes:** tokens `pre-layout`, `pre-edgemaster-bit`

---

### 4.3 TASK variants — full opcode + param set

**Need:** Spot `o=103` is confirmed [dreame-app-implementation-guide-2026-06-09.md].
All-areas `o=100`, edge `o=101`, zone `o=102`, and the pause/resume/dock/stop
opcodes are from integration memory — not yet observed from the app relay.

**App action:** Start **all-areas mow**, **edge mow**, **zone (multi-zone) mow**;
then from a running state: **pause**, **resume**, **return-to-dock**, **stop** —
each from a clean state with the relay up.

**Expected wire:**
`{"m":"a","p":0,"o":<100|101|102|pause-opcode|resume-opcode|6|stop-opcode>,"d":…}`
[UNKNOWN — to capture] — compare `d` params to our `o=100/101/102/103` builders
in `mower/actions.py`.

**Unblocks:** Phase 2 TASK-variant confirmation; provides ground-truth for
`mower/actions.py` task builder.

**Closes:** token `task-variant-params`

---

### 4.4 Real-mow obstacle photos (transient, live-map icons)

**Need:** The session had no real mow with physical obstacles. The obstacle-marker
+ per-obstacle photo index API (the "normal obstacle" calls absent from this
capture) is unknown.

**App action:** Run a **real mow** in an area with physical obstacles the mower
must mark; while running, **tap an obstacle icon** on the live map to open its
photo.

**Expected wire:** The obstacle-marker event + per-obstacle photo index call
[UNKNOWN — to capture]; likely a `sendCommand` read (`m:"g"`, `t:` TBD) or an
MQTT `/status/<did>/…` PUBLISH carrying pre-signed photo URLs.

**Unblocks:** Phase 2 transient session-obstacle photos.

**Closes:** token `transient-obstacle-photo-api`

---

### 4.5 Patrol photos

**Need:** Point patrol and edge patrol photo flows were not exercised this
session. Bucket path for patrol photos is unknown (may differ from AI-obstacle
album).

**App action:** Run a **point patrol** (`o=107` [UNKNOWN — to capture]) and an
**edge patrol** (`o=108` [UNKNOWN — to capture]); open the resulting photos from
the album.

**Expected wire:** Patrol-photo trigger (the `o=107`/`o=108` side-effects) +
confirmation that patrol photos land in the same
`dreame-eu.oss-eu-central-1.aliyuncs.com/oss/media/000000/oss/<uid>/<did>/ali_dreame/<ts>.jpg`
album bucket as AI-obstacle photos [dreame-app-implementation-guide-2026-06-09.md].

**Unblocks:** Confirms album coverage for the patrol-photo surface.

**Closes:** token `patrol-photo-bucket`

---

### 4.6 The pre-signed photo-index call

**Need:** The session captured 31 photo fetches from `dreame-eu` OSS
[dreame-app-https-findings-2026-06-08.md] but the index call that returns the
signed URL set was **not seen** over HTTPS — it did not traverse the `:443`
proxy. The app likely uses `sendCommand` `t:"AIOBS"` or an MQTT status push.

**App action:** Open the **album page** with both relays active (`:13267`
reverse-proxy + `:19973` socat relay); trigger an AI/person detection.

**Expected wire:** Watch `:13267 sendCommand` (`t:"AIOBS"` or photo-list read)
**and** MQTT `/status/<did>/…`/`/w/<did>/` PUBLISH frames [UNKNOWN — to capture].

**Unblocks:** A durable "list my photos" path (vs reconstructing keys from
`photo_list` in the summary blob).

**Closes:** entry `AIOBS` + token `aiobs-photo-index`

---

### 4.7 CFG writes via app (path confirmation)

**Need:** Only `PRE` and `TIME` writes were captured this session. The write path
for the remaining CFG keys is inferred by analogy — confirm the exact `t`-key and
`d`-shape for each.

**App action:** Change **mowing height** (results in a PRE write — use as a
cross-check), **LED (`RGBPSTA`)**, a **notification toggle**, **rain protection**,
**DND** — one at a time with the `:13267` relay up.

**Expected wire:** `{"m":"s","t":"<KEY>","d":…}` [UNKNOWN — to capture] via
`sendCommand` — confirm the app uses the same endpoint that returns `code:0`
(the cleaner path vs the 80001-prone route observed in `reference_app_api_probe`).

**Unblocks:** Validates the "cleaner write path" reframe; enables gating each CFG
key on the confirmed payload shape rather than the ioBroker-inferred layout.

**Closes:** token `cfg-write-path`

---

### 4.8 Dense LiDAR scan source — CONDITIONAL

**Need:** The app fetches a full 153k-point PCD from
`dreame-eu.oss-eu-central-1.aliyuncs.com/iot/mapbin/…/<did>_<n>.0550.bin`
[dreame-app-https-findings-2026-06-08.md]. Whether the integration's
`list_3dmap_objects()` already covers this path is unknown — test first.

**Condition:** Only pursue if `tools/probes/lidar_parity_probe.py` confirms a
parity gap between what the integration fetches and the OSS PCD the app fetched.

**App action:** Open the **3D map / LiDAR viewer**; if the app shows a denser
scan than the integration's current data, capture the fetch.

**Expected wire:** The OSS `iot/mapbin/…` GET [dreame-app-https-findings-2026-06-08.md]
(object name + date) and any `sendCommand` `m:"g"` that lists it
[UNKNOWN — to capture] — compare to our `list_3dmap_objects()` result.

**Unblocks:** Phase 2 dense-scan reachability (per `op10_3dmap_negative`).

**Closes:** token `lidar-dense-source` *(only if §3.4 confirms a parity gap)*

---

## Parked — record, do not chase

These items may appear in the capture log; note the wire for traceability but do
not open Phase 2 items for them.

- **TIME write** — `{"m":"s","t":"TIME","d":{"tz":"Europe/Berlin","time":"<unixs>"}}`
  [dreame-app-implementation-guide-2026-06-09.md] — sets device clock/timezone.
  Conflicts with `project_g2408_app_only_settings` (timezone treated as an
  app-only preference with no integration surface). Record the wire; do not build
  a TIME entity.

- **Meari `video_tx` live camera** — rides
  `:13267/smart-app/meari-cloud/redirectAndLogin`
  [dreame-app-implementation-guide-2026-06-09.md]. A large separate IPC surface
  (Meari cloud). Scope-flag only; not part of this effort.

- **Backend C (Aliyun Link) adoption** — the integration stays on backend A
  (miio/`sendCommand`); the Aliyun auth bridge is documented in the transport map
  but not adopted. Record any new Aliyun endpoint paths; do not port auth.

---

## Artifact conventions

| Artifact | Path on rig | Notes |
|---|---|---|
| Rig root | `/Users/ok/dreame-mitm/` | Off-repo; `scripts/start-session.sh` |
| `:13267` control log | `logs/miio-13267.jsonl` + `logs/flows.mitm` | mitmproxy reverse-proxy; all sendCommand bodies |
| All-hosts HTTPS | `logs/api-calls.jsonl` + `logs/flows.mitm` | Lossless archive; replay via `mitmweb --rfile` |
| MQTT relay log | `relay/mqtt.log` | socat TLS relay on `:19973`; MQTT frames in hex |
| MQTT parser | `scripts/parse-mqtt.py` | Reads `data.method`/`data.params`; action params nested at `params.in[]` |
| Photo samples | `logs/photos/` | Stay off-repo — privacy (real property + person shots) |
| Map samples | `logs/maps/` | Stay off-repo — `full_*.bin` PCD blobs |

---

## Closure protocol

After each capture session:

1. Write the decoded wire into `inventory.yaml`: advance the entry status from
   `partial` → `confirmed` (or `hypothesized` → `partial`).
2. Close the matching `open_questions` ID: update the entry's `open_questions`
   list (remove the closed token or mark it answered) and promote the
   verification status.
3. Journal the finding in `docs/research/g2408-research-journal.md` with the date
   and a "Quick answer" update at the top of the relevant topic cluster.
4. The matching Phase 2 item is then buildable — open the implementation task.

> Corpus-validate: never confirm a wire claim from one run; check across all
> available probe logs (`/data/claude/homeassistant/probe/logs/probe_log_*.jsonl`)
> before promoting to `confirmed` (per `feedback_corpus_validate_protocol_claims`).
