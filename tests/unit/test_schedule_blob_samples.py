import base64
from custom_components.dreame_a2_mower.cloud_state import SchedulePlan
from custom_components.dreame_a2_mower.protocol.schedule_encode import encode_schedule_blob


def _wire_weekday_to_maskbit(w):  # w: Sun=0..Sat=6 -> mask bit 0=Mon..6=Sun
    return (w + 6) % 7


def _blob_hex(plan):
    return base64.b64decode(encode_schedule_blob((plan,))).hex()


def test_all_area_sample():
    plan = SchedulePlan(time_min=780, weekday_mask=1 << _wire_weekday_to_maskbit(3),
                        action_type=0, zone_id=None, extra_bytes=b"")
    assert _blob_hex(plan) == "aa07300c0300ed"


def test_zone_full_sample():
    plan = SchedulePlan(time_min=544, weekday_mask=1 << _wire_weekday_to_maskbit(5),
                        action_type=1, zone_id=2, extra_bytes=b"")
    assert _blob_hex(plan) == "aa085120120002ed"


def test_zone_edge_sample():
    plan = SchedulePlan(time_min=480, weekday_mask=1 << _wire_weekday_to_maskbit(0),
                        action_type=2, zone_id=2, extra_bytes=bytes([0x00]))
    assert _blob_hex(plan) == "aa0902e021000200ed"
