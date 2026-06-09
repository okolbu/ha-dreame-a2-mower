# App-capture knowledge → docs + integration — design (Spec A)

**Date:** 2026-06-09
**Status:** Design — pending review
**Topic:** Fold the 2026-06-08/09 live app-MITM findings into the docs and
inventory, and implement the integration support that is *fully known* now;
record (but defer) the support that is *not yet fully known* pending further
capture (see the companion Spec B, the capture playbook).

**Source evidence:**
- `/data/claude/homeassistant/dreame-app-https-findings-2026-06-08.md`
- `/data/claude/homeassistant/dreame-app-implementation-guide-2026-06-09.md`

Both are a live, fully-decrypted capture of `com.dreame.smartlife 2.5.6.4`
driving the real online g2408 (EU account `BM169439`, did `-112293549`), via
mitmproxy (`:443`) + a `:13267` reverse-proxy + a `:19973` socat TLS relay.

---

## 1. Why this exists

An external capture session resolved several long-standing blanks and
**contradicted** some shipped docs. The headline corrections:

1. **Obstacle/AI photos are reachable.** Our docs (`s2p55`, `summary_photo_list`,
   `project_g2408_ai_photo_probe`) concluded photos were app-backend-only and
   unreachable. In fact they live in the **same `dreame-eu.oss-eu-central-1`
   OSS bucket the integration already fetches LiDAR PCD from**, at key
   `oss/media/000000/oss/<uid>/<did>/ali_dreame/<unix_ts>[_person].jpg`, and the
   `photo_list:[...]` leaves in the `.0550.json` session summary map 1:1 to
   them. The signing/fetch plumbing already exists in `cloud_client/_oss.py`.
2. **Backend "B" identity was wrong.** It is `eu.iot.dreame.tech:13267`
   (HTTP/TLS), **not** `app.dreame.tech`; backend A and B are the **same
   host:port**, and `POST …/dreame-iot-com-10000/device/sendCommand` is the
   shared control relay. It returns `code:0` online — the `80001` we attributed
   to the RPC path is **asleep/slow-prop-specific**, not inherent.
3. **The control envelope is corroborated live.** Spot mow =
   `action(siid:2,aiid:50)` `{"m":"a","p":0,"o":103,"d":{"area":[1]}}` → `code:0`.
   Matches `project_g2408_task_envelopes_verified`.
4. **A new routed `t`-key read vocabulary** is visible:
   `DEV DOCK MPOS MAPI MAPL MISTA OBS AIOBS PREI RGBPSTA SCHDTV3 REMOTE IOT CFG
   MITRC`. Several are reads the integration can issue **today** via its
   existing routed-`get` path.
5. **PRE is writable by the app** via `{"m":"s","t":"PRE","d":[…19…]}` with
   `d[4]=55`=mowing height (5.5 cm) — but only the **ON-state** array was
   captured, and it is **19 elements** where our integration builds a
   **10-element** PRE with height at index 2. This is unresolved → Phase 2.

**Scope discipline (per `feedback_corpus_validate_protocol_claims`):** every
wire claim below is *app-observed truth*, not yet validated on our own client.
Phase 1 ships only what we can verify on the live mower from this box; Phase 1
also **documents every partial finding** (including the deferred ones) so no
knowledge is lost while we wait for more capture.

---

## 2. Architecture / where things land

This work touches three layers, each with an established home:

| Layer | Artifact | What changes |
|---|---|---|
| **Protocol SoT** | `custom_components/dreame_a2_mower/inventory.yaml` | `t`-key vocab entries, PRE partial sample, photo key-layout correction, backend/transport notes; `verifications` + `open_questions` |
| **Reference docs** | `docs/research/{app-api-surface-2026-05-25,cloud-write-reference,g2408-protocol}.md`, `docs/research/knowledge-gaps.md`, `docs/research/g2408-research-journal.md`, `docs/data-policy.md` | Corrections + dated journal entry + privacy note |
| **Integration code** | `cloud_client/_oss.py`, a new photo archive + camera entity, `tools/probes/`, plus a LiDAR-parity probe | Album photos feature; read-probe tool; LiDAR fetch-parity investigation |

Memories to update on completion: `project_g2408_ai_photo_probe` (resolved),
backend-B identity, `project_g2408_op10_3dmap_negative` (lidar parity result).

---

## 3. Phase 1 — fully known, build + verify now

### 3.1 Doc reconciliation (the spine — records *all* knowledge)

This is one deliverable that captures both the known facts **and** the partial
findings for the deferred items, so Phase 2 starts from a written baseline.

