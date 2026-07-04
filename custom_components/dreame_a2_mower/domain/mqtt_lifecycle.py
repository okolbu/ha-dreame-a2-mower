"""MQTT auth-recovery lifecycle service (layer 4) — refactor-v2 P3.9d.

Moved VERBATIM from ``coordinator/_core.py`` — the T3-9 / P3.8 MQTT rc=5
(auth-rejected) recovery path with the escalating cooldown. Each function takes
the coordinator (``coord``) as its first argument; the coordinator keeps thin
``_CoreMixin`` delegators (``_handle_mqtt_auth_error`` stays ``@callback``) so
the ``_init_mqtt`` wiring + ``test_mqtt_auth_recovery`` surface is unchanged.

The rc=5 guard state (``_rc5_relogin_in_progress`` / ``_rc5_last_attempt_unix`` /
``_rc5_consecutive_failures``) + the ``_RC5_RELOGIN_COOLDOWN_S`` /
``_RC5_RELOGIN_COOLDOWN_MAX_S`` class constants stay owned by ``_CoreMixin``
(read via ``coord._rc5_*`` here); 9e decides their final home during the
``__init__`` attr-shrink.
"""
from __future__ import annotations

import time

from ..const import LOGGER


def handle_mqtt_auth_error(coord) -> None:
    """T3-9: MQTT rc=5 (broker rejected our credentials).

    The cloud session token (``_key``) rotates on a periodic re-login
    (``cloud_client/_fetchers.py`` refreshes it when ``_key_expire``
    passes); until now nothing told the MQTT client about a rotation, so
    a broker reconnect after the old password went stale looped on rc=5
    forever with no self-heal short of an HA reload.

    Runs on the event loop (hopped via ``call_soon_threadsafe`` from the
    paho network thread that reported rc=5 — see ``_init_mqtt``).
    Kicks off ``_async_recover_mqtt_auth`` as a background task: a
    cloud re-login is a blocking ``requests`` call and must not run
    inline on the loop.

    Guarded against a tight loop: a relogin already in flight is not
    duplicated, and a fresh rc=5 within ``_RC5_RELOGIN_COOLDOWN_S`` of
    the last attempt is logged and skipped (covers both a broker that
    keeps rejecting a freshly-refreshed password and rapid repeated
    disconnects) rather than hammering the cloud login endpoint.
    """
    now = time.time()
    if coord._rc5_relogin_in_progress:
        LOGGER.debug(
            "[mqtt] rc=5 auth error while a relogin is already in "
            "flight — ignoring duplicate signal"
        )
        return
    cooldown = min(
        coord._RC5_RELOGIN_COOLDOWN_S * (2 ** coord._rc5_consecutive_failures),
        coord._RC5_RELOGIN_COOLDOWN_MAX_S,
    )
    if now - coord._rc5_last_attempt_unix < cooldown:
        LOGGER.warning(
            "[mqtt] rc=5 auth error seen again within %ds (escalated after "
            "%d consecutive failure(s)) of the last relogin attempt — "
            "skipping to avoid a tight reconnect loop (will retry on the "
            "next rc=5 once the cooldown elapses)",
            cooldown,
            coord._rc5_consecutive_failures,
        )
        return
    coord._rc5_relogin_in_progress = True
    coord._rc5_last_attempt_unix = now
    coord.hass.async_create_task(coord._async_recover_mqtt_auth())


async def async_recover_mqtt_auth(coord) -> None:
    """T3-9: re-login the cloud client and push refreshed MQTT creds.

    ``cloud.login()`` blocks (``requests``), so it runs in the executor.
    On success, ``update_credentials`` hot-swaps the MQTT client's
    username/password so paho's own automatic reconnect (armed via
    ``reconnect_delay_set`` in ``mqtt_client.connect``) succeeds on its
    next attempt instead of retrying the stale password. On failure the
    method just logs — the next genuine rc=5 (after the cooldown) will
    retry.
    """
    try:
        cloud = coord.cloud
        mqtt = coord.mqtt
        if cloud is None or mqtt is None:
            LOGGER.debug(
                "[mqtt] rc=5 recovery: cloud/mqtt not initialised — skipping"
            )
            return
        ok = await coord.hass.async_add_executor_job(cloud.login)
        if not ok:
            # P2-inherit: escalate the cooldown so a broker that keeps
            # rejecting fresh creds is retried less and less aggressively.
            coord._rc5_consecutive_failures += 1
            if cloud.last_login_failure == "auth":
                # Task 2 (P6.1b) DEVIATION from the literal brief: raising
                # ConfigEntryAuthFailed from this background task is not a
                # valid HA API (nothing awaits it into config-entry setup) —
                # entry.async_start_reauth is the correct runtime surface for
                # a rc=5 relogin that fails because the cloud genuinely
                # rejected the (freshly-refreshed) credentials, as opposed to
                # a transient network blip.
                LOGGER.error(
                    "[mqtt] rc=5 recovery: cloud rejected the configured "
                    "credentials — starting the reauth flow"
                )
                coord.entry.async_start_reauth(coord.hass)
            else:
                LOGGER.warning(
                    "[mqtt] rc=5 recovery: cloud re-login failed (%d consecutive); "
                    "MQTT will keep retrying with the stale password until the "
                    "next rc=5 triggers another (increasingly spaced) attempt",
                    coord._rc5_consecutive_failures,
                )
            return
        username, password = cloud.mqtt_credentials()
        mqtt.update_credentials(username, password)
        # Success — reset the escalation so the next rc=5 gets the base cooldown.
        coord._rc5_consecutive_failures = 0
        LOGGER.info(
            "[mqtt] rc=5 recovery: cloud re-login succeeded; refreshed "
            "credentials pushed to the MQTT client for the next reconnect"
        )
    finally:
        coord._rc5_relogin_in_progress = False
