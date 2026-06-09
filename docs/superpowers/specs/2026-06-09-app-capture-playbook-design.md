# Missing-knowledge capture playbook — design (Spec B)

**Date:** 2026-06-09
**Status:** Design — pending review
**Topic:** The list of knowledge still missing after the 2026-06-08/09 app-MITM
session, expressed as **exact in-app actions to perform on the next capture
run**, each mapped to the wire it should reveal and the Spec A Phase 2 item it
unblocks. Companion to `2026-06-09-app-capture-knowledge-design.md` (Spec A).

**Audience:** the instance running the Mac capture rig
(`/Users/ok/dreame-mitm/`) — emulator + mitmproxy `:443` + `:13267`
reverse-proxy + `:19973` socat TLS relay + guest iptables DNAT. Output lands in
`logs/miio-13267.jsonl`, `logs/api-calls.jsonl`, `relay/mqtt.log`; parser
`scripts/parse-mqtt.py`. **The capture is ongoing** — this playbook is the
running shopping list; close items as they land and add new gaps as they appear.

---

## 1. Why this exists

The 2026-06-08/09 session captured reads, the spot-mow `o=103` write, and two
CFG writes (`PRE` ON-state, `TIME`). It did **not** capture: schedule writes,
the EdgeMaster OFF/ON diff, the full TASK opcode set, real-mow obstacle photos,
or patrol photos — because no real mow/patrol ran and only one PRE state was
toggled. This doc is the deliberate, ordered list of app actions to close those
gaps, so the next session is a checklist rather than improvisation.

Cross-links: extends `docs/research/g2408-capture-procedures.md` (the general
capture how-to); each entry references the `inventory.yaml open_questions` ID it
closes (created in Spec A §3.1).

---

## 2. Format of each entry

> **Need** — what we don't know.
> **App action** — the exact thing to do in the app.
> **Expected wire** — host / method / `t`-key / `o`-opcode to grep for.
> **Unblocks** — the Spec A Phase 2 item.
> **Closes** — `inventory.yaml` open-question ID.

---

## 3. Tier 1 — closeable from the HA box (no Mac rig)

These are **reads** the integration can already issue via its routed-`get` path,
so they go to Spec A §3.3's read-probe tool, **not** the Mac session. Listed here
so we don't block on MITM for things we can read today.

| Need | Probe (`m:"g" t:`) | Closes |
|---|---|---|
| `MPOS` live-position response shape (MQTT-down fallback) | `MPOS` | mpos-decode |
| `PRE`/`PREI` live array vs our 10-elem builder | `PRE`, `PREI` | pre-layout |
| `AIOBS` shape (is this the photo index?) | `AIOBS` | aiobs-photo-index |
| `RGBPSTA` LED state | `RGBPSTA` | rgbpsta-decode |
| `MITRC` paging `{idx,size}` semantics | `MITRC` | mitrc-decode |
| `SCHDTV3` GET shape (vs our SCHEDULE CFG blob) | `SCHDTV3` | schdtv3-shape |

If any read returns the pre-signed photo URL set, it also closes the
photo-index gap below.

---

## 4. Tier 2 — needs the Mac app-MITM (writes / app-only flows)

### 4.1 SCHDTV3 SET — schedule write
- **App action:** add a schedule, then edit it (change time/day/area), then
  delete it — three distinct writes.
- **Expected wire:** `:13267 …/device/sendCommand` `action siid:2 aiid:50`
  `{"m":"s","t":"SCHDTV3","d":<...>}`.
- **Unblocks:** Spec A P2 SCHDTV3 SET. **Closes:** schdtv3-set.

### 4.2 PRE OFF→ON diff + full layout
- **App action:** toggle **EdgeMaster OFF**, capture; toggle **ON**, capture;
  then change **mowing height** and **mowing direction** one at a time.
- **Expected wire:** repeated `{"m":"s","t":"PRE","d":[…19…]}` — diff the arrays
  to pin the edge bit(s), height index (`d[4]` hypothesis), and direction index.
- **Unblocks:** Spec A P2 PRE-write entities; resolves the 19-vs-10 layout
  discrepancy. **Closes:** pre-layout, pre-edgemaster-bit.

### 4.3 TASK variants — full opcode + param set
- **App action:** start **all-areas**, **edge**, **zone (multi-zone)**, then
  **pause**, **resume**, **return-to-dock**, **stop** — each from a clean state.
