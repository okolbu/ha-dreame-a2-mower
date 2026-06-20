"""Card gate: the schedule card's add/edit modal must survive hass updates.

`set hass` fires on EVERY HA entity change (Lovelace reassigns `hass` to every
card), and the mower pushes telemetry constantly. The card used to re-render its
whole shadow DOM on every such update, which — while the modal was open — wiped
the live <input type=time>, the day-toggle state, and focus from a stale HTML
snapshot. Symptoms: time edits wouldn't stick; day/Cancel buttons felt
"deselected right away".

The fix: while a modal is open, keep the latest state (for the eventual save)
but DO NOT re-render. Runs the REAL `set hass` setter in node (per
feedback_frontend_card_verification — `node --check` only catches syntax).
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

NODE = shutil.which("node")
HARNESS = pathlib.Path(__file__).parent / "schedule_modal_harness.mjs"


def _run_harness() -> dict:
    r = subprocess.run(
        [NODE, str(HARNESS)], capture_output=True, text=True, timeout=30
    )
    assert r.returncode == 0, f"node harness failed:\n{r.stdout}\n{r.stderr}"
    last = [ln for ln in r.stdout.splitlines() if ln.strip()][-1]
    return json.loads(last)


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_modal_open_state_is_sane():
    d = _run_harness()
    assert d["afterFirst"] == 1, "first hass should render once"
    assert d["modalOpen"] is True, "opening the add modal sets _modal"
    assert d["afterOpen"] == 2, "opening the modal renders it once"


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_same_ref_hass_update_does_not_clobber_modal():
    d = _run_harness()
    # A hass update where THIS sensor didn't change must not re-render the modal.
    assert d["afterSameRef"] == d["afterOpen"], (
        "a same-state hass update re-rendered (and would wipe) the open modal"
    )


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_new_ref_hass_update_keeps_modal_but_freshens_state():
    d = _run_harness()
    # Even a genuine sensor change must not yank the modal out from under the
    # user — but the card must still hold the latest state for the save.
    assert d["afterNewRef"] == d["afterOpen"], (
        "a sensor-change hass update re-rendered (and would wipe) the open modal"
    )
    assert d["modalStillOpen"] is True
    assert d["stateRefIsFresh"] is True, (
        "the card must keep the latest state for the eventual save"
    )


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_render_resumes_after_modal_closes():
    d = _run_harness()
    assert d["afterClose"] == d["afterNewRef"] + 1, (
        "closing the modal must let hass updates re-render the card again"
    )
