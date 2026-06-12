# Live video stream + snapshot/record — implementation handoff (g2408)

**Status:** Setup chain FULLY captured (app-MITM 2026-06-09, re-confirmed 2026-06-12).
The media stream itself is Tencent XP2P **P2P/UDP, off-relay** — not capturable by the
HTTPS/MQTT rig and not needed for setup. Everything an integration needs to *establish*
a session, *snapshot/record*, and *retrieve* recordings is captured and documented here.

> ⚠️ **Inventory correction required.** `inventory.yaml` / `g2408-canonical.md` currently
> annotate the camera properties (s4p22, s4p44, s4p59, s4p83) with *"g2408 has no confirmed
> camera module."* **That is stale and wrong.** The g2408 HAS a camera: `feature:"video_tx"`,
> vendor `tx` = Tencent IoT Video; live view, two-way audio, and AI/human photos are all real
> and captured. Fix those entries when folding this in. The earlier "not IPC-enrolled
> (`videoStatus:null`, `featureCode:-1`)" note refers to the **Dreame security-camera** product
> line's `/smart-app/ipc/...` surface — a DIFFERENT path; the mower's camera uses
> `dreame-third-video/tx/*` + Tencent XP2P, documented below.

---

## 1. Architecture: two planes

- **Control plane** — Dreame cloud REST, host `eu.iot.dreame.tech:13267` (the same miio
  control endpoint the integration already uses), authed with `sign` + `timestamp`
  (+ `accesstoken` for video calls). This is what we capture and what the integration drives.
- **Media plane** — Tencent IoT-Video **XP2P** (peer-to-peer, UDP, device↔app via Tencent's
  hole-punch/relay) + **TRTC**. Carries live video, live audio, two-way "Talk" audio, and is
  the source the app frame-grabs for snapshots/recordings. **Never touches our relay.** To
  consume it you MUST drive the **Tencent IoT-Video XP2P SDK** with the creds from the control
  plane (you cannot reconstruct the stream from HTTP alone).

Lifecycle stays on the control plane: enable `o=400 {on:1}` → fetch creds → SDK opens P2P →
(optional) snapshot/record uploads → stop `o=400 {on:0}`.

---

## 2. Setup chain (exact, captured)

