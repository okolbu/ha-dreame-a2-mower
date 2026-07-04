"""Cloud-write mixin for DreameA2CloudClient (P3.5 transport split).

Staging home for the three device WRITERS extracted from ``_fetchers.py``:
``set_cfg`` / ``set_pre`` (CFG routed-action writes) and
``trigger_firmware_update`` (OTA "update now"). All three return a
:class:`WriteResult` so callers can distinguish "the mower never heard it"
from "the mower heard it and said no".

P3.8 (domain-services extraction) relocates these to ``domain/writes``; this
mixin is the intermediate home so the move happens once.
"""
from __future__ import annotations

import time
from typing import Any

from ._helpers import _LOGGER, WriteResult


class _WritersMixin:

    def set_cfg(self, key: str, value: Any) -> WriteResult:
        """Write a single CFG key via routed-action s2 aiid=50.

        Wire format: ``{m: 's', t: key, d: <d_payload>}`` sent as
        ``in[0]`` of the siid=2 aiid=50 action call.

        ``value`` accepts two shapes:

        - **dict** — sent as ``d`` directly (named-key payload). Use
          this for complex CFG keys that take more than one slot:
          e.g. ``WRP {"value":1,"time":8,"sen":0}``,
          ``DND {"value":1,"time":[1200,480]}``,
          ``LIT {"value":1,"time":[480,1200],"light":[1,1,1,1],"fill":0}``.
          Source for the named-key catalog: ioBroker.dreame v0.3.7
          (see docs/research/wire-captures/iobroker-write-catalog-2026-05-09.md).
        - **anything else** — wrapped as ``{"value": value}``. This is
          the path for simple keys that take a single int / bool /
          all-bool list (CLS, VOL, FDP, STUN, AOP, PROT, ATA,
          MSG_ALERT, VOICE).

        The value MUST always end up wrapped under a ``value`` key —
        without it the device returns ``r=-3`` (not supported)
        inside the routed-action response and the cloud silently
        retains the old value (smoking-gun probe 2026-05-09 against
        all 16 known-writable CFG keys).

        Returns a :class:`WriteResult` (P2 Task 5 — was a bool). ``accepted``
        is True only when the device's routed-action response has
        ``out[0].r == 0`` — i.e. the device actually accepted the write.
        Pre-fix code only checked the top-level HTTP code which is always 0
        even when the device rejected the action. Outcome mapping:

        - ``out[0].r == 0``            → delivered + accepted (code 0).
        - ``out[0].r != 0``            → delivered + rejected (code=r,
          msg from msg/e). r=-3 is the device's "no setter for this key at
          this address" verdict — see ``inventory.yaml`` § READ/WRITE
          SURFACES note 1.
        - result is None               → not delivered (80001 / transport;
          code = ``_last_send_error_code``).
        - malformed response (non-dict / HTTP code != 0 / missing ``out``)
          → not delivered, no fabricated device code. Unlike
          ``routed_action`` (which treats a no-verdict envelope as accepted
          for *actions*), a **setting** write with no readable verdict must
          stay falsy: the caller reverts its optimistic state and the user
          retries — the pre-WriteResult behaviour, now with an honest
          retryable message.

        Wire-format coverage on g2408 (confirmed live 2026-05-09):

        Working with the wrapped {value: X} format (primitive callers):
        - Single int / bool: CLS, VOL, FDP, STUN, AOP, PROT
        - All-bool list[3]: ATA
        - All-bool list[4]: MSG_ALERT, VOICE

        Hypothesised to work with the named-key dict format (post-2026-05-09;
        verify per-key before relying on it):
        - WRP, DND, LOW, LIT — see ioBroker catalog above
        - CMS reset, PRE — full-array writes (separate set_pre helper)

        Still unknown wire format (no app-side reference):
        - BAT (list[6] mixed), REC (list[9] mixed), LANG (list[2] mixed)

        For unsupported shapes the device returns r=-3 and set_cfg
        returns a rejected WriteResult — the entity-layer caller's
        optimistic update is reverted.

        Source: probe `/tmp/probe_cfg_writes.py` 2026-05-09; full
        evidence in docs/research/wire-captures/cfg-write-regression-2026-05-09.md
        and the ioBroker catalog at iobroker-write-catalog-2026-05-09.md.
        """
        if isinstance(value, dict):
            d_payload: Any = value
        else:
            d_payload = {"value": value}
        payload = {"m": "s", "t": key, "d": d_payload}
        self._last_send_error_code = None
        try:
            result = self.action(siid=2, aiid=50, parameters=[payload])
            if result is None:
                _LOGGER.warning(
                    "set_cfg %s=%r: cloud returned None (80001?)", key, value
                )
                code = self._last_send_error_code
                return WriteResult(
                    delivered=False, accepted=False, code=code,
                    msg="not delivered (80001 — mower asleep/unreachable)"
                    if code == 80001 else "not delivered (transport)",
                )
            if not isinstance(result, dict):
                _LOGGER.warning(
                    "set_cfg %s=%r: unexpected response shape: %r",
                    key, value, result,
                )
                return WriteResult.not_delivered("unexpected response shape")
            # HTTP-layer code = always 0 on a reachable cloud; the actual
            # action result is in `out[0].r`.
            top_code = result.get("code")
            if top_code is not None and top_code != 0:
                _LOGGER.warning(
                    "set_cfg %s=%r: cloud HTTP error code %s", key, value, top_code,
                )
                return WriteResult(
                    delivered=False, accepted=False, code=top_code,
                    msg=f"cloud HTTP error code {top_code}",
                )
            outs = result.get("out") or []
            if not outs or not isinstance(outs[0], dict):
                _LOGGER.warning(
                    "set_cfg %s=%r: missing or malformed `out` in response: %r",
                    key, value, result,
                )
                return WriteResult.not_delivered("no device verdict in response")
            r = outs[0].get("r")
            if r != 0:
                msg = outs[0].get("msg") or outs[0].get("e") or ""
                _LOGGER.warning(
                    "set_cfg %s=%r: device rejected (out[0].r=%r msg=%r). "
                    "Wire format may be wrong for this CFG key — see "
                    "docs/research/wire-captures/cfg-write-regression-2026-05-09.md",
                    key, value, r, msg,
                )
                return WriteResult(delivered=True, accepted=False, code=r, msg=msg)
            return WriteResult(delivered=True, accepted=True, code=0)
        except Exception as ex:
            _LOGGER.warning("set_cfg %s=%r failed: %s", key, value, ex)
            return WriteResult.not_delivered(str(ex))

    def set_pre(self, pre_array: list) -> WriteResult:
        """Write the full PRE preferences array.

        Delegates to ``protocol.cfg_action.set_pre`` which constructs the
        routed-action envelope ``{m:'s', t:'PRE', d:<bare array>}``.
        The ``d`` field is the array itself — NOT wrapped under ``value``.

        The caller is responsible for read-modify-write semantics: read the
        current PRE array via fetch_cfg(), mutate the target element, and
        pass the full updated array here.

        Returns a :class:`WriteResult` (P2 Task 5 — was a bool) whose
        ``accepted`` is True only when the device's routed-action response
        has ``out[0].r == 0``. The HTTP-layer ``code`` is always 0 on a
        reachable cloud even when the device rejects the action, so a
        shallow ``result is not None`` check reports false success — the
        same bug class as the pre-v1.0.2a9 ``set_cfg``. We parse
        ``out[0].r`` here just like ``set_cfg`` does, with the same
        outcome mapping (see ``set_cfg``'s docstring).

        Prior r=-3 verdict debunked (2026-06-09 app MITM capture): the
        original code wrapped the array as ``d:{"value": pre_array}``, and
        the device returned ``r=-3`` on every write.  The app sends the bare
        array ``d:[...]`` and the device accepts it (r=0).  The r=-3 was a
        wrong-envelope artifact, not evidence that g2408 has no PRE setter.
        See docs/research/wire-captures/pre-write-r3-2026-06-03.md (the
        old -3 evidence) and the 2026-06-09 app-capture findings.

        Source: protocol/cfg_action.py set_pre(); docs/research/g2408-protocol.md §6.2.
        """
        from ..protocol import cfg_action  # type: ignore[import]

        self._last_send_error_code = None
        try:
            result = cfg_action.set_pre(self.action, pre_array)
            if result is None:
                _LOGGER.warning("set_pre: cloud returned None (80001?)")
                code = self._last_send_error_code
                return WriteResult(
                    delivered=False, accepted=False, code=code,
                    msg="not delivered (80001 — mower asleep/unreachable)"
                    if code == 80001 else "not delivered (transport)",
                )
            if not isinstance(result, dict):
                _LOGGER.warning(
                    "set_pre: unexpected response shape: %r", result
                )
                return WriteResult.not_delivered("unexpected response shape")
            top_code = result.get("code")
            if top_code is not None and top_code != 0:
                _LOGGER.warning("set_pre: cloud HTTP error code %s", top_code)
                return WriteResult(
                    delivered=False, accepted=False, code=top_code,
                    msg=f"cloud HTTP error code {top_code}",
                )
            outs = result.get("out") or []
            if not outs or not isinstance(outs[0], dict):
                _LOGGER.warning(
                    "set_pre: missing or malformed `out` in response: %r", result
                )
                return WriteResult.not_delivered("no device verdict in response")
            r = outs[0].get("r")
            if r != 0:
                msg = outs[0].get("msg") or outs[0].get("e") or ""
                _LOGGER.warning(
                    "set_pre: device rejected (out[0].r=%r msg=%r) — envelope is "
                    "the app's bare array; non-zero r is a genuine device rejection",
                    r, msg,
                )
                return WriteResult(delivered=True, accepted=False, code=r, msg=msg)
            return WriteResult(delivered=True, accepted=True, code=0)
        except ValueError as ex:
            _LOGGER.warning("set_pre: invalid array: %s", ex)
            return WriteResult.not_delivered(f"invalid PRE array: {ex}")
        except Exception as ex:
            _LOGGER.warning("set_pre failed: %s", ex)
            return WriteResult.not_delivered(str(ex))

    def trigger_firmware_update(self) -> WriteResult:
        """"Update now" trigger — POST iotuserbind/manualFirmwareUpdate.

        Returns a :class:`WriteResult` (P3.5 — was a bool; given WriteResult on
        the way to domain/writes per the P2-inherit OTA-honesty note). Its
        ``accepted`` mirrors the device's own verdict — the INNER
        ``data.success``. The outer ``success`` only means the API received the
        call; ``accepted=False`` (with ``delivered=True``) means the device
        refused (weak WiFi / not charging — gated device-side). A None /
        non-dict / missing-field / transport error is a NOT-delivered
        WriteResult (the mower never heard the command).

        ``WriteResult.__bool__`` is tied to ``accepted``, so the existing
        ``bool(...)`` caller (``coordinator.async_trigger_firmware_update``)
        keeps the identical pre-WriteResult truthiness — refused OR
        not-delivered both read falsy, delivered+accepted reads truthy.

        Auth: Dreame-Auth bearer (via ``request()``), no ``sign`` (see
        ``_ota.fetch_ota_version``). Body carries ``did``, ``uid``, and a
        millisecond ``timestamp``.

        Source: app-mitm 2026-06-16; inventory.yaml § ota.manualFirmwareUpdate.
        """
        url = f"{self.get_api_url()}/dreame-user-iot/iotuserbind/manualFirmwareUpdate"
        body = {
            "did": str(self._did),
            "uid": str(self._uid),
            "timestamp": int(time.time() * 1000),
        }
        try:
            import json as _json
            resp = self.request(
                url, _json.dumps(body), content_type="application/json"
            )
        except Exception as ex:  # noqa: BLE001 — defensive
            _LOGGER.warning("trigger_firmware_update: %s", ex)
            return WriteResult.not_delivered(str(ex))
        if not isinstance(resp, dict):
            return WriteResult.not_delivered("unexpected response shape")
        data = resp.get("data")
        if not isinstance(data, dict):
            return WriteResult.not_delivered("no `data` field in response")
        if bool(data.get("success")):
            return WriteResult(delivered=True, accepted=True, code=0)
        return WriteResult(
            delivered=True, accepted=False, code=None,
            msg="device refused OTA (weak WiFi / not charging — gated device-side)",
        )