- **Expected wire:** `{"m":"a","p":0,"o":<100|101|102|pause|resume|6|stop>,"d":…}`
  — compare params to our `o=100/101/102/103` builders in `mower/actions.py`.
- **Unblocks:** Spec A P2 TASK-variant confirmation. **Closes:** task-variant-params.

### 4.4 Real-mow obstacle photos (transient, live-map icons)
- **App action:** run a **real mow** in an area with physical obstacles the
  mower must mark and route around; while running, **tap an obstacle icon** on
  the live map to open its photo.
- **Expected wire:** the obstacle-marker + per-obstacle photo index API (the
  "normal obstacle" calls absent from this capture); likely a `sendCommand`
  read or an MQTT status event carrying pre-signed photo URLs.
- **Unblocks:** Spec A P2 transient session-obstacle photos. **Closes:**
  transient-obstacle-photo-api.

### 4.5 Patrol photos
- **App action:** run a **point patrol** and an **edge patrol**; open the
  resulting photos from the album.
- **Expected wire:** patrol-photo trigger (`o=107`/`o=108` side effects) +
  confirmation that patrol photos land in the same `ali_dreame/<ts>.jpg` album
  bucket as AI-obstacle photos.
- **Unblocks:** confirms Spec A §3.2 album coverage. **Closes:** patrol-photo-bucket.

### 4.6 The pre-signed photo-index call
- **App action:** open the **album page**; trigger an AI/person detection.
- **Expected wire:** the call returning the album's pre-signed URL set — watch
  `:13267` `sendCommand` (`t:"AIOBS"`/photo read) **and** MQTT
  `/status/…`/`/w/…` PUBLISH frames.
- **Unblocks:** a durable "list my photos" path (vs reconstructing from
  `photo_list`). **Closes:** aiobs-photo-index.

### 4.7 CFG writes via app (path confirmation)
- **App action:** change **mowing height**, **LED (`RGBPSTA`)**, a
  **notification toggle**, **rain protection**, **DND** — one at a time.
- **Expected wire:** `{"m":"s","t":"<KEY>","d":…}` via `sendCommand` — confirm
  the app uses the same path that returns `code:0` (cleaner than our
  80001-prone route per `reference_app_api_probe`).
- **Unblocks:** validates the "cleaner write path" reframe in Spec A §3.5.
  **Closes:** cfg-write-path.

### 4.8 Dense LiDAR scan source (if Spec A §3.4 finds a gap)
- **App action:** open the **3D map / LiDAR viewer**; if the app shows a denser
  scan than the integration, capture the fetch.
- **Expected wire:** the OSS `iot/mapbin/…` GET the app issues (object name +
  date) and any `sendCommand` `m:"g"` that lists it — compare to our
  `list_3dmap_objects()` result.
- **Unblocks:** Spec A §3.4 / P2 dense-scan reachability. **Closes:**
  lidar-dense-source. *(Only if §3.4 confirms a parity gap.)*

---

## 5. Parked — record, do not chase

- **TIME write** (`{"m":"s","t":"TIME","d":{"tz","time"}}`) — sets device
  clock/tz; conflicts with `project_g2408_app_only_settings` (timezone treated
  as an app-only preference). Record the wire; no integration surface.
- **Meari `video_tx` live camera** — `smart-app/meari-cloud/redirectAndLogin`;
  a large separate IPC surface. Scope-flag only; not part of this effort.
- **Backend C (Aliyun Link) adoption** — the integration stays on backend A;
  the auth bridge is documented in Spec A, not adopted.

---

## 6. Artifact + reproduction conventions

- Rig: `/Users/ok/dreame-mitm/` (`scripts/start-session.sh`), off-repo.
- HTTP/TLS control: `logs/miio-13267.jsonl` (+ `.mitm`).
- All-hosts HTTPS: `logs/api-calls.jsonl`; lossless `logs/flows.mitm`.
- MQTT: `relay/mqtt.log`; parser `scripts/parse-mqtt.py`
  (reads `data.method`/`data.params`; action params nested at `params.in[]`).
- Media samples stay off-repo (`logs/photos/`, `logs/maps/`) — privacy.
- After each capture: write the decoded wire into `inventory.yaml` (status
  `partial`→`confirmed`), close the matching `open_questions` ID, and note it in
  `g2408-research-journal.md`. Then the corresponding Spec A Phase 2 item is
  ready to build.
