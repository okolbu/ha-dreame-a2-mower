"""Parse the Dreame embedded-JPEG COM (FFFE) metadata block.

The app stores AI-detection metadata in the JPEG COM marker as base64 JSON:
  {"d":[{"c":<class>,"f":<conf 0-1>,"x","y","w","h"}], "o":<opcode>, "s", "sub"}
o=107 patrol, o=100 mow/obstacle. Returns a normalized dict or None.
"""
from __future__ import annotations

import base64
import json
import struct
from typing import Any

_SOI = b"\xff\xd8"
_COM = b"\xff\xfe"
_SOS = b"\xff\xda"


def parse_jpeg_com(data: Any) -> dict | None:
    """Return {detections:[{cls,conf,x,y,w,h}], o, s, sub} from the JPEG's COM
    marker, or None if absent/malformed."""
    if not isinstance(data, (bytes, bytearray)) or len(data) < 4 or data[:2] != _SOI:
        return None
    i = 2
    n = len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            break
        marker = bytes(data[i:i + 2])
        seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker == _COM:
            seg = data[i + 4:i + 2 + seg_len]
            try:
                raw = base64.b64decode(bytes(seg).split(b"\x00", 1)[0])
                meta = json.loads(raw)
            except (ValueError, TypeError):
                return None
            if not isinstance(meta, dict):
                return None
            dets = []
            for d in meta.get("d") or []:
                if isinstance(d, dict):
                    dets.append({"cls": d.get("c"), "conf": d.get("f"),
                                 "x": d.get("x"), "y": d.get("y"),
                                 "w": d.get("w"), "h": d.get("h")})
            return {"detections": dets, "o": meta.get("o"),
                    "s": meta.get("s"), "sub": meta.get("sub")}
        if marker == _SOS:
            break
        i += 2 + seg_len
    return None
