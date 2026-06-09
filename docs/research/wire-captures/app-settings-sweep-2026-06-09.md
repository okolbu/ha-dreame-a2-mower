<!-- Tier-3 dated evidence — read for context, NOT current truth. inventory.yaml wins. -->

# App settings-sweep — wire capture (2026-06-09)

Condensed index of the 2026-06-09 Android-app MITM settings sweep (app 2.5.6.4
→ `eu.iot.dreame.tech:13267` relay + miio-MQTT). Full raw detail lives
out-of-tree at:
- `/data/claude/homeassistant/dreame-app-findings-2026-06-09-settings-sweep.md`
- `/data/claude/homeassistant/dreame-app-WRITE-implementation-guide-2026-06-09.md`

Facts below are promoted into `inventory.yaml` (the SoT); cite this file as
`app-mitm:2026-06-09-settings-sweep` in `verifications:`.

## Resolved this sweep
| Surface | Resolution |
|---|---|
| PRE indices 3,4,5,6,7,9,10,12,13,14,15,16 | Each mapped + value-confirmed by isolated toggle |
| PRE[0]/[1]/[2] | version byte / map index / zone index |
| CFG WRP/FDP/PATH/DND/LOW/PROT/BAT/BP/STUN/AOP/CLS/PIN/VOICE/VOL/LANG/MSG_ALERT/ATA/REC/LIT | exact write payloads |
| PREP | per-zone General↔Custom enable {idx,value} |
| Routed opcodes 3,4,5,6,9,13,100–103,107,200,201,204,208,215,218,219,220,221,234,400 | confirmed |
| Schedule write | SCHDDV3 (chunked protobuf, format known via schedule_decode.py) + SCHDIV3 + SCHDSV3 |
| MAP.* | decoded-map JSON cached in iotuserdata |
| OSS photos/video | userDidOssList + embedded-JPEG metadata + checkDevOssStorage + addOssNew/ossUploaded |
| GPS | location/getRecords (WGS84 strings, ATA[2]-gated) |
| NET / REMOTE | wifi list / 4G SIM |
| Message center | message-record/list v1, device-messages, share-messages |
| Tencent video | /dreame-third-video/tx/* cred chain (stream off-relay) |

## Supersedes
- `app-api-surface-2026-05-25.md`: marketing System Messages ARE reachable via
  `message-record/list?version=v1` (the earlier probe used `/v2/`, which was empty).
