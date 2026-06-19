"""Parse the AIOBS routed-action marker list into ObstacleMarker records.

Wire source: routed-action siid:2 aiid:50 in=[{"m":"g","t":"AIOBS","d":{"idx":0}}].
The response `d` dict carries `obs`: a list of rows, each
``[ [x_verts mm], [y_verts mm], confidence, class, filename, flag, id ]``.
[cloud/captures/mitm_session_20260619/miio-13267.jsonl@2026-06-17_19:50:15]

confidence ≈ f*100 and class == JPEG-COM "s" are cross-validated (verified);
``flag`` (index 5) is [UNVERIFIED].
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ObstacleMarker:
    """One AIOBS obstacle marker = a map polygon + the photo filename base."""

    id: str
    filename: str
    polygon_m: tuple[tuple[float, float], ...]
    confidence: int | None
    obstacle_class: int | None
    flag: int | None
    detection_epoch: float | None


def _epoch_from_filename(name: str) -> float | None:
    """``"1781714586.078000_0"`` → 1781714586.078 (the `_<idx>` suffix dropped)."""
    if not isinstance(name, str):
        return None
    base = name.split("_", 1)[0]
    try:
        return float(base)
    except ValueError:
        return None


def parse_aiobs_markers(payload: dict | None) -> list[ObstacleMarker]:
    if not isinstance(payload, dict):
        return []
    obs = payload.get("obs")
    if not isinstance(obs, list):
        return []
    out: list[ObstacleMarker] = []
    for row in obs:
        if not isinstance(row, (list, tuple)) or len(row) < 7:
            continue
        xs, ys, conf, cls, fname, flag, mid = row[:7]
        if not isinstance(xs, (list, tuple)) or not isinstance(ys, (list, tuple)):
            continue
        polygon_m = tuple(
            (float(x) / 1000.0, float(y) / 1000.0) for x, y in zip(xs, ys)
        )
        fname = str(fname)
        out.append(
            ObstacleMarker(
                id=str(mid),
                filename=fname,
                polygon_m=polygon_m,
                confidence=int(conf) if isinstance(conf, (int, float)) else None,
                obstacle_class=int(cls) if isinstance(cls, (int, float)) else None,
                flag=int(flag) if isinstance(flag, (int, float)) else None,
                detection_epoch=_epoch_from_filename(fname),
            )
        )
    return out
