"""Tests for _FileBridgeMixin.get_device_file.

The mixin is [UNVERIFIED] — the signer does not yet reproduce the captured
golden and the backend is currently unreliable.  These tests exercise the
decode / fail-closed / body-shape contract WITHOUT hitting the network by
overriding the ``_post_file_bridge`` seam.
"""
from __future__ import annotations

import base64
import json

import pytest

from custom_components.dreame_a2_mower.cloud_client._file_bridge import (
    _FileBridgeMixin,
)


# ---------------------------------------------------------------------------
# Test harness helpers
# ---------------------------------------------------------------------------


def _client(resp_json):
    """Build a minimal _FileBridgeMixin instance whose POST seam returns resp_json."""

    class _C(_FileBridgeMixin):
        _did = "-112293549"

        def _post_file_bridge(self, body):
            # Seam: real impl does the signed POST; tests override this.
            return resp_json

        def get_file(self, url):
            # Stub: tests that exercise the URL branch set this on the instance.
            return getattr(self, "_get_file_stub", None)

    return _C()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_decodes_base64_body():
    """Leading hypothesis from bundle code64=true: base64 bytes in JSON data field."""
    jpeg = b"\xff\xd8\xff\xe0JFIFdata"
    resp = {"data": base64.b64encode(jpeg).decode()}
    out = _client(resp).get_device_file("1781714586.078000_0.jpg")
    assert out == jpeg


def test_follows_url_response():
    """If data field is an http URL, get_device_file fetches it via self.get_file."""
    sentinel = b"\xff\xd8\xff\xe0sentinel_bytes"
    resp = {"data": "https://example.oss.aliyun.com/obstacle/photo.jpg"}
    c = _client(resp)
    c._get_file_stub = sentinel
    out = c.get_device_file("photo.jpg")
    assert out == sentinel


def test_fails_closed_on_post_error():
    """When _post_file_bridge returns None, get_device_file returns None (no raise)."""

    class _C(_FileBridgeMixin):
        _did = "12345"

        def _post_file_bridge(self, body):
            return None

        def get_file(self, url):
            raise AssertionError("should not be called")

    assert _C().get_device_file("x.jpg") is None


def test_fails_closed_on_post_exception():
    """When _post_file_bridge raises, get_device_file returns None (no raise)."""

    class _C(_FileBridgeMixin):
        _did = "12345"

        def _post_file_bridge(self, body):
            raise RuntimeError("network exploded")

        def get_file(self, url):
            raise AssertionError("should not be called")

    assert _C().get_device_file("x.jpg") is None


def test_builds_compact_fileinfo():
    """The body POSTed must have compact fileinfo (no spaces) + sign + timestamp."""
    captured_body: dict = {}

    class _C(_FileBridgeMixin):
        _did = "-112293549"

        def _post_file_bridge(self, body):
            captured_body.update(body)
            return None  # fail closed is fine for this structural check

        def get_file(self, url):
            return None

    _C().get_device_file("x.jpg", "ai_obs")

    assert "fileinfo" in captured_body
    assert "sign" in captured_body
    assert "timestamp" in captured_body
    assert "did" in captured_body

    # fileinfo must be compact JSON (no spaces after separators)
    fi = captured_body["fileinfo"]
    assert fi == '{"filename":"x.jpg","type":"ai_obs"}', (
        f"fileinfo not compact: {fi!r}"
    )
