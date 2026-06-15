"""Normalize Dreame message-center records into one shape.

Pure module (no I/O). Three upstream sources feed the dashboard "Info" tab:

  - service  — v1 message-record/list serviceMsg.msgRecord
               (multiLangDisplay JSON, readStatus, createTime)  [verified]
  - device   — device-messages/v2 content[] (messageId, string sendTime,
               localizationContents:{en}; no reliable read flag) [verified]
  - share    — /dreame-messaging/user/share-messages             [field names
               confirmed by live capture — see the plan's Task 7]

Each becomes a ``Message``; ``date`` is ISO-8601 UTC. Newest first.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Message:
    id: str
    title: str
    date: str | None
    body: str | None
    link: str | None
    unread: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "date": self.date,
            "body": self.body,
            "link": self.link,
            "unread": self.unread,
        }


def _iso(ts: Any) -> str | None:
    """Epoch seconds/ms OR a 'YYYY-MM-DD HH:MM:SS' string → ISO-8601 UTC, or None."""
    if ts is None:
        return None
    # Numeric epoch (int/float, or a numeric string).
    try:
        v = float(ts)
    except (TypeError, ValueError):
        v = None
    if v is not None:
        if v > 1e11:  # milliseconds
            v /= 1000.0
        try:
            return datetime.fromtimestamp(v, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    # String datetime (device-messages/v2 sendTime), assumed UTC.
    if isinstance(ts, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                continue
    return None


def _en_display(rec: dict) -> dict:
    """Decode multiLangDisplay JSON → the en (or first) lang dict."""
    raw = rec.get("multiLangDisplay")
    if not raw:
        return {}
    try:
        disp = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return {}
    if not isinstance(disp, dict):
        return {}
    return disp.get("en") or next((v for v in disp.values() if isinstance(v, dict)), {})


def _sorted_newest_first(items: list[tuple[Any, Message]]) -> list[Message]:
    """Sort (sort_key, Message) by key desc; None keys sort last."""
    return [
        m
        for _, m in sorted(
            items, key=lambda t: (t[0] is not None, t[0] or 0), reverse=True
        )
    ]


def normalize_service(records: list[dict] | None) -> list[Message]:
    out: list[tuple[Any, Message]] = []
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        en = _en_display(rec)
        ts = rec.get("createTime") or rec.get("sendTime")
        out.append(
            (
                ts,
                Message(
                    id=str(rec.get("id") or rec.get("messageId") or ""),
                    title=str(en.get("name") or ""),
                    date=_iso(ts),
                    body=en.get("content") or None,
                    link=en.get("link") or None,
                    unread=not bool(rec.get("readStatus")),
                ),
            )
        )
    return _sorted_newest_first(out)


def normalize_device(records: list[dict] | None) -> list[Message]:
    out: list[tuple[Any, Message]] = []
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        loc = rec.get("localizationContents")
        text = None
        if isinstance(loc, dict):
            text = loc.get("en") or loc.get("en-US")
        ts = rec.get("sendTime") or rec.get("createTime")
        out.append(
            (
                ts,
                Message(
                    id=str(rec.get("messageId") or rec.get("id") or ""),
                    title=str(text or ""),
                    date=_iso(ts),
                    # Device-messages/v2 carries the whole text in one
                    # localization string — no separate body/link.
                    body=None,
                    link=None,
                    # No reliable read flag → treat all as unread.
                    unread=True,
                ),
            )
        )
    return _sorted_newest_first(out)


def normalize_share(records: list[dict] | None) -> list[Message]:
    out: list[tuple[Any, Message]] = []
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        en = _en_display(rec)
        ts = rec.get("createTime") or rec.get("sendTime") or rec.get("time")
        title = (
            en.get("name")
            or rec.get("title")
            or rec.get("content")
            or rec.get("message")
            or ""
        )
        out.append(
            (
                ts,
                Message(
                    id=str(rec.get("id") or rec.get("messageId") or ""),
                    title=str(title),
                    date=_iso(ts),
                    body=(en.get("content") or rec.get("content") or None),
                    link=(en.get("link") or rec.get("link") or None),
                    unread=not bool(rec.get("readStatus") or rec.get("read")),
                ),
            )
        )
    return _sorted_newest_first(out)


def unread_count(messages: list[Message]) -> int:
    return sum(1 for m in messages if m.unread)
