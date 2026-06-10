"""On-disk archive of album (Patrol + AI-obstacle) photos.

[dreame-app-implementation-guide-2026-06-09.md] Photos are fetched from the
dreame-eu OSS bucket (see protocol/photo_keys.py) and persisted here verbatim.
Content-addressed by md5; re-fetching the same image is a no-op. Mirrors
archive/lidar.py but is NOT map-scoped and tracks a person-detection flag.

Privacy: these JPEGs contain images of the property and people. Local only;
never committed (see docs/data-policy.md).
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

INDEX_NAME = "index.json"
INDEX_VERSION = 1


@dataclass(frozen=True)
class ArchivedPhoto:
    """Metadata for one archived photo (as stored in ``index.json``)."""

    filename: str
    name: str
    unix_ts: int
    size_bytes: int
    md5: str
    is_person: bool
    category: str = "obstacle"
    detection: dict | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "name": self.name,
            "unix_ts": self.unix_ts,
            "size_bytes": self.size_bytes,
            "md5": self.md5,
            "is_person": self.is_person,
            "category": self.category,
            "detection": self.detection,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ArchivedPhoto":
        is_person = bool(d.get("is_person", False))
        raw_cat = d.get("category")
        category = raw_cat if raw_cat else ("person" if is_person else "obstacle")
        return cls(
            filename=str(d.get("filename", "")),
            name=str(d.get("name", "")),
            unix_ts=int(d.get("unix_ts", 0)),
            size_bytes=int(d.get("size_bytes", 0)),
            md5=str(d.get("md5", "")),
            is_person=is_person,
            category=category,
            detection=d.get("detection") or None,
        )


def _format_date(unix_ts: int) -> str:
    try:
        return datetime.fromtimestamp(int(unix_ts), tz=UTC).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return "unknown-date"


class PhotoArchive:
    """Filesystem-backed photo archive for Patrol and AI-obstacle images.

    NOT map-scoped — all photos share a single flat directory under ``root``.
    Photos are deduplicated by md5 so re-fetching from the cloud is a no-op.

    The on-disk index is NOT read in ``__init__`` — ``load_index()`` must be
    called (via ``hass.async_add_executor_job`` from async context) before any
    index-dependent accessor is used. Mirrors ``LidarArchive`` so the two
    archives can be set up with the same pattern.
    """

    def __init__(self, root: Path, retention: int = 0, max_bytes: int = 0) -> None:
        """`retention` = max number of photos to keep on disk. 0 = unlimited.
        `max_bytes` = cumulative-size cap in bytes. 0 = unlimited.
        Both caps run independently after every archive write.
        """
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._index: list[ArchivedPhoto] = []
        self._retention = int(retention) if retention else 0
        self._max_bytes = int(max_bytes) if max_bytes else 0
        self._per_cat: int = 0
        self._index_loaded: bool = False

    def _index_path(self) -> Path:
        return self._root / INDEX_NAME

    def load_index(self) -> None:
        """Read ``index.json`` off disk. Idempotent; blocking — call from an
        executor. See ``LidarArchive.load_index`` for the same pattern."""
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
            rows = data.get("photos", []) if isinstance(data, dict) else []
            self._index = [
                ArchivedPhoto.from_dict(r) for r in rows if isinstance(r, dict)
            ]
        except (OSError, ValueError, TypeError) as ex:
            _LOGGER.warning("PhotoArchive: index load failed (%s); starting fresh", ex)
            self._index = []

    def _save_index(self) -> None:
        path = self._index_path()
        tmp = path.with_suffix(".json.tmp")
        payload = {
            "version": INDEX_VERSION,
            "photos": [p.to_dict() for p in self._index],
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

    def has(self, md5: str) -> bool:
        self.load_index()
        return any(p.md5 == md5 for p in self._index)

    def latest(self) -> ArchivedPhoto | None:
        self.load_index()
        if not self._index:
            return None
        return max(self._index, key=lambda p: p.unix_ts)

    def latest_person(self) -> ArchivedPhoto | None:
        """Return the most-recently-archived photo flagged ``is_person``,
        or ``None`` if no person photos have been stored."""
        self.load_index()
        persons = [p for p in self._index if p.is_person]
        return max(persons, key=lambda p: p.unix_ts) if persons else None

    def list_photos(self) -> list[ArchivedPhoto]:
        """Return all archived photos newest-first."""
        self.load_index()
        return sorted(self._index, key=lambda p: p.unix_ts, reverse=True)

    def read_bytes(self, filename: str) -> bytes | None:
        """Read the raw JPEG bytes for *filename*. Returns ``None`` on I/O error."""
        try:
            return (self._root / filename).read_bytes()
        except OSError:
            return None

    def archive(
        self,
        *,
        name: str,
        unix_ts: int,
        data: bytes,
        is_person: bool,
        category: str = "obstacle",
        detection: dict | None = None,
    ) -> ArchivedPhoto | None:
        """Persist one JPEG. Idempotent by md5. Returns the archive record on
        first insert, ``None`` when the md5 already exists or the payload is
        empty."""
        if not data:
            return None
        md5 = hashlib.md5(data).hexdigest()
        if self.has(md5):
            return None

        stem = f"{_format_date(unix_ts)}_{int(unix_ts)}_{md5[:8]}.jpg"
        path = self._root / stem
        tmp = path.with_suffix(".jpg.tmp")
        try:
            tmp.write_bytes(data)
            tmp.replace(path)
        except OSError as ex:
            _LOGGER.warning("PhotoArchive: write failed (%s): %s", ex, path)
            return None

        photo = ArchivedPhoto(
            filename=stem,
            name=str(name or ""),
            unix_ts=int(unix_ts),
            size_bytes=len(data),
            md5=md5,
            is_person=bool(is_person),
            category=str(category) if category else "obstacle",
            detection=detection,
        )
        self._index.append(photo)
        self._save_index()
        self._enforce_retention()
        self._enforce_size_cap()
        self._enforce_per_category_retention()
        return photo

    def _enforce_retention(self) -> None:
        """Prune oldest photos beyond the configured cap. Mirrors
        LidarArchive._enforce_retention."""
        keep = getattr(self, "_retention", 0)
        if not keep or keep <= 0:
            return
        if len(self._index) <= keep:
            return
        sorted_idx = sorted(self._index, key=lambda p: p.unix_ts)
        excess = len(sorted_idx) - keep
        to_drop = sorted_idx[:excess]
        for photo in to_drop:
            try:
                (self._root / photo.filename).unlink(missing_ok=True)
            except OSError as ex:
                _LOGGER.warning(
                    "PhotoArchive: failed to prune %s: %s",
                    photo.filename,
                    ex,
                )
        kept_files = {p.filename for p in sorted_idx[excess:]}
        self._index = [p for p in self._index if p.filename in kept_files]
        self._save_index()
        _LOGGER.info(
            "PhotoArchive: pruned %d old photo(s) past retention=%d",
            excess,
            keep,
        )

    def _enforce_size_cap(self) -> None:
        """Prune oldest photos until total on-disk size is at or below the cap.
        No-op when cap is 0 (unlimited) or already under cap. Mirrors
        LidarArchive._enforce_size_cap."""
        cap = getattr(self, "_max_bytes", 0)
        if not cap or cap <= 0:
            return
        sorted_idx = sorted(self._index, key=lambda p: p.unix_ts)
        total = sum(p.size_bytes for p in sorted_idx)
        if total <= cap:
            return
        pruned = 0
        while sorted_idx and total > cap:
            photo = sorted_idx.pop(0)
            try:
                (self._root / photo.filename).unlink(missing_ok=True)
            except OSError as ex:
                _LOGGER.warning(
                    "PhotoArchive: failed to prune %s: %s", photo.filename, ex,
                )
            total -= photo.size_bytes
            pruned += 1
        kept_files = {p.filename for p in sorted_idx}
        self._index = [p for p in self._index if p.filename in kept_files]
        if pruned:
            self._save_index()
            _LOGGER.info(
                "PhotoArchive: pruned %d photo(s) to honor max_bytes=%d (now %d B)",
                pruned,
                cap,
                total,
            )

    def set_retention(self, keep: int) -> None:
        """Update the count cap and prune immediately if needed."""
        self._retention = int(keep) if keep else 0
        self._enforce_retention()

    def set_max_bytes(self, max_bytes: int) -> None:
        """Update the cumulative-size cap and prune immediately if needed."""
        self._max_bytes = int(max_bytes) if max_bytes else 0
        self._enforce_size_cap()

    def set_per_category_retention(self, keep: int) -> None:
        """Update the per-category count cap and prune immediately if needed."""
        self._per_cat = int(keep) if keep else 0
        self._enforce_per_category_retention()

    def count_by_category(self, cat: str) -> int:
        """Return the number of archived photos whose ``category`` matches *cat*."""
        self.load_index()
        return sum(1 for p in self._index if p.category == cat)

    def _enforce_per_category_retention(self) -> None:
        """For each category, keep at most ``_per_cat`` newest photos.

        Drops file + index entry for any excess, then saves the index.
        No-op when ``_per_cat <= 0``.
        """
        keep = self._per_cat
        if keep <= 0:
            return
        # group by category
        from collections import defaultdict
        by_cat: dict[str, list[ArchivedPhoto]] = defaultdict(list)
        for photo in self._index:
            by_cat[photo.category].append(photo)

        to_drop: list[ArchivedPhoto] = []
        for photos in by_cat.values():
            if len(photos) <= keep:
                continue
            # keep newest by unix_ts
            sorted_photos = sorted(photos, key=lambda p: p.unix_ts)
            excess = len(sorted_photos) - keep
            to_drop.extend(sorted_photos[:excess])

        if not to_drop:
            return

        for photo in to_drop:
            try:
                (self._root / photo.filename).unlink(missing_ok=True)
            except OSError as ex:
                _LOGGER.warning(
                    "PhotoArchive: failed to prune %s: %s", photo.filename, ex,
                )
        drop_filenames = {p.filename for p in to_drop}
        self._index = [p for p in self._index if p.filename not in drop_filenames]
        self._save_index()
        _LOGGER.info(
            "PhotoArchive: pruned %d photo(s) past per-category retention=%d",
            len(to_drop),
            keep,
        )