- **`app-api-surface-2026-05-25.md`** — correct backend B to
  `eu.iot.dreame.tech:13267`; note A/B share host:port and `sendCommand` is the
  shared relay returning `code:0` online; add the `:13267` endpoint catalog and
  the auth bridge (`getAuthCodeV3` → `api.link.aliyun.com/living/account/region/
  get` → Aliyun Link session). Mark the doc's "app doesn't use backend A" claim
  as superseded.
- **`cloud-write-reference.md`** — add the live `device/sendCommand` outer/inner
  envelope, the `aiid:50` multiplex (`{m,t,d}` get/set vs `{m,p,o,d}` action),
  spot `o=103 d:{area:[1]}` live-confirmation, and reframe the `80001` semantics
  (asleep/slow-prop, not RPC-inherent). Bump "last-verified" date.
- **`inventory.yaml`** —
  - Add the routed `t`-key vocabulary as entries with confidence + per-key
    `open_questions` (response/decode unknown for `MPOS MAPI MAPL OBS AIOBS PREI
    RGBPSTA MITRC SCHDTV3`).
  - Record the **PRE 19-element ON-state sample** verbatim
    (`[0,0,0,0,55,1,8,1,0,1,1,2,1,20,10,7,1,2,0]`, `d[4]=55`=height; ioBroker
    index hints) as a `partial`/`hypothesized` verification with an
    `open_questions` entry: "OFF/ON diff to locate EdgeMaster bit; reconcile
    19-elem app layout vs our 10-elem builder; confirm `m:s t:PRE` returns
    `code:0` on our client."
  - Correct the **photos** entries (`s2p55`, `summary_photo_list`): photos ARE
    reachable; record the key layout `oss/media/000000/oss/<uid>/<did>/
    ali_dreame/<ts>[_person].jpg`, the `_person` person-detection variant, and
    that the album = Patrol + AI-obstacle photos merged. Add an `open_questions`
    for the **transient session-obstacle photos** (different API, uncaptured).
- **`knowledge-gaps.md`** — regenerate from inventory (`inventory_gen.py`); the
  new `open_questions` flow through automatically.
- **`g2408-research-journal.md`** — dated 2026-06-09 entry summarising the
  capture, the corrections, and the partial/deferred findings, with a pointer to
  Spec B.
- **`data-policy.md` / privacy** — album photos contain images of the property
  and **people** (`_person` shots). Local archive only; never committed; treat
  bucket paths + saved frames as sensitive (cf. existing privacy memory).

### 3.2 Album photos (Patrol + AI-obstacle) — feature

The two photo systems the app merges into its "album page" — the
`<ts>[_person].jpg` objects present in this capture.

- **Key builder** — from a session summary's `photo_list` leaves, build object
  keys `oss/media/000000/oss/<uid>/<did>/ali_dreame/<name>`. NOT the summary
  layout, NOT the 479D Xiaomi-FDS bucket. Sign via the existing
  `get_interim_file_url`/`getDownloadUrl` (region `eu-central-1`); fetch via
  existing `get_file`. Captured signed URLs are `Expires`-limited → always
  reconstruct + re-sign, never replay.
- **Disk archive** — mirror `archive/lidar.py`: content-addressed, retention
  cap, dedup. Never committed; respects the privacy note above.
- **HA surface** — a **"latest AI/patrol photo" camera entity**, plus a separate
  **"latest person-detection" camera entity** keyed off the `_person` filename
  suffix (the only discriminator the list exposes — the app itself only
  distinguishes type on the photo, not in the list). Use the established
  camera-proxy + **access_token-rotation refresh pattern**
  (`feedback_camera_image_refresh_pattern`: broadcast → await render →
  broadcast again) so the browser doesn't serve a stale cached frame.
- **Out of scope for Phase 1:** the live pre-signed *photo index call* (the app
  obtains the album URL set off-HTTPS — likely an `AIOBS`/photo read or MQTT
  event). We don't need it: `photo_list` from the summary gives the filenames
  and we reconstruct+sign ourselves. Pinning the index call is a Spec B item.

### 3.3 Read-probe tool (`tools/probes/`)

A dev-box-only, idempotent probe that issues routed-`get`
(`action siid:2 aiid:50 {"m":"g","t":"<KEY>","d":<args>}`) for
`MPOS PREI AIOBS RGBPSTA MITRC SCHDTV3 PRE …` against the live mower and
**pretty-prints the raw responses inline with timestamps**
(`feedback_inline_logging`). This captures decode material **without the Mac
rig** and is the primary feed for Phase 2 decode work. It also issues a PRE
read (`m:"g" t:"PRE"`/`PREI`) so we can compare the live array to our builder.

