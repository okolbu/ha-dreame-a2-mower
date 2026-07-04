"""Account/device message-store fetchers for DreameA2CloudClient (P3.5 split).

The three cloud message surfaces:
- ``fetch_device_messages`` — per-device push store (the app's A2 tab).
- ``fetch_message_record``  — account system + service message counts.
- ``fetch_share_messages``  — the sharing tab.
"""
from __future__ import annotations

import time
from typing import Any

from ._helpers import _LOGGER


class _MessagesMixin:

    def fetch_device_messages(
        self, did: str | int, page_size: int = 10,
    ) -> list[dict[str, Any]] | None:
        """Fetch the per-device cloud notification store (the app's A2 tab).

        GET ``/dreame-messaging/user/device-messages/v2?did=<did>&pageNum=1&pageSize=N``.
        Server caps `page_size` at 10 and ignores pagination (pageNum 2+ returns
        the same latest-10) [probe@2026-06-18] — this is a
        moving window of the latest N pushes for `did`. Each record carries
        `source={siid,piid,value,eiid,aiid}` (values as STRING), multilingual
        `localizationContents`, `sendTime` (str "YYYY-MM-DD HH:MM:SS"),
        `readTime`, and `messageId` (the dedup key).

        Returns the parsed `data.content` list on success, or `None` on
        any failure (no token, HTTP error, JSON parse error, non-zero code).
        Logs at warning level.

        See docs/research/app-api-surface-2026-05-25.md § device-messages/v2.
        """
        strings = self._ensure_strings()
        if self._key_expire and time.time() > self._key_expire:
            self.login()
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            strings[47]: strings[3],
            strings[49]: strings[5],
            strings[50]: self._ti if self._ti else strings[6],
            strings[51]: strings[52],
            strings[46]: self._key,
        }
        if self._country == "cn":
            headers[strings[48]] = strings[4]
        url = f"{self.get_api_url()}/dreame-messaging/user/device-messages/v2"
        try:
            resp = self._session.get(
                url,
                headers=headers,
                params={"did": str(did), "pageNum": 1, "pageSize": page_size},
                timeout=15,
            )
        except Exception as ex:  # noqa: BLE001 — defensive
            _LOGGER.warning("fetch_device_messages: request failed: %s", ex)
            return None
        if resp.status_code != 200:
            _LOGGER.warning(
                "fetch_device_messages: HTTP %d (body: %s)",
                resp.status_code, resp.text[:200],
            )
            return None
        try:
            body = resp.json()
        except Exception as ex:  # noqa: BLE001
            _LOGGER.warning("fetch_device_messages: JSON parse failed: %s", ex)
            return None
        if not isinstance(body, dict) or body.get("code") not in (0, 200):
            _LOGGER.debug(
                "fetch_device_messages: non-zero response code: %r msg=%r",
                body.get("code"), body.get("msg"),
            )
            return None
        records = (body.get("data") or {}).get("content")
        return records if isinstance(records, list) else None

    def fetch_message_record(self) -> dict | None:
        """System + service messages via /dreame-message-push/v1/message-record/list.

        Returns ``{service_unread, system_unread, latest}`` where ``latest``
        is the ``en.name`` of the first serviceMsg record (or ``None``).
        Returns ``None`` on any failure.
        """
        self._ensure_strings()
        if getattr(self, "_key_expire", None) and time.time() > self._key_expire:
            self.login()
        strings = getattr(self, "_strings", None) or self.strings
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            strings[47]: strings[3],
            strings[49]: strings[5],
            strings[50]: getattr(self, "_ti", None) or strings[6],
            strings[51]: strings[52],
            strings[46]: getattr(self, "_key", ""),
        }
        if getattr(self, "_country", None) == "cn":
            headers[strings[48]] = strings[4]
        try:
            url = f"{self.get_api_url()}/dreame-message-push/v1/message-record/list"
            resp = self._session.get(
                url,
                headers=headers,
                params={"version": "v1"},
                timeout=10,
            )
            if resp.status_code != 200:
                _LOGGER.warning("fetch_message_record: HTTP %d (body: %s)", resp.status_code, resp.text[:200])
                return None
            body = resp.json()
        except Exception as ex:  # pragma: no cover
            _LOGGER.warning("fetch_message_record: %s", ex)
            return None
        data = (body or {}).get("data") or {}
        svc = data.get("serviceMsg") or {}
        sysm = data.get("systemMsg") or {}
        latest = None
        recs = svc.get("msgRecord") or []
        if recs and isinstance(recs[0], dict):
            import json as _json
            try:
                disp = _json.loads(recs[0].get("multiLangDisplay") or "{}")
                en = disp.get("en") or next(iter(disp.values()), {})
                latest = (en or {}).get("name")
            except (ValueError, TypeError):
                latest = None
        return {
            "service_unread": svc.get("unread"),
            "system_unread": sysm.get("unread"),
            "latest": latest,
            "service_records": recs,
        }

    def fetch_share_messages(self, limit: int = 100, offset: int = 0) -> list | None:
        """Sharing-tab messages via /dreame-messaging/user/share-messages.

        GET …/share-messages?version=v1&limit=<limit>&offset=<offset>.
        Returns the raw record list (data.content), or None on failure.
        Logs at WARNING; does not raise.
        """
        self._ensure_strings()
        if getattr(self, "_key_expire", None) and time.time() > self._key_expire:
            self.login()
        strings = getattr(self, "_strings", None) or self.strings
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            strings[47]: strings[3],
            strings[49]: strings[5],
            strings[50]: getattr(self, "_ti", None) or strings[6],
            strings[51]: strings[52],
            strings[46]: getattr(self, "_key", ""),
        }
        if getattr(self, "_country", None) == "cn":
            headers[strings[48]] = strings[4]
        try:
            url = f"{self.get_api_url()}/dreame-messaging/user/share-messages"
            resp = self._session.get(
                url,
                headers=headers,
                params={"version": "v1", "limit": limit, "offset": offset},
                timeout=10,
            )
            if resp.status_code != 200:
                _LOGGER.warning(
                    "fetch_share_messages: HTTP %d (body: %s)",
                    resp.status_code, resp.text[:200],
                )
                return None
            body = resp.json()
        except Exception as ex:  # pragma: no cover
            _LOGGER.warning("fetch_share_messages: %s", ex)
            return None
        if not isinstance(body, dict) or body.get("code") not in (0, 200):
            _LOGGER.debug(
                "fetch_share_messages: non-zero response code: %r msg=%r",
                (body or {}).get("code") if isinstance(body, dict) else None,
                (body or {}).get("msg") if isinstance(body, dict) else None,
            )
            return None
        records = body.get("data") or {}
        recs = records.get("content") if isinstance(records, dict) else None
        return recs if isinstance(recs, list) else None
