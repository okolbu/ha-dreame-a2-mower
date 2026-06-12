# Dreame app MITM rig — setup & gotchas (so the next session skips the trial-and-error)

Goal: decrypt the **Dreame `com.dreame.smartlife` app ↔ cloud** traffic to RE the
g2408 mower protocol. The expensive part was (a) stopping the emulator crashing and
(b) discovering **Frida is a dead end for this app's TLS** — use a transparent relay
instead. Toolkit scripts: `dreame-app-capture-2026-06-09/mitm-toolkit/scripts/`
(host paths are `/Users/ok/dreame-mitm/` on the Apple-Silicon Mac; adapt as needed).

## TL;DR reproduce
```
./00-install-host-tools.sh      # one-time: brew(mitmproxy,scrcpy,JDK) + pipx(frida,objection) + LOCAL Android SDK + frida-server
./10-create-avd.sh              # one-time: API30 arm64 google_apis AVD (NOT _playstore — must be rootable)
./start-session.sh              # boot emulator (+system CA +frida +launch app)   [EMU_WINDOW=1 GPU_MODE=angle_indirect]
./start-relays.sh               # the KEY step: socat :19973 + mitmproxy reverse :13267 + iptables redirects + bounce app
# analyze: logs/miio-13267.jsonl  (THE main capture: control + reads)
```

## Architecture — 3 capture layers (the app talks to 3 places, only 1 via the proxy)
| traffic | host:port | how captured |
|---|---|---|
| HTTPS (Aliyun auth/region, OSS map+photos, shop, Tencent video creds) | `*:443` | emulator `-http-proxy 10.0.2.2:8080` → **mitmweb** (system CA + Frida unpin) |
| **miio CLOUD API (control `sendCommand` + reads — THE important one)** | `eu.iot.dreame.tech:13267` | **mitmproxy reverse-proxy** on host :13267 + guest iptables DNAT |
| miio MQTT **status** channel | `10000.mt.eu.iot.dreame.tech:19973` | **socat TLS relay** on host :19973 + guest iptables DNAT |
The :13267 and :19973 connections **bypass the http-proxy** (non-443 direct TLS) →
that's why they need the iptables-redirect + dedicated host relays.

## CRITICAL gotchas (each cost hours)
1. **Emulator crashes ≈ every minute → `-feature -VirtioWifi`.** Root cause: the
   `netsimd` virtual-WiFi daemon throws a gRPC `bad_function_call` and aborts qemu
   on a timer (crash report: SIGABRT in `grpc…ThreadInternalsPosix`; `netsimd-*.ips`
   crashes at the same timestamp; "Netsim Wifi … Socket closed" warnings). Disabling
   plain `-Wifi` is NOT enough — must disable **`VirtioWifi`**. (Now in 20-start-emulator.sh: `-feature -Vulkan,-VirtioWifi`.) App still has internet via legacy net.
2. **GPU:** `-gpu angle_indirect` (Metal) is the most stable; **host GPU crashes**,
   swiftshader crashes under load. Also `-feature -Vulkan` (heavy screens trip guest Vulkan).
3. **AVOID the in-app LiDAR 3D view** — it crashes the GPU regardless of backend.
   (We already have the PCD; don't open it.)
4. **Lean RAM (3 GB).** 6 GB caused host swap-thrashing crashes on a memory-tight Mac.
5. **Frida is USELESS for this app's TLS — do NOT waste time on it.** App is
   DEX-packed (`libemgmo`) AND uses bundled/shaded TLS: native `SSL_read/write` hooks
   = 0 hits, Conscrypt `NativeCrypto` (all 6 variants) = 0 hits, ClassLoader/
   enumerate discovery = 0 Aliyun classes. **The transparent relay (below) is the way.**
6. **The app does NOT pin the miio endpoints** (:13267, :19973) — it accepts our
   CA-signed leaf cert natively, **no Frida needed** for those. (Frida unpin is only
   useful for the :443 Java/OkHttp pinning.) So the relays work even on an
   app instance launched by the user (not just `frida -f`).
7. **macOS toolchain traps:** no `timeout` (use bg+wait), no `mapfile` (bash 3.2),
   Homebrew `avdmanager` can't see the local SDK (install `cmdline-tools;latest`
   LOCALLY and use that avdmanager), mitmproxy `--listen-port 0` is invalid.
8. **Reboot loses guest state:** iptables redirects + tmpfs system-CA reset every
   emulator boot → `start-relays.sh` re-applies redirects + bounces the app;
   `40-install-ca-system.sh` re-injects the CA. Host relays survive crashes.

## The relay (how the :13267 / :19973 interception works)
- Make a **leaf cert for the broker/cloud hostnames signed by the mitmproxy CA**
  (openssl; SANs incl. `*.iot.dreame.tech`, `10000.mt.eu.iot.dreame.tech`). App
  trusts it via the system CA store. Material in `relay/` (regenerable).
- **:13267** = HTTP-over-TLS → `mitmdump --mode reverse:https://eu.iot.dreame.tech:13267
  --listen-port 13267 -s record-all.py` (decodes + records to `miio-13267.jsonl`).
- **:19973** = miio MQTT/TLS → `socat -x OPENSSL-LISTEN:19973,cert=leaf-bundle.pem,…
  OPENSSL:10000.mt.eu.iot.dreame.tech:19973` (hexdump → `mqtt.log`; parse with
  `parse-mqtt.py`). NOTE: device CONTROL goes via :13267 `sendCommand`, NOT MQTT;
  MQTT is status-push only (the integration's own probe already decodes status).
- Guest redirect: `iptables -t nat -A OUTPUT -p tcp --dport <port> ! -d 10.0.2.2
  -j DNAT --to 10.0.2.2:<port>`.

## What lives where (endpoints recap — see WRITE guide for payloads)
- **Control + settings:** `eu.iot.dreame.tech:13267/dreame-iot-com-10000/device/sendCommand`
  → `action s2.a50 {m:g|s|a, …}` (signed; integration already signs this host).
- **Photos:** `iotoss/userDidOssList` (list+signed URLs) / `addOssNew`+`ossUploaded`
  (manual upload) / `checkDevOssStorage` (quota). Metadata embedded in JPEG COM.
- **GPS:** `dreame-mower-service-app/location/getRecords`. **Live video:** Tencent
  XP2P via `dreame-third-video/tx/*` (stream is off-relay P2P).

## Analysis helpers (in scripts/)
- `record-all.py` — mitmproxy addon: every req+resp → JSONL (loaded by the reverse proxy + mitmweb).
- `parse-mqtt.py` — decode the socat MQTT hexdump into readable frames.
- `iot.py {summary|watch|show}` — filter JSONL to just Dreame/IoT calls (drops shop/google noise).
- `sweep-decode.py` — diff consecutive CFG writes (used for the settings sweep; great for `PRE`-style arrays).

## App version note
Use a **Flutter-era build (2.5.x)** for full features (loads the g2408 plugin →
map/photo/camera). The old RN-only `1.5.41` is easier to MITM but can't load the
mower plugin. `.apkm`/`.xapk` are split bundles → `30-install-apk.sh` handles
install-multiple (drops non-arm64 splits). The app keeps you logged-in across
re-installs/reboots (userdata persists).
