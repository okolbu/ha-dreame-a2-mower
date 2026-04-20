"""Per-session summary archive on disk.

Each completed mowing session produces a JSON blob (see
`protocol.session_summary`). The archive persists one file per session so
future analysis can reconstruct history without re-fetching from the
Dreame cloud.

File layout:

    <root>/<YYYY-MM-DD>_<end_ts>_<md5[:8]>.json      raw JSON as received
    <root>/index.json                                 lightweight index

The archive is content-addressed by `summary.md5`: re-archiving the same
session is a no-op. The index file is rewritten atomically on every
archive. No data is ever deleted automatically — users can prune by hand.

No HA dependency here — the class takes a plain filesystem `Path`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_LOGGER = logging.getLogger(__name__)

INDEX_NAME = "index.json"
INDEX_VERSION = 1


@dataclass(frozen=True)
class ArchivedSession:
    """Metadata for one archived session (as stored in `index.json`)."""

    filename: str
    start_ts: int
    end_ts: int
    duration_min: int
    area_mowed_m2: float
    map_area_m2: int
    md5: str

    @classmethod
    def from_summary(cls, filename: str, summary) -> "ArchivedSession":
        return cls(
            filename=filename,
            start_ts=int(summary.start_ts),
            end_ts=int(summary.end_ts),
            duration_min=int(summary.duration_min),
            area_mowed_m2=float(summary.area_mowed_m2),
            map_area_m2=int(summary.map_area_m2),
            md5=str(summary.md5),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "duration_min": self.duration_min,
            "area_mowed_m2": self.area_mowed_m2,
            "map_area_m2": self.map_area_m2,
            "md5": self.md5,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ArchivedSession":
        return cls(
            filename=str(d.get("filename", "")),
            start_ts=int(d.get("start_ts", 0)),
            end_ts=int(d.get("end_ts", 0)),
            duration_min=int(d.get("duration_min", 0)),
            area_mowed_m2=float(d.get("area_mowed_m2", 0.0)),
            map_area_m2=int(d.get("map_area_m2", 0)),
            md5=str(d.get("md5", "")),
        )


class SessionArchive:
    """Filesystem-backed session archive."""

    def __init__(self, root: Path, retention: int = 0) -> None:
        """`retention` = max number of sessions to keep on disk. 0 means
        unlimited. Adjustable at runtime via `set_retention()`.
        """
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._index: list[ArchivedSession] = []
        self._retention = int(retention) if retention else 0
        self._load_index()

    # -------------------- index I/O --------------------

    def _index_path(self) -> Path:
        return self._root / INDEX_NAME

    def _load_index(self) -> None:
        path = self._index_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            rows = data.get("sessions", []) if isinstance(data, dict) else []
            self._index = [
                ArchivedSession.from_dict(r) for r in rows if isinstance(r, dict)
            ]
        except (OSError, ValueError, TypeError) as ex:
            _LOGGER.warning("SessionArchive: index load failed (%s); starting fresh", ex)
            self._index = []

    def _save_index(self) -> None:
        path = self._index_path()
        tmp = path.with_suffix(".json.tmp")
        payload = {
            "version": INDEX_VERSION,
            "sessions": [s.to_dict() for s in self._index],
        }
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp.replace(path)

    # -------------------- public API --------------------

    @property
    def root(self) -> Path:
        return self._root

    @property
    def count(self) -> int:
        return len(self._index)

    def latest(self) -> ArchivedSession | None:
        if not self._index:
            return None
        return max(self._index, key=lambda s: s.end_ts)

    def list_sessions(self) -> list[ArchivedSession]:
        """Return archived sessions ordered most-recent-first (by end_ts)."""
        return sorted(self._index, key=lambda s: s.end_ts, reverse=True)

    def has(self, md5: str) -> bool:
        return any(s.md5 == md5 for s in self._index)

    def archive(self, summary, raw_json: dict[str, Any] | None = None) -> ArchivedSession | None:
        """Persist one session summary. Idempotent by `summary.md5`.

        `raw_json` is the original JSON dict (written verbatim to disk for
        audit/replay). If omitted, a minimal reconstruction from the
        summary dataclass is stored instead — lossy but still useful.
        """
        md5 = str(getattr(summary, "md5", "") or "")
        if md5 and self.has(md5):
            return None

        end_ts = int(getattr(summary, "end_ts", 0))
        date_part = _format_date(end_ts)
        stem = f"{date_part}_{end_ts}_{md5[:8] or 'nohash'}.json"
        path = self._root / stem
        tmp = path.with_suffix(".json.tmp")
        try:
            if raw_json is not None:
                payload = raw_json
            else:
                payload = _summary_to_dict(summary)
            tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
            tmp.replace(path)
        except OSError as ex:
            _LOGGER.warning("SessionArchive: failed to write %s: %s", path, ex)
            return None

        entry = ArchivedSession.from_summary(filename=stem, summary=summary)
        self._index.append(entry)
        self._save_index()
        self._enforce_retention()
        return entry

    def _enforce_retention(self) -> None:
        """Prune oldest sessions beyond the configured cap.

        No-op when `self._retention` is 0 or None (unlimited). Otherwise
        keeps only the `_retention` most recent (by `end_ts`) entries
        on disk + in the index. Runs after every successful archive;
        typical cost is a single `path.unlink()` per mow once the
        archive is full.
        """
        keep = getattr(self, "_retention", 0)
        if not keep or keep <= 0:
            return
        if len(self._index) <= keep:
            return
        # Sort oldest-first, chop the excess from the front.
        sorted_idx = sorted(self._index, key=lambda s: s.end_ts)
        excess = len(sorted_idx) - keep
        to_drop = sorted_idx[:excess]
        for entry in to_drop:
            try:
                (self._root / entry.filename).unlink(missing_ok=True)
            except OSError as ex:
                _LOGGER.warning(
                    "SessionArchive: failed to prune %s: %s",
                    entry.filename,
                    ex,
                )
        # Keep only the most-recent `keep` entries in the in-memory
        # index and rewrite the index file.
        kept_files = {e.filename for e in sorted_idx[excess:]}
        self._index = [e for e in self._index if e.filename in kept_files]
        self._save_index()
        _LOGGER.info(
            "SessionArchive: pruned %d old session(s) past retention=%d",
            excess,
            keep,
        )

    def set_retention(self, keep: int) -> None:
        """Set the retention cap. 0 or negative means unlimited."""
        self._retention = int(keep) if keep else 0
        self._enforce_retention()

    def load(self, entry: ArchivedSession) -> dict[str, Any] | None:
        """Read the raw JSON of an archived session. None on error."""
        path = self._root / entry.filename
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError) as ex:
            _LOGGER.warning(
                "SessionArchive: failed to load %s: %s", entry.filename, ex
            )
            return None


# -------------------- helpers --------------------


def _format_date(unix_ts: int) -> str:
    if unix_ts <= 0:
        return "0000-00-00"
    try:
        return datetime.fromtimestamp(int(unix_ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return "0000-00-00"


def _summary_to_dict(summary) -> dict[str, Any]:
    """Lossy reconstruction of the session JSON from a SessionSummary.

    Only used as a fallback when the raw JSON isn't available at archive
    time. Not symmetric with the wire format (polygons are stored in
    metres, not cm). Re-parsing this through `parse_session_summary`
    will not yield the same result.
    """
    return {
        "start": summary.start_ts,
        "end": summary.end_ts,
        "time": summary.duration_min,
        "mode": summary.mode,
        "result": summary.result,
        "stop_reason": summary.stop_reason,
        "areas": summary.area_mowed_m2,
        "map_area": summary.map_area_m2,
        "md5": summary.md5,
        "dock": list(summary.dock) if summary.dock else None,
        "_note": (
            "Reconstructed from SessionSummary dataclass — geometry in metres, "
            "not cm. Not wire-compatible."
        ),
    }
