"""On-disk archive of patrol/AI-obstacle video clips (thumb JPG + MP4).

Mirrors ``archive/photos.py`` in structure and conventions. Videos are
deduplicated by ``video_id`` (the cloud's opaque string identifier), so
re-fetching the same clip is a no-op.

Privacy: these files may contain images of the property and people. Local
only; never committed (see docs/data-policy.md).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

INDEX_NAME = "index.json"
INDEX_VERSION = 1


@dataclass(frozen=True)
class ArchivedVideo:
    """Metadata for one archived video clip (as stored in ``index.json``)."""

    video_id: str
    mp4_filename: str
    thumb_filename: str
    unix_ts: int
    duration: int
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "mp4_filename": self.mp4_filename,
            "thumb_filename": self.thumb_filename,
            "unix_ts": self.unix_ts,
            "duration": self.duration,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ArchivedVideo":
        return cls(
            video_id=str(d.get("video_id", "")),
            mp4_filename=str(d.get("mp4_filename", "")),
            thumb_filename=str(d.get("thumb_filename", "")),
            unix_ts=int(d.get("unix_ts", 0)),
            duration=int(d.get("duration", 0)),
            size_bytes=int(d.get("size_bytes", 0)),
        )


class VideoArchive:
    """Filesystem-backed archive for patrol/AI-obstacle video clips.

    NOT map-scoped — all videos share a single flat directory under ``root``.
    Videos are deduplicated by ``video_id`` so re-fetching from the cloud is
    a no-op.

    The on-disk index is NOT read in ``__init__`` — ``load_index()`` must be
    called (via ``hass.async_add_executor_job`` from async context) before any
    index-dependent accessor is used. Mirrors ``PhotoArchive`` so the two
    archives can be set up with the same pattern.
    """

    def __init__(self, root: Path, retention: int = 0, max_bytes: int = 0) -> None:
        """`retention` = max number of video clips to keep on disk. 0 = unlimited.
        `max_bytes` = cumulative-size cap in bytes. 0 = unlimited.
        Both caps run independently after every archive write.
        """
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._index: list[ArchivedVideo] = []
        self._retention = int(retention) if retention else 0
        self._max_bytes = int(max_bytes) if max_bytes else 0
        self._index_loaded: bool = False

    def _index_path(self) -> Path:
        return self._root / INDEX_NAME

    def load_index(self) -> None:
        """Read ``index.json`` off disk. Idempotent; blocking — call from an
        executor. See ``PhotoArchive.load_index`` for the same pattern."""
        if self._index_loaded:
            return
        self._load_index()
        self._index_loaded = True

    def _load_index(self) -> None:
        path = self._index_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            rows = data.get("videos", []) if isinstance(data, dict) else []
            self._index = [
                ArchivedVideo.from_dict(r) for r in rows if isinstance(r, dict)
            ]
        except (OSError, ValueError, TypeError) as ex:
            _LOGGER.warning("VideoArchive: index load failed (%s); starting fresh", ex)
            self._index = []

    def _save_index(self) -> None:
        path = self._index_path()
        tmp = path.with_suffix(".json.tmp")
        payload = {
            "version": INDEX_VERSION,
            "videos": [v.to_dict() for v in self._index],
        }
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp.replace(path)

    # -------------------- public API --------------------

    @property
    def root(self) -> Path:
        return self._root

    @property
    def count(self) -> int:
        self.load_index()
        return len(self._index)

    def has(self, video_id: str) -> bool:
        self.load_index()
        return any(v.video_id == video_id for v in self._index)

    def latest(self) -> ArchivedVideo | None:
        self.load_index()
        if not self._index:
            return None
        return max(self._index, key=lambda v: v.unix_ts)

    def list_videos(self) -> list[ArchivedVideo]:
        """Return all archived videos newest-first."""
        self.load_index()
        return sorted(self._index, key=lambda v: v.unix_ts, reverse=True)

    def get(self, video_id: str) -> ArchivedVideo | None:
        """Return the index entry for *video_id*, or ``None`` if not present."""
        self.load_index()
        return next((v for v in self._index if v.video_id == video_id), None)

    def read_thumb(self, video_id: str) -> bytes | None:
        """Read the thumb JPG bytes for *video_id* IF it is in the index.

        Returns ``None`` when the id is unknown (path-traversal guard) or on
        an I/O error — never opens an arbitrary path.
        """
        entry = self.get(video_id)
        if entry is None:
            return None
        try:
            return (self._root / entry.thumb_filename).read_bytes()
        except OSError:
            return None

    def read_mp4(self, video_id: str) -> bytes | None:
        """Read the MP4 bytes for *video_id* IF it is in the index.

        Returns ``None`` when the id is unknown (path-traversal guard) or on
        an I/O error — never opens an arbitrary path.
        """
        entry = self.get(video_id)
        if entry is None:
            return None
        try:
            return (self._root / entry.mp4_filename).read_bytes()
        except OSError:
            return None

    def set_retention(self, keep: int) -> None:
        """Update the count cap and prune immediately if needed."""
        self._retention = int(keep) if keep else 0
        self._enforce_retention()

    def set_max_bytes(self, max_bytes: int) -> None:
        """Update the cumulative-size cap and prune immediately if needed."""
        self._max_bytes = int(max_bytes) if max_bytes else 0
        self._enforce_size_cap()

    def archive(
        self,
        *,
        video_id: str,
        mp4: bytes,
        thumb: bytes,
        unix_ts: int,
        duration: int,
    ) -> ArchivedVideo | None:
        """Persist one video clip (MP4 + thumb JPG). Idempotent by video_id.
        Returns the archive record on first insert, ``None`` when the
        video_id already exists or both payloads are empty."""
        if not mp4 and not thumb:
            return None
        if self.has(video_id):
            return None

        mp4_filename = f"{video_id}.mp4"
        thumb_filename = f"{video_id}.jpg"

        mp4_path = self._root / mp4_filename
        mp4_tmp = mp4_path.with_suffix(".mp4.tmp")
        try:
            mp4_tmp.write_bytes(mp4)
            mp4_tmp.replace(mp4_path)
        except OSError as ex:
            _LOGGER.warning("VideoArchive: mp4 write failed (%s): %s", ex, mp4_path)
            return None

        thumb_path = self._root / thumb_filename
        thumb_tmp = thumb_path.with_suffix(".jpg.tmp")
        try:
            thumb_tmp.write_bytes(thumb)
            thumb_tmp.replace(thumb_path)
        except OSError as ex:
            _LOGGER.warning(
                "VideoArchive: thumb write failed (%s): %s", ex, thumb_path
            )
            # Roll back the mp4 we already wrote
            mp4_path.unlink(missing_ok=True)
            return None

        video = ArchivedVideo(
            video_id=str(video_id),
            mp4_filename=mp4_filename,
            thumb_filename=thumb_filename,
            unix_ts=int(unix_ts),
            duration=int(duration),
            size_bytes=len(mp4) + len(thumb),
        )
        self._index.append(video)
        self._save_index()
        self._enforce_retention()
        self._enforce_size_cap()
        return video

    def _enforce_retention(self) -> None:
        """Prune oldest clips beyond the configured cap. Mirrors
        PhotoArchive._enforce_retention. Removes BOTH mp4 and thumb together."""
        keep = getattr(self, "_retention", 0)
        if not keep or keep <= 0:
            return
        if len(self._index) <= keep:
            return
        sorted_idx = sorted(self._index, key=lambda v: v.unix_ts)
        excess = len(sorted_idx) - keep
        to_drop = sorted_idx[:excess]
        for video in to_drop:
            try:
                (self._root / video.mp4_filename).unlink(missing_ok=True)
            except OSError as ex:
                _LOGGER.warning(
                    "VideoArchive: failed to prune mp4 %s: %s",
                    video.mp4_filename,
                    ex,
                )
            try:
                (self._root / video.thumb_filename).unlink(missing_ok=True)
            except OSError as ex:
                _LOGGER.warning(
                    "VideoArchive: failed to prune thumb %s: %s",
                    video.thumb_filename,
                    ex,
                )
        kept_ids = {v.video_id for v in sorted_idx[excess:]}
        self._index = [v for v in self._index if v.video_id in kept_ids]
        self._save_index()
        _LOGGER.info(
            "VideoArchive: pruned %d old clip(s) past retention=%d",
            excess,
            keep,
        )

    def _enforce_size_cap(self) -> None:
        """Prune oldest clips until total on-disk size is at or below the cap.
        No-op when cap is 0 (unlimited) or already under cap. Mirrors
        PhotoArchive._enforce_size_cap. Removes BOTH mp4 and thumb together."""
        cap = getattr(self, "_max_bytes", 0)
        if not cap or cap <= 0:
            return
        sorted_idx = sorted(self._index, key=lambda v: v.unix_ts)
        total = sum(v.size_bytes for v in sorted_idx)
        if total <= cap:
            return
        pruned = 0
        while sorted_idx and total > cap:
            video = sorted_idx.pop(0)
            try:
                (self._root / video.mp4_filename).unlink(missing_ok=True)
            except OSError as ex:
                _LOGGER.warning(
                    "VideoArchive: failed to prune mp4 %s: %s", video.mp4_filename, ex,
                )
            try:
                (self._root / video.thumb_filename).unlink(missing_ok=True)
            except OSError as ex:
                _LOGGER.warning(
                    "VideoArchive: failed to prune thumb %s: %s",
                    video.thumb_filename,
                    ex,
                )
            total -= video.size_bytes
            pruned += 1
        kept_ids = {v.video_id for v in sorted_idx}
        self._index = [v for v in self._index if v.video_id in kept_ids]
        if pruned:
            self._save_index()
            _LOGGER.info(
                "VideoArchive: pruned %d clip(s) to honor max_bytes=%d (now %d B)",
                pruned,
                cap,
                total,
            )
