import base64, json, struct
from custom_components.dreame_a2_mower.protocol import photo_meta


def _jpeg_with_com(meta: dict) -> bytes:
    payload = base64.b64encode(json.dumps(meta).encode()).decode().encode()
    seg = payload + b"\x00"
    length = len(seg) + 2
    return b"\xff\xd8" + b"\xff\xfe" + struct.pack(">H", length) + seg + b"\xff\xd9"


def test_parse_jpeg_com_extracts_detections_and_opcode():
    meta = {"d": [{"c": "person", "f": 0.81, "x": 1, "y": 2, "w": 3, "h": 4}], "o": 107, "s": 5, "sub": 35}
    out = photo_meta.parse_jpeg_com(_jpeg_with_com(meta))
    assert out["o"] == 107 and out["s"] == 5 and out["sub"] == 35
    assert out["detections"][0]["cls"] == "person"
    assert abs(out["detections"][0]["conf"] - 0.81) < 1e-6
    assert out["detections"][0]["x"] == 1 and out["detections"][0]["w"] == 3


def test_parse_jpeg_com_none_when_absent():
    assert photo_meta.parse_jpeg_com(b"\xff\xd8\xff\xd9") is None
    assert photo_meta.parse_jpeg_com(b"not a jpeg") is None
    assert photo_meta.parse_jpeg_com(None) is None


def test_parse_jpeg_com_no_detections():
    out = photo_meta.parse_jpeg_com(_jpeg_with_com({"d": [], "o": 100, "s": 5, "sub": 35}))
    assert out["detections"] == [] and out["o"] == 100
