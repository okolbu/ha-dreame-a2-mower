# g2408 capability snapshot

**Date**: 2026-04-27
**Source**: derived offline from `probe_log_*.jsonl` (3 weeks, 310 457 lines, 30 unique siid/piid pairs observed) + decompression of the encoded `DREAME_MODEL_CAPABILITIES` blob.

## Methodology

The capability flags resolved by `DreameMowerDeviceCapability.refresh()` come from three sources:

1. **`__init__` defaults** — hard-coded constructor values.
2. **Property-presence checks** — `device.get_property(P) is None / is not None` against the integration's property store, which is populated by MQTT pushes (and, in theory, API polls — but on g2408 those return `80001` per the protocol doc).
3. **Model-blob lookup** — `device_capabilities.get(model)` against the encoded `DREAME_MODEL_CAPABILITIES` blob, applying per-model overrides.

For (2), the canonical signal of "the integration sees this property" is "the firmware ever pushed it via MQTT" — so 3 weeks of `probe_log_*.jsonl` MQTT captures answer the property-presence question authoritatively for g2408 in the user's normal usage pattern.

For (3), the blob is JSON-zlib-base64; decompressing reveals **g2408 has no entry in the blob**:

```python
caps = json.loads(zlib.decompress(base64.b64decode(DREAME_MODEL_CAPABILITIES), zlib.MAX_WBITS | 32))
caps.get("g2408")  # → None
```

So the model-blob lookup adds **zero** capability flags on g2408. The blob is dead weight for this device. This is a strong corroborating signal for P1.4.4: deleting the blob breaks nothing.

## Observed (siid, piid) pairs in 3 weeks of MQTT

```
s1p1, s1p4, s1p50, s1p51, s1p52, s1p53,
s2p1, s2p2, s2p50, s2p51, s2p52, s2p53, s2p54, s2p55, s2p56, s2p62, s2p65, s2p66,
s3p1, s3p2,
s5p104, s5p105, s5p106, s5p107, s5p108,
s6p1, s6p2, s6p3, s6p117,
s99p20
```

Notable absences relevant to the capability flags (none observed):
- `s4p22` (AI_DETECTION), `s4p26` (CUSTOMIZED_CLEANING), `s4p48` (SHORTCUTS), `s4p54` (AUTO_SWITCH_SETTINGS), `s4p58` (TASK_TYPE), `s4p59` (PET_DETECTIVE), `s4p50` (LENSBRUSH_LEFT)
- `s5p4` (DND_TASK)
- `s6p7` (MULTI_FLOOR_MAP), `s6p14` (MAP_BACKUP_STATUS), `s6p15` (WIFI_MAP)
- `s7p5` (VOICE_ASSISTANT), `s10001p9` (CAMERA_LIGHT_BRIGHTNESS)
- `s13p1` (MAP_SAVING) — its absence drives `lidar_navigation = True`
- `s16p1` (SENSOR_DIRTY_LEFT) — its absence drove `disable_sensor_cleaning = True` (flag and all gated code deleted in P1.5)
- `s4p21` (OBSTACLE_AVOIDANCE) — also drove `disable_sensor_cleaning`
- `s3p3` (OFF_PEAK_CHARGING)

## Resolved capability flags (the snapshot)

```python
G2408_CAPABILITY_SNAPSHOT = {
    'ai_detection': False,
    'auto_charging': False,
    'auto_rename_segment': False,
    'auto_switch_settings': False,
    'backup_map': False,
    'camera_streaming': False,
    'cleangenius': False,
    'cleangenius_auto': False,
    'cleaning_route': False,
    'customized_cleaning': False,
    'dnd': False,
    'dnd_task': False,
    'extended_furnitures': False,
    'fill_light': False,
    'floor_direction_cleaning': False,
    'floor_material': False,
    'fluid_detection': False,
    'gen5': False,
    'large_particles_boost': False,
    'lensbrush': False,
    'lidar_navigation': True,           # MAP_SAVING not observed
    'list': None,                       # built lazily, not part of identity
    'map_object_offset': False,         # "p20" not in "g2408"
    'max_suction_power': False,
    'multi_floor_map': False,           # MULTI_FLOOR_MAP not observed
    'new_furnitures': False,
    'new_state': False,
    'obstacle_image_crop': False,
    'obstacles': False,
    'off_peak_charging': False,
    'pet_detective': False,
    'pet_furniture': False,
    'pet_furnitures': False,
    'robot_type': RobotType.LIDAR,
    'saved_furnitures': False,
    'segment_slow_clean_route': False,  # cleaning_route is False, so demoted
    'segment_visibility': False,
    'shortcuts': False,
    'task_type': False,
    'voice_assistant': False,
    'wifi_map': False,
}
```

## Implications for the P1 plan

- **P1.4.3 (flatten)**: `__init__` becomes a hard-coded constants list set to the values above. `refresh()` becomes a no-op preserved for call-site compatibility.
- **P1.4.4 (delete blob)**: the blob has no g2408 entry; decode call is provably dead. Safe to delete.
- **P1.5 (drop dead branches)**: `disable_sensor_cleaning = True` confirmed the **"always-disabled"** branch — entities gated by `not capability.disable_sensor_cleaning` were always-NOT-created (invisible to the user). Per the spec's "no §2.1 citation = delete" rule, all gated code (sensor.py, button.py, coordinator.py, three device.py blocks) and the flag itself were deleted. `disable_sensor_cleaning` no longer exists in the class or snapshot.

## Caveats

- The MQTT scan covers 3 weeks of one user's usage pattern. A property emitted only during a never-triggered user action (e.g., a Voice Assistant settings change that would emit `s7p5`) would be absent from the scan even if the firmware supports it. Since no in-app evidence was provided either for these features being available on g2408, the snapshot reflects "configurable on this firmware in this app version" not "exists somewhere in the firmware".
- The integration's `__init__` defaults sometimes diverge from the post-`refresh()` outcome. The values above are post-`refresh()` — i.e. what the running integration would produce, not the constructor defaults.
- `list` is `None` here because it's built only after the refresh's reflection loop runs; the snapshot represents the state right after `refresh()`, but `list` is rebuilt lazily on the constructor in the flattened form too — leaving it `None` in the snapshot is correct.
- `robot_type` is `RobotType.LIDAR` — set unconditionally at the end of `refresh()`.
