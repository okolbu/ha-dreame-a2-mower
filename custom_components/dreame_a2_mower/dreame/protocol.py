import logging
import random
import hashlib
import json
import base64
import hmac
import requests
import zlib
import ssl
import queue
from threading import Thread, Timer
from time import sleep
import time
import locale
from datetime import datetime
from paho.mqtt import client as mqtt_client
from typing import Any, Dict, Optional, Tuple
from .exceptions import DeviceException
from .const import DREAME_STRINGS


def _random_agent_id() -> str:
    """Module-level helper used by the Dreame cloud MQTT client-id
    factory. Formerly `DreameMowerMiHomeCloudProtocol.get_random_agent_id`
    — kept as a plain function now that the Mi cloud class is gone
    (Phase 2 cleanup, v2.0.0-alpha.33)."""
    import random
    letters = "ABCDEF"
    return "".join(random.choice(letters) for _ in range(13))

_LOGGER = logging.getLogger(__name__)


# DreameMowerDeviceProtocol (local-LAN miIO path via python-miio)
# removed 2026-04-20, Cleanup Phase 2. The A2 uses cloud-push MQTT
# only; there was never a local LAN token available for this device
# family, so the class was permanently dead code.


class DreameMowerDreameHomeCloudProtocol:
    def __init__(self, username: str, password: str, country: str = "cn", did: str = None) -> None:
        self.two_factor_url = None
        self._username = username
        self._password = password
        self._country = country
        self._location = country
        self._did = did
        self._session = requests.session()
        self._queue = queue.Queue()
        self._thread = None
        self._id = random.randint(1, 100)
        self._reconnect_timer = None
        self._host = None
        self._model = None
        self._ti = None
        self._fail_count = 0
        self._connected = False
        self._client_connected = False
        self._client_connecting = False
        self._client = None
        self._message_callback = None
        self._connected_callback = None
        self._mqtt_archive = None
        self._logged_in = None
        self._stream_key = None
        self._client_key = None
        self._secondary_key = None
        self._key_expire = None
        self._key = None
        self._uid = None
        self._uuid = None
        self._strings = None

    def _api_task(self):
        while True:
            item = self._queue.get()
            if len(item) == 0:
                self._queue.task_done()
                return
            item[0](self._api_call(item[1], item[2], item[3]))
            sleep(0.1)
            self._queue.task_done()

    def _api_call_async(self, callback, url, params=None, retry_count=2):
        if self._thread is None:
            self._thread = Thread(target=self._api_task, daemon=True)
            self._thread.start()

        self._queue.put((callback, url, params, retry_count))

    def _api_call(self, url, params=None, retry_count=2):
        return self.request(
            f"{self.get_api_url()}/{url}",
            json.dumps(params, separators=(",", ":")
                       ) if params is not None else None,
            retry_count,
        )

    def get_api_url(self) -> str:
        return f"https://{self._country}{self._strings[0]}:{self._strings[1]}"

    @property
    def device_id(self) -> str:
        return self._did

    @property
    def dreame_cloud(self) -> bool:
        return True

    @property
    def object_name(self) -> str:
        return f"{self._model}/{self._uid}/{str(self._did)}/0"

    @property
    def logged_in(self) -> bool:
        return self._logged_in

    @property
    def connected(self) -> bool:
        return self._connected and self._client_connected

    def _reconnect_timer_cancel(self):
        if self._reconnect_timer is not None:
            self._reconnect_timer.cancel()
            del self._reconnect_timer
            self._reconnect_timer = None

    def _reconnect_timer_task(self):
        self._reconnect_timer_cancel()
        if self._client_connecting and self._client_connected:
            self._client_connected = False
            _LOGGER.warn("Device client reconnect failed! Retrying...")

    def _set_client_key(self) -> bool:
        if self._client_key != self._key:
            self._client_key = self._key
            self._client.username_pw_set(self._uuid, self._client_key)
            return True
        return False

    @staticmethod
    def _on_client_connect(client, self, flags, rc):
        self._client_connecting = False
        self._reconnect_timer_cancel()
        if rc == 0:
            if not self._client_connected:
                self._client_connected = True
                _LOGGER.info("Connected to the device client")
            client.subscribe(
                f"/{self._strings[7]}/{self._did}/{self._uid}/{self._model}/{self._country}/")
            if self._connected_callback:
                try:
                    self._connected_callback()
                except:
                    pass
        else:
            _LOGGER.warn("Device client connection failed: %s", rc)
            if not self._set_client_key():
                self._client_connected = False

    @staticmethod
    def _on_client_disconnect(client, self, rc):
        if rc != 0 and not self._set_client_key():
            if rc == 5 and self._key_expire:
                self.login()
            if self._client_connected:
                if not self._client_connecting:
                    self._client_connecting = True
                    _LOGGER.info(
                        "Device Client disconnected (%s) Reconnecting...", rc)
                self._reconnect_timer_cancel()
                self._reconnect_timer = Timer(10, self._reconnect_timer_task)
                self._reconnect_timer.start()

    @staticmethod
    def _on_client_message(client, self, message):
        # Mirror the raw on-wire payload to the JSONL archive — always
        # first so even malformed messages are captured. Never let an
        # archive failure propagate; observability must not break the
        # live pipeline.
        if self._mqtt_archive is not None:
            try:
                self._mqtt_archive.write(
                    topic=getattr(message, "topic", "?"),
                    payload=message.payload,
                )
            except Exception as ex:
                _LOGGER.warning("MQTT archive write failed: %s", ex)

        if self._message_callback:
            try:
                response = json.loads(message.payload.decode("utf-8"))
            except Exception as ex:
                # Was silently swallowed; undecodable payloads used to vanish
                # without trace. Log at WARNING with payload as hex so anything
                # non-JSON can be recovered for analysis.
                try:
                    sample = message.payload[:200].hex()
                except Exception:
                    sample = "<unreadable>"
                _LOGGER.warning(
                    "[UNKNOWN] MQTT payload on topic %s did not decode as JSON "
                    "(%s); first 200 bytes hex=%s",
                    getattr(message, "topic", "?"),
                    ex,
                    sample,
                )
                return
            if "data" in response and response["data"]:
                self._message_callback(response["data"])
            else:
                _LOGGER.debug(
                    "MQTT message without 'data' field on topic %s: %s",
                    getattr(message, "topic", "?"),
                    response,
                )

    def _handle_device_info(self, info):
        self._uid = info[self._strings[8]]
        self._did = info["did"]
        self._model = info[self._strings[35]]
        self._host = info[self._strings[9]]
        _LOGGER.info(
            "cloud _handle_device_info: did=%r model=%r _host=%r",
            self._did, self._model, self._host,
        )
        prop = info[self._strings[10]]
        if prop and prop != "":
            prop = json.loads(prop)
            if self._strings[11] in prop:
                self._stream_key = prop[self._strings[11]]

    def connect(self, message_callback=None, connected_callback=None):
        if self._logged_in:
            info = self.get_device_info()
            if info:
                if message_callback:
                    self._message_callback = message_callback
                    self._connected_callback = connected_callback
                    if self._client is None:
                        _LOGGER.info("Connecting to the device client")
                        try:
                            host = self._host.split(":")
                            self._client = mqtt_client.Client(
                                mqtt_client.CallbackAPIVersion.VERSION1,
                                f"{self._strings[53]}{self._uid}{self._strings[54]}{_random_agent_id()}{self._strings[54]}{host[0]}",
                                clean_session=True,
                                userdata=self,
                            )
                            self._client.on_connect = DreameMowerDreameHomeCloudProtocol._on_client_connect
                            self._client.on_disconnect = DreameMowerDreameHomeCloudProtocol._on_client_disconnect
                            self._client.on_message = DreameMowerDreameHomeCloudProtocol._on_client_message
                            self._client.reconnect_delay_set(1, 15)
                            self._client.tls_set(cert_reqs=ssl.CERT_NONE)
                            self._client.tls_insecure_set(True)
                            self._set_client_key()
                            self._client.connect(host[0], int(host[1]), 50)
                            self._client.loop_start()
                        except Exception as e:
                            _LOGGER.error("Connect failed. error: %s", e)
                            pass
                    elif not self._client_connected:
                        self._set_client_key()
                self._connected = True
                return info
        return None

    def login(self) -> bool:
        self._session.close()
        self._session = requests.session()
        self._logged_in = False

        if self._strings is None:
            self._strings = json.loads(zlib.decompress(
                base64.b64decode(DREAME_STRINGS), zlib.MAX_WBITS | 32))

        try:
            if self._secondary_key:
                data = f"{self._strings[12]}{self._strings[13]}{self._secondary_key}"
            else:
                data = f"{self._strings[12]}{self._strings[14]}{self._username}{self._strings[15]}{hashlib.md5((self._password + self._strings[2]).encode('utf-8')).hexdigest()}{self._strings[16]}"

            headers = {
                "Accept": "*/*",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept-Language": "en-US;q=0.8",
                "Accept-Encoding": "gzip, deflate",
                self._strings[47]: self._strings[3],
                self._strings[49]: self._strings[5],
                self._strings[50]: self._ti if self._ti else self._strings[6],
            }

            if self._country == "cn":
                headers[self._strings[48]] = self._strings[4]

            response = self._session.post(
                self.get_api_url() + self._strings[17],
                headers=headers,
                data=data,
                timeout=10,
            )
            if response.status_code == 200:
                data = json.loads(response.text)
                if self._strings[18] in data:
                    self._key = data.get(self._strings[18])
                    self._secondary_key = data.get(self._strings[19])
                    self._key_expire = time.time(
                    ) + data.get(self._strings[20]) - 120
                    self._logged_in = True
                    self._uuid = data.get("uid")
                    self._location = data.get(
                        self._strings[21], self._location)
                    self._ti = data.get(self._strings[22], self._ti)
            else:
                try:
                    data = json.loads(response.text)
                    if "error_description" in data and "refresh token" in data["error_description"]:
                        self._secondary_key = None
                        return self.login()
                except:
                    pass
                _LOGGER.error("Login failed: %s", response.text)
        except requests.exceptions.Timeout:
            response = None
            _LOGGER.warning("Login Failed: Read timed out. (read timeout=10)")
        except Exception as ex:
            response = None
            _LOGGER.error("Login failed: %s", str(ex))

        if self._logged_in:
            self._fail_count = 0
            self._connected = True
        return self._logged_in

    def get_devices(self) -> Any:
        response = self._api_call(
            f"{self._strings[23]}/{self._strings[24]}/{self._strings[27]}/{self._strings[28]}")
        if response:
            if "data" in response and response["code"] == 0:
                return response["data"]
        return None

    def get_device_info(self) -> Any:
        response = self._api_call(
            f"{self._strings[23]}/{self._strings[24]}/{self._strings[27]}/{self._strings[29]}",
            {"did": self._did},
        )
        if response and "data" in response and response["code"] == 0:
            data = response["data"]
            self._handle_device_info(data)
            response = self._api_call(
                f"{self._strings[23]}/{self._strings[25]}/{self._strings[30]}",
                {"did": self._did},
            )
            if response and "data" in response and response["code"] == 0:
                if self._strings[31] in response["data"]:
                    data = {
                        **response["data"][self._strings[31]][self._strings[32]],
                        **data,
                    }
                else:
                    _LOGGER.warning(
                        "Get Device OTC Info empty, trying fallback... (%s)", response)
                    devices = self.get_devices()
                    if devices is not None:
                        found = list(
                            filter(
                                lambda d: str(d["did"]) == self._did,
                                devices[self._strings[34]][self._strings[36]],
                            )
                        )
                        if len(found) > 0:
                            self._handle_device_info(found[0])
                            return found[0]
                    _LOGGER.warning(
                        "Get Device OTC Info fallback failed, proceeding with basic device info")
                    return data
            return data
        return None

    def get_info(self, mac: str) -> Tuple[Optional[str], Optional[str]]:
        if self._did is not None:
            return " ", self._host
        devices = self.get_devices()
        if devices is not None:
            found = list(
                filter(
                    lambda d: str(d["mac"]) == mac,
                    devices[self._strings[34]][self._strings[36]],
                )
            )
            if len(found) > 0:
                self._handle_device_info(found[0])
                return " ", self._host
        return None, None

    def send_async(self, callback, method, parameters, retry_count: int = 2):
        host = ""
        if self._host and len(self._host):
            host = f"-{self._host.split('.')[0]}"
        # Mirror send()'s action-call URL fix (alpha.78/80): when the
        # call is an action and derived host is empty or non-numeric,
        # fall back to the apk-hardcoded Dreame iotComPrefix '-10000'
        # + force HTTPS. Required to avoid 404 when action_async fires
        # before _handle_device_info has populated _host.
        if method == "action" and (not host or not host.lstrip("-").isdigit()):
            host = "-10000"

        self._id = self._id + 1
        url = f"{self._strings[37]}{host}/{self._strings[27]}/{self._strings[38]}"
        if method == "action" and url.startswith("http://"):
            url = "https://" + url[len("http://"):]
        self._api_call_async(
            lambda api_response: callback(
                None
                if api_response is None or "data" not in api_response or not api_response["data"] or "result" not in api_response["data"]
                else api_response["data"]["result"]
            ),
            url,
            {
                "did": str(self._did),
                "id": self._id,
                "data": {
                    "did": str(self._did),
                    "id": self._id,
                    "method": method,
                    "params": parameters,
                    "from": "XXXXXX",
                },
            },
            retry_count,
        )

    def send(self, method, parameters, retry_count: int = 2) -> Any:
        host = ""
        if self._host and len(self._host):
            host = f"-{self._host.split('.')[0]}"
        # Fallback for Dreame brand: apk hardcodes iotComPrefix='10000'
        # in BRAND_CONFIG. If bind info didn't yield a numeric prefix,
        # use it anyway — the /dreame-iot-com/ path (no suffix) returns
        # 404 on g2408 for siid:2 aiid:50 calls; /dreame-iot-com-10000/
        # is the apk-documented form. Only applies to action calls so
        # existing property/data calls are unaffected.
        original_host = host
        if method == "action" and (not host or not host.lstrip("-").isdigit()):
            host = "-10000"
        url = f"{self._strings[37]}{host}/{self._strings[27]}/{self._strings[38]}"
        if method == "action":
            # Force HTTPS for action calls: apk uses https://, our
            # strings[37] compiles to http://. Existing map/data
            # fetches are left untouched to avoid breaking them.
            if url.startswith("http://"):
                url = "https://" + url[len("http://"):]
            _LOGGER.debug(
                "cloud action URL: %s (derived host=%r final host=%r _host=%r)",
                url, original_host, host, self._host,
            )

        attempts = 3 if method == "action" else 1
        for attempt in range(attempts):
            self._id = self._id + 1
            api_response = self._api_call(
                url,
                {
                    "did": str(self._did),
                    "id": self._id,
                    "data": {
                        "did": str(self._did),
                        "id": self._id,
                        "method": method,
                        "params": parameters,
                        "from": "XXXXXX",
                    },
                },
                retry_count,
            )
            if api_response and "data" in api_response and api_response["data"] and "result" in api_response["data"]:
                return api_response["data"]["result"]

            error_code = api_response.get("code") if api_response else None
            if error_code:
                _LOGGER.warning(
                    "Cloud send error %s for %s (attempt %d/%d): %s",
                    error_code, method, attempt + 1, attempts, api_response.get("msg", ""))
                # 80001 = "device unreachable via cloud relay". On devices
                # where the cloud consistently can't reach the mower
                # (verified on g2408, B1 — every single action during
                # mowing returned 80001 too), retrying burns ~32 s per
                # call (3 attempts × ~8 s gap) with zero chance of a
                # different outcome. Break out fast on this specific
                # code so boot stays under a few seconds. Other error
                # codes (transient HTTP 5xx, etc.) still get the
                # retry-with-backoff path.
                if method == "action" and error_code != 80001 and attempt < attempts - 1:
                    sleep(8)
                    continue
            break
        return None

    def get_file(self, url: str, retry_count: int = 4) -> Any:
        retries = 0
        if not retry_count or retry_count < 0:
            retry_count = 0
        while retries < retry_count + 1:
            try:
                response = self._session.get(url, timeout=15)
            except Exception as ex:
                response = None
                _LOGGER.warning("Unable to get file at %s: %s", url, ex)
            if response is not None and response.status_code == 200:
                return response.content
            retries = retries + 1
        return None

    def attach_mqtt_archive(self, archive) -> None:
        """Install an MQTT archive for raw JSONL capture.

        See :class:`protocol.mqtt_archive.MqttArchive`. Called by the
        coordinator when the ``mqtt_archive`` option is enabled on the
        config entry. The archive sees every payload that arrives on
        the paho callback thread, before JSON decoding.
        """
        self._mqtt_archive = archive

    def get_file_url(self, object_name: str = "") -> Any:
        api_response = self._api_call(
            f"{self._strings[23]}/{self._strings[39]}/{self._strings[56]}",
            {
                "did": str(self._did),
                "uid": str(self._uid),
                self._strings[35]: self._model,
                "filename": object_name[1:],
                self._strings[21]: self._country,
            },
        )
        if api_response is None or "data" not in api_response:
            return None

        return api_response["data"]

    def get_interim_file_url(self, object_name: str = "") -> str:
        api_response = self._api_call(
            f"{self._strings[23]}/{self._strings[39]}/{self._strings[55]}",
            {
                "did": str(self._did),
                self._strings[35]: self._model,
                self._strings[40]: object_name,
                self._strings[21]: self._country,
            },
        )
        if api_response is None:
            _LOGGER.warning(
                "[OSS] get_interim_file_url: API call returned None for "
                "object_name=%r — cloud transport failure, see prior "
                "Cloud send error / get_properties warnings.",
                object_name,
            )
            return None
        if "data" not in api_response:
            # Cloud responded with an envelope but no `data` field —
            # this is the failure mode that's been silently dropping
            # session-summary downloads on g2408. Surface the full
            # response so we can categorise the error class.
            _LOGGER.warning(
                "[OSS] get_interim_file_url: response had no `data` field "
                "for object_name=%r. Full response: %r",
                object_name, api_response,
            )
            return None
        return api_response["data"]

    def get_properties(self, keys):
        params = {"did": str(self._did), "keys": keys}
        api_response = self._api_call(
            f"{self._strings[23]}/{self._strings[25]}/{self._strings[41]}", params)
        if api_response is None or "data" not in api_response:
            return None

        return api_response["data"]

    def get_device_property(self, key, limit=1, time_start=0, time_end=9999999999):
        return self.get_device_data(key, "prop", limit, time_start, time_end)

    def get_device_event(self, key, limit=1, time_start=0, time_end=9999999999):
        return self.get_device_data(key, "event", limit, time_start, time_end)

    def get_device_data(self, key, type, limit=1, time_start=0, time_end=9999999999):
        data_keys = key.split(".")
        params = {
            "uid": str(self._uid),
            "did": str(self._did),
            "from": time_start if time_start else 1687019188,
            "limit": limit,
            "siid": data_keys[0],
            self._strings[21]: self._country,
            self._strings[42]: 3,
        }
        param_name = "piid"
        if type == "event":
            param_name = "eiid"
        elif type == "action":
            param_name = "aiid"

        params[param_name] = data_keys[1]
        api_response = self._api_call(
            f"{self._strings[23]}/{self._strings[25]}/{self._strings[43]}", params)
        if api_response is None or "data" not in api_response or self._strings[33] not in api_response["data"]:
            return None

        return api_response["data"][self._strings[33]]

    def get_batch_device_datas(self, props) -> Any:
        api_response = self._api_call(
            f"{self._strings[23]}/{self._strings[26]}/{self._strings[44]}",
            {"did": self._did, self._strings[35]: props},
        )
        if api_response is None or "data" not in api_response:
            return None
        return api_response["data"]

    def set_batch_device_datas(self, props) -> Any:
        api_response = self._api_call(
            f"{self._strings[23]}/{self._strings[26]}/{self._strings[45]}",
            {"did": self._did, self._strings[35]: props},
        )
        if api_response is None or "result" not in api_response:
            return None
        return api_response["result"]

    def request(self, url: str, data, retry_count=2) -> Any:
        retries = 0
        if not retry_count or retry_count < 0:
            retry_count = 0
        while retries < retry_count + 1:
            try:
                if self._key_expire and time.time() > self._key_expire:
                    self.login()

                headers = {
                    "Accept": "*/*",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept-Language": "en-US;q=0.8",
                    "Accept-Encoding": "gzip, deflate",
                    self._strings[47]: self._strings[3],
                    self._strings[49]: self._strings[5],
                    self._strings[50]: self._ti if self._ti else self._strings[6],
                    self._strings[51]: self._strings[52],
                    self._strings[46]: self._key,
                }
                if self._country == "cn":
                    headers[self._strings[48]] = self._strings[4]

                response = self._session.post(
                    url,
                    headers=headers,
                    data=data,
                    timeout=15,
                )
                break
            except requests.exceptions.Timeout:
                retries = retries + 1
                response = None
                if self._connected:
                    _LOGGER.warning(
                        "Error while executing request: Read timed out. (read timeout=15): %s",
                        data,
                    )
            except Exception as ex:
                retries = retries + 1
                response = None
                if self._connected:
                    _LOGGER.warning(
                        "Error while executing request: %s", str(ex))

        if response is not None:
            if response.status_code == 200:
                self._fail_count = 0
                self._connected = True
                parsed = json.loads(response.text)
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    from ..protocol.api_log import summarize_api_response
                    _LOGGER.debug(
                        "API response: %s",
                        summarize_api_response(url, parsed),
                    )
                return parsed
            elif response.status_code == 401 and self._secondary_key:
                _LOGGER.debug("Execute api call failed: Token Expired")
                self.login()
            else:
                _LOGGER.warn(
                    "Execute api call failed with response: %s", response.text)

        if self._fail_count == 5:
            if not self._client_connected:
                self._connected = False
            else:
                _LOGGER.debug(
                    "HTTP requests failing but MQTT client still connected, keeping device connected")
        else:
            self._fail_count = self._fail_count + 1
        return None

    def disconnect(self):
        self._session.close()
        self._connected = False
        self._logged_in = False
        if self._client is not None:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
            self._client_connected = False
            self._client_connecting = False
        if self._thread:
            self._queue.put([])
        self._message_callback = None
        self._connected_callback = None