### 3.4 LiDAR fetch-parity investigation

The app renders a **newer / denser** LiDAR scan than what the integration shows.
Determine whether we fetch the same object the app does.

- Diff our `list_3dmap_objects()` → `get_interim_file_url()` result against the
  app's captured sample (`<did>_154157120.0550.bin`, 153,261 points, dated
  `2026/04/20`, key `iot/mapbin/000000/ali_dreame/<YYYY/MM/DD>/<uid>/…`):
  object name, capture date, point count.
- Determine whether the OBJ-list is handing us a **stale/sparser** object (fix:
  ordering/recency selection) or whether the dense scan lives on a **surface we
  don't reach** (the `op10_3dmap_negative` "live dense LiDAR" — then it becomes a
  Phase 2 item + a Spec B capture target).
- Deliverable: a finding (parity confirmed, or a concrete code fix, or a
  documented Phase 2/Spec B item) + a journal/memory update.

### 3.5 sendCommand / 80001 verification

Confirm `cloud_client/_rpc.py` already targets the app's
`device/sendCommand` shape; re-document when `80001` actually fires (asleep /
slow-prop) vs `code:0`. Doc + diagnostic only — no feature change unless the
verification surfaces a cheap reliability win.

---

## 4. Phase 2 — deferred until more capture lands (documented now)

Built later, when Spec B's captures arrive. Partial knowledge for each is
written into `inventory.yaml`/docs in Phase 1 §3.1.

- **PRE-write entities** — wire EdgeMaster + mowing-height as writable
  read-modify-write `m:"s" t:"PRE"` switches/numbers, once the OFF/ON diff
  locates the edge bit(s), the 19-element layout is mapped, and `code:0` is
  confirmed on our client. (Unblocked by Spec B §PRE.)
- **Transient session-obstacle photos** — the live-map clickable-icon photos
  that go dead after a session; needs the obstacle-photo index/marker API,
  uncaptured because no real mow ran. (Unblocked by Spec B §real-mow.)
- **SCHDTV3 SET** — schedule write format (only GET seen). (Unblocked by Spec B.)
- **TASK variant params** — all-areas/edge/zone/pause/resume/dock/stop opcode +
  param confirmation against our `o=100/101/102/…` builders. (Unblocked by Spec B.)
- **New read-key entities** — decode + surface `MPOS` (live-position MQTT-down
  fallback), `MITRC` (paged history/track), `RGBPSTA` (LED state), `AIOBS`
  (photo index), once §3.3 captures their response shapes.

---

## 5. Components & isolation

| Unit | Purpose | Depends on |
|---|---|---|
| Doc reconciliation | Record all known + partial findings in SoT/docs | inventory schema, `inventory_gen.py` |
| `photo` key builder | summary `photo_list` → signed OSS key | `_oss.py` signing |
| `archive/photos.py` | local content-addressed photo store | mirrors `archive/lidar.py` |
| photo camera entity(ies) | HA surface, token-rotation refresh | camera-proxy, archive |
| `tools/probes/read_probe.py` | issue routed-gets, log raw responses | `cloud_client` routed-get |
| LiDAR-parity probe | diff our PCD vs app sample | `_oss.py`, `protocol/pcd.py` |

Each is independently testable; the photo feature is the only user-facing
addition in Phase 1.

---

## 6. Testing & verification

- **Doc/inventory:** CI inventory-schema + wire-census gates must stay green
  (`inventory_gen.py --validate-only`); decoded-status vocab kept in sync.
- **Photos:** unit-test the key builder against the captured `photo_list`
  fixture; live-verify by fetching a real album photo end-to-end on the box and
  confirming the camera entity rotates its access_token (browser hard-refresh).
- **Read-probe / LiDAR-parity:** run live against the mower; capture raw output;
  no asserts beyond "got `code:0` + non-empty body" — these are discovery tools.
- **No silent caps:** if the album fetch bounds count/age, `log()` what's dropped.

---

## 7. Out of scope

- **TIME write** (`{m:"s",t:"TIME",d:{tz,time}}`) — conflicts with
  `project_g2408_app_only_settings`; record in Spec B, do not chase.
- **Meari `video_tx` live camera** — a large separate surface
  (`smart-app/meari-cloud/redirectAndLogin`); scope-flag only.
- **Aliyun Link (backend C) auth path** — the integration stays on backend A;
  documented for completeness, not adopted.
