"""Tests for the [UNVERIFIED] file-bridge signer.

The signer is a hypothesis derived from app reverse-engineering.  It does NOT
yet reproduce the captured golden signature.  The strict xfail below is the
honesty mechanism — it turns into an xpass (loud failure) if someone later
fixes the formula and the golden starts matching, prompting them to convert it
to a hard assert and mark the inventory verified.
"""
import hashlib

import pytest

from custom_components.dreame_a2_mower.cloud_client._file_bridge import sign_file_bridge

_FILEINFO = '{"filename":"1781714586.078000_0.jpg","type":"ai_obs"}'
_PARAMS = {"fileinfo": _FILEINFO, "did": "-112293549"}
_TS = 1781718618184
_GOLDEN = "952cdf8580ae1c162df56b9c24fe21c3"


def test_sign_is_deterministic_32hex():
    """The signer is stable + MD5-shaped (its CORRECTNESS is unverified — see
    the xfail golden test below)."""
    s = sign_file_bridge(_PARAMS, _TS)
    assert s == sign_file_bridge(_PARAMS, _TS)
    assert len(s) == 32 and all(c in "0123456789abcdef" for c in s)


@pytest.mark.xfail(
    reason=(
        "signer UNVERIFIED — hypothesis formula does not yet "
        "reproduce the captured golden; a hidden signed input "
        "is missing. Flip to a hard assert once a live 200 or a "
        "successful app capture confirms the formula."
    ),
    strict=True,
)
def test_sign_reproduces_captured_golden():
    assert sign_file_bridge(_PARAMS, _TS) == _GOLDEN