# DreameMowerMiHomeCloudProtocol (Xiaomi / Mi Home cloud path)
# removed 2026-04-20, Cleanup Phase 2. This fork targets the
# Dreame A2 mower which authenticates only against the Dreame
# cloud; the ~540 lines of Mi cloud auth / API / MQTT code were
# dead for every user of this integration. Static helpers that
# were reused by the Dreame cloud client (get_random_agent_id)
# are now module-level: see _random_agent_id at top of file.


class DreameMowerProtocol:
    """Thin wrapper over the Dreame Home cloud client.

    Phase 2 cleanup (v2.0.0-alpha.33) collapsed this from a
    multi-backend router (Mi cloud / Dreame cloud / local miIO) into a
    pure Dreame-cloud client. `self.device` (local LAN) is always None;
    `self.cloud` and `self.device_cloud` are the same
    `DreameMowerDreameHomeCloudProtocol` instance. The `prefer_cloud`
    attribute is retained as constant True so downstream code paths
    that gate on it keep compiling; local-first logic is gone.
    """

    def __init__(
        self,
        ip: str = None,
        token: str = None,
        username: str = None,
        password: str = None,
        country: str = None,
        prefer_cloud: bool = False,
        account_type: str = "dreame",
        device_id: str = None,
    ) -> None:
        # ip/token/prefer_cloud/account_type kept in the signature for
        # back-compat with callers that still pass them positionally;
        # all ignored.
        del ip, token, prefer_cloud, account_type
        self.prefer_cloud = True
        self._connected = False
        self._mac = None
        self.device = None  # no local-LAN path on A2
        if username and password and country:
            self.cloud = DreameMowerDreameHomeCloudProtocol(
                username, password, country, device_id
            )
        else:
            self.cloud = None
        # On the old code path `device_cloud` could be a distinct Mi
        # client; now it's the same Dreame cloud instance so the
        # sendCommand / getBatchDeviceDatas helpers below can continue
        # to reference it without a `None` check.
        self.device_cloud = self.cloud

    def set_credentials(self, ip: str, token: str, mac: str = None, account_type: str = "dreame"):
        """Kept for back-compat; only `mac` is retained for the MQTT
        client-id factory. IP/token/account_type are ignored."""
        del ip, token, account_type
        self._mac = mac
        self.device = None

    def connect(self, message_callback=None, connected_callback=None, retry_count=1) -> Any:
        info = self.cloud.connect(message_callback, connected_callback)
        if info:
            self._connected = True
        return info

    def disconnect(self):
        if self.cloud is not None:
            self.cloud.disconnect()
        self._connected = False

    def attach_mqtt_archive(self, archive) -> None:
        """Install an MQTT archive on the Dreame cloud's paho loop."""
        if self.cloud is not None and hasattr(self.cloud, "attach_mqtt_archive"):
            self.cloud.attach_mqtt_archive(archive)

    def send_async(self, callback, method, parameters: Any = None, retry_count: int = 2):
        if (self.prefer_cloud or not self.device) and self.device_cloud:
            if not self.device_cloud.logged_in:
                # Use different session for device cloud
                self.device_cloud.login()
                if self.device_cloud.logged_in and not self.device_cloud.device_id:
                    if self.cloud.device_id:
                        self.device_cloud._did = self.cloud.device_id
                    elif self._mac:
                        self.device_cloud.get_info(self._mac)

            if not self.device_cloud.logged_in:
                raise DeviceException(
                    "Unable to login to device over cloud") from None

            def cloud_callback(response):
                if response is None:
                    if not (self.device_cloud and self.device_cloud._client_connected):
                        self._connected = False
                    raise DeviceException(
                        "Unable to discover the device over cloud") from None
                self._connected = True
                callback(response)

            self.device_cloud.send_async(
                cloud_callback, method, parameters=parameters, retry_count=retry_count)
            return
        # Local-LAN fallback (`self.device.send_async`) removed in
        # Phase 2 cleanup — A2 has no local-LAN path.

    def send(self, method, parameters: Any = None, retry_count: int = 2) -> Any:
        if self.device_cloud is None:
            return None
        if not self.device_cloud.logged_in:
            # Use different session for device cloud
            self.device_cloud.login()
            if self.device_cloud.logged_in and not self.device_cloud.device_id:
                if self.cloud.device_id:
                    self.device_cloud._did = self.cloud.device_id
                elif self._mac:
                    self.device_cloud.get_info(self._mac)

        if not self.device_cloud.logged_in:
            raise DeviceException(
                "Unable to login to device over cloud") from None

        response = self.device_cloud.send(
            method, parameters=parameters, retry_count=retry_count)
        if response is None:
            _LOGGER.warning(
                "Cloud request returned None for %s (device may be in deep sleep)", method)
            return None
        self._connected = True
        return response

    def get_properties(self, parameters: Any = None, retry_count: int = 1) -> Any:
        return self.send("get_properties", parameters=parameters, retry_count=retry_count)

    def set_property(self, siid: int, piid: int, value: Any = None, retry_count: int = 2) -> Any:
        return self.set_properties(
            [
                {
                    "did": f"{siid}.{piid}" if not self.dreame_cloud else str(self.cloud.device_id),
                    "siid": siid,
                    "piid": piid,
                    "value": value,
                }
            ],
            retry_count=retry_count,
        )

    def set_properties(self, parameters: Any = None, retry_count: int = 2) -> Any:
        return self.send("set_properties", parameters=parameters, retry_count=retry_count)

    def action_async(self, callback, siid: int, aiid: int, parameters=[], retry_count: int = 2):
        if parameters is None:
            parameters = []

        _LOGGER.debug("Send Action Async: %s.%s %s", siid, aiid, parameters)
        self.send_async(
            callback,
            "action",
            parameters={
                "did": f"{siid}.{aiid}" if not self.dreame_cloud else str(self.cloud.device_id),
                "siid": siid,
                "aiid": aiid,
                "in": parameters,
            },
            retry_count=retry_count,
        )

    def action(self, siid: int, aiid: int, parameters=[], retry_count: int = 2) -> Any:
        if parameters is None:
            parameters = []

        _LOGGER.debug("Send Action: %s.%s %s", siid, aiid, parameters)
        return self.send(
            "action",
            parameters={
                "did": f"{siid}.{aiid}" if not self.dreame_cloud else str(self.cloud.device_id),
                "siid": siid,
                "aiid": aiid,
                "in": parameters,
            },
            retry_count=retry_count,
        )

    @property
    def connected(self) -> bool:
        if self.device_cloud is None:
            return False
        return (
            self.device_cloud.logged_in
            and self.device_cloud.connected
            and self._connected
        )

    @property
    def dreame_cloud(self) -> bool:
        if self.cloud:
            return self.cloud.dreame_cloud
        return False
