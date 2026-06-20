"""Disk-backed log of AIOBS obstacle-marker metadata.

Holds one record per detection (keyed by marker id) so the metadata survives
even when the photo can't be fetched (the getDeiviceFile backend is currently
unreliable). The image bytes, when fetched, are stored in PhotoArchive; this
log only tracks metadata + the fetch status. Mirrors archive/photos.py's
JSON-index-on-disk shape.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ..protocol.obstacle_markers import ObstacleMarker

_VALID_STATUS = {"pending", "backend_unavailable", "ready", "gone"}


@dataclass
class LoggedMarker:
    id: str
    filename: str
    detection_epoch: float | None
    obstacle_class: int | None
    confidence: int | None
    polygon_m: list[list[float]]
    image_status: str = "pending"
    image_md5: str | None = None


class ObstacleMarkerLog:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._path = self._root / "markers.json"
        self._index: dict[str, LoggedMarker] = {}

    def load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
        except (OSError, ValueError):
            return
        if not isinstance(raw, list):
            return
        for rec in raw:
            try:
                lm = LoggedMarker(**rec)
            except TypeError:
                continue
            self._index[lm.id] = lm

    def _persist(self) -> None:
        self._path.write_text(json.dumps([asdict(v) for v in self._index.values()]))

    def note(self, marker: ObstacleMarker) -> bool:
        """Upsert by id. Returns True only on first insert."""
        if marker.id in self._index:
            return False
        self._index[marker.id] = LoggedMarker(
            id=marker.id,
            filename=marker.filename,
            detection_epoch=marker.detection_epoch,
            obstacle_class=marker.obstacle_class,
            confidence=marker.confidence,
            polygon_m=[[x, y] for x, y in marker.polygon_m],
        )
        self._persist()
        return True

    def set_status(
        self, marker_id: str, status: str, *, image_md5: str | None = None
    ) -> None:
        if status not in _VALID_STATUS:
            raise ValueError(f"invalid status {status!r}")
        rec = self._index.get(marker_id)
        if rec is None:
            return
        rec.image_status = status
        if image_md5 is not None:
            rec.image_md5 = image_md5
        self._persist()

    def pending(self) -> list[LoggedMarker]:
        return [r for r in self._index.values() if r.image_status == "pending"]

    def all(self) -> list[LoggedMarker]:
        return list(self._index.values())