All on `https://eu.iot.dreame.tech:13267`, `POST`, JSON body, `Dreame-Auth` token in headers
(same as existing API calls). `sign` = the standard Dreame request HMAC over the body params
(the integration's existing signer); `timestamp` = epoch ms. Secrets masked below.

```
# 1) Video-service session token
POST /dreame-third-video/tx/user/accesstoken
  req:  {"os":"android","sign":"…","timestamp":<ms>}
  resp: {data:{data:{ token:<accesstoken>, userId:"910596097905266688", expireAt:<epoch_s> }}}

# 2) Role/eligibility gate (call before identity; cheap)
POST /dreame-third-video/tx/dev/isDevUser
  req:  {"accesstoken":<tok>,"did":"<DID>","sign":"…","timestamp":<ms>}
  resp: {data:{data:{ isDevUser:true }}}

# 3) Tencent IoT device identity (the XP2P device creds)
POST /dreame-third-video/tx/mgr/dev/getIdentity
  req:  {"did":"<DID>","os":"android","sign":"…","timestamp":<ms>}
  resp: {data:{data:{ secretId:<MASKED>, secretKey:<MASKED>,
                      deviceId:"B64XZHGZUT/I4rl99pelxmAV2zt",
                      deviceName:"I4rl99pelxmAV2zt", productId:"B64XZHGZUT" }}}

# 4) XP2P P2P connect descriptor
POST /dreame-third-video/tx/dev/getP2PInfo
  req:  {"accesstoken":<tok>,"did":"<DID>","sign":"…","timestamp":<ms>}
  resp: {data:{data:{ p2pInfo:"XP2P…%<sdkVer>" }}}     # SDK v2.4.49 seen

# 5) Enable the camera (routed action on the miio sendCommand surface, siid:2 aiid:50)
action o=400 {m:'a', o:400, d:{on:1}}     # confirmed 2026-06-09; on:0 to stop.
#   - Also fires AUTOMATICALLY at point-patrol start (patrol auto-capture needs the camera on).
#   - o=15 {c:0|1} is a SEPARATE camera toggle used during remote-control/joystick mode.

# Media/signaling hosts the SDK will contact (:443): iot.cloud.tencent.com, *.trtcube-license.cn
```

**Field notes**
- `productId` (`B64XZHGZUT`) + `deviceName`/`deviceId` are the Tencent IoT product/device under
  which the mower's camera is registered — needed to init the XP2P SDK.
- `accesstoken` from (1) is reused in (2) and (4). `expireAt` ≈ 7 days (`getP2PInfo` should be
  re-fetched per session; treat `p2pInfo` as short-lived/session-scoped).
- Ordering observed: 1→2 at app start, then 3→4 immediately before opening live view.

---

## 3. Consuming the stream (SDK-dependent — NOT in capture)

Feed into the **Tencent IoT-Video XP2P / IoTVideo P2P SDK**:
- device identity: `secretId`, `secretKey`, `deviceId`/`deviceName`, `productId` (step 3),
- the `p2pInfo` connect string (step 4).

The SDK establishes the UDP P2P channel and exposes a local interface (typically a local
proxy URL / data callbacks) the player or frame-grabber reads. Over that channel:
- **live video + audio** (the feed),
- **two-way "Talk" audio** — confirmed entirely in-stream: pressing Talk emits **NO** control
  command on the wire (the lone `VOL` write seen was an unrelated volume bump from a UI hint),
- the **source frames** the app captures for snapshot/record.

> This is the one piece you cannot do from the captured HTTP alone — it requires linking
> Tencent's SDK (or a compatible XP2P client). For HA, that's the hard part; the control-plane
> setup above is straightforward.

---

## 4. Snapshot / record while watching (client-side → OSS, fully captured)

The app grabs a frame (jpg) or clip (mp4, **60 s cap**) from the P2P stream and uploads it.
All on `eu.iot.dreame.tech:13267`, same auth.

```
# (optional) quota check
POST /dreame-user-iot/iotoss/checkDevOssStorage  {did,sign,ts}
  → {total:"209715200", used:"45898604"}          # ~200 MB cap

# 1) reserve an object + get a signed PUT URL
POST /dreame-user-iot/iotoss/addOssNew
  req:  {category:0, did, fileSize, filename:"<ms>.jpg|.mp4", model:"dreame.mower.g2408",
         source:2, type:"jpg"|"mp4"|"thumb", uid:"<ACCOUNT>", key:"<16hex>", sign, timestamp}
  resp: {data:{ ossId, url:"https://dreame-eu.oss-eu-central-1.aliyuncs.com/oss/media/000000/
                            oss/<ACCOUNT>/<DID>/ali_dreame/<ms>.jpg?Expires=…&OSSAccessKeyId=…
                            &Signature=…", expiresTime, pwd:"<…>" }}

# 2) PUT the bytes to that signed url (standard Aliyun OSS PUT)

# 3) confirm
POST /dreame-user-iot/iotoss/ossUploaded
  req:  {ossId, …same fields…, ext:"{\"duration\":N}" (mp4 only), sign, timestamp}
  → {data:"ok"}
```

- `source:2` = manual capture. `key` = a per-capture 16-hex id; for a **video**, the mp4 and its
  `thumb` share the same `key`.
- `pwd` is returned by `addOssNew` (purpose TBD — likely an object access/integrity token; not
  needed for the PUT, which is authorized by the signed URL). Worth a closer look if you hit
  access issues.
- Object path is deterministic:
  `…/oss/media/000000/oss/<ACCOUNT=BM169439>/<DID=-112293549>/ali_dreame/<unixms>.<ext>`.

---

## 5. Retrieval (existing gallery — already in cloud-write-reference patterns)

```
POST /dreame-user-iot/iotoss/userDidOssList?current=1&size=10000   {did,sign,ts}
  → {records:[{ id, type:"jpg"|"thumb", category, filepath:<PRE-SIGNED OSS GET URL>,
               fileSize, uploadTime, key, ext, videoPath }]}
```
- `type:"jpg"` = photos (incl. AI-obstacle/human + manual snapshots); `type:"thumb"` = videos,
  with `videoPath`→mp4 and `ext.duration`. **Recorded mp4s are retrievable** via the signed URL.
- This same list backs photo types 1 (patrol) & 2 (AI-obstacle). NOT the ephemeral type-3
  live-map obstacle photos — see `dreame-app-obstacle-photos-2026-06-12.md` on the capture share.

---

## 6. Suggested HA integration shape

- **Camera entity** backed by an XP2P client: on `async_camera_image` / stream start →
  run §2 chain (cache `accesstoken` until `expireAt`; re-fetch `getP2PInfo` per session) →
  `o=400 {on:1}` → open XP2P → expose still/stream. On stop → `o=400 {on:0}` + close P2P.
- **Snapshot/record services** → §4 flow; surface results via §5 list.
- **Hard dependency:** an XP2P/IoTVideo P2P client usable from Python/HA. If none is viable,
  the realistic fallback is **snapshot/record + gallery playback only** (all pure HTTP, fully
  reproducible) and skip the live preview — still useful (AI/manual photos, recorded clips).

---

## 7. Open questions / risks
- **XP2P SDK in Python:** the blocker. Tencent's SDK is C/Java/iOS-first; needs a binding or a
  reimpl of the P2P handshake. Until solved, live preview is not implementable; HTTP capture
  features are.
- **`sign` algorithm:** assumed identical to the integration's existing Dreame request signer
  (same host/params). Confirm the video endpoints accept the same signature scheme.
- **`pwd` from addOssNew:** purpose unconfirmed.
- **Token lifetimes:** `accesstoken expireAt` ~7 d; `p2pInfo` treat as per-session.

## 8. Inventory.yaml edits to make (for the authoritative source)
1. Add a `live_video` / camera-session entry with the §2 chain (endpoints, order, shapes,
   XP2P SDK requirement) and the §4 snapshot/record flow.
2. **Correct** s4p22 / s4p44 / s4p59 / s4p83 and any "no camera module on g2408" notes —
   the camera exists (`feature:"video_tx"`, Tencent XP2P). Keep the distinction from the
   `/smart-app/ipc/*` security-camera line.
3. Cross-link `o400 camera_live_view`, `o=15 {c}`, and the OSS gallery (`userDidOssList`).

## 9. Sources (on the capture share `/Volumes/claude/homeassistant/`)
- `dreame-app-WRITE-implementation-guide-2026-06-09.md` §🎥 / §5
- `dreame-app-findings-2026-06-09-settings-sweep.md` §🎥 LIVE CAMERA / §🎬 manual capture
- Raw: `dreame-app-capture-2026-06-09/{miio-cloud-13267-http.jsonl, https-443.jsonl}`
  (grep `dreame-third-video`, `iotoss/addOssNew`, `userDidOssList`).
