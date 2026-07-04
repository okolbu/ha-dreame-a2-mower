"""OSS media-listing + quota fetchers for DreameA2CloudClient (P3.5 split)."""
from __future__ import annotations

import time

from ._helpers import _LOGGER


class _MediaMixin:

    def list_oss_media(self, media_type: str, *, size: int = 12, max_pages: int = 20) -> list | None:
        """List OSS media via iotoss/userDidOssList. media_type 'jpg' (photos) or
        'thumb' (videos). Paged; returns all records or None. Records carry
        server-signed `filepath` (+ `videoPath` for thumb)."""
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
        out: list = []
        for page in range(1, max_pages + 1):
            try:
                url = f"{self.get_api_url()}/dreame-user-iot/iotoss/userDidOssList?current={page}&size={size}"
                resp = self._session.post(url, headers=headers,
                                          json={"did": str(self._did), "type": media_type}, timeout=10)
                if resp.status_code != 200:
                    return out or None
                body = resp.json()
            except Exception as ex:  # pragma: no cover
                _LOGGER.warning("list_oss_media(%s): %s", media_type, ex)
                return out or None
            recs = ((body or {}).get("data") or {}).get("records")
            if recs is None:
                recs = (body or {}).get("records")
            if not recs:
                break
            out.extend(recs)
            if len(recs) < size:
                break
        return out or None

    def fetch_oss_quota(self) -> dict | None:
        """OSS storage quota via iotoss/checkDevOssStorage → {total, used} bytes."""
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
            url = f"{self.get_api_url()}/dreame-user-iot/iotoss/checkDevOssStorage"
            resp = self._session.post(url, headers=headers,
                                      json={"did": str(self._did)}, timeout=10)
            if resp.status_code != 200:
                return None
            data = (resp.json() or {}).get("data") or {}
        except Exception as ex:  # pragma: no cover
            _LOGGER.warning("fetch_oss_quota: %s", ex)
            return None
        try:
            return {"total": int(data["total"]), "used": int(data["used"])}
        except (KeyError, TypeError, ValueError):
            return None
