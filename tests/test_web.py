from __future__ import annotations

import pytest

from anon_tool.web import _resolve_auth


def test_web_ui_allows_localhost_without_auth() -> None:
    assert _resolve_auth("127.0.0.1", None, None) is None
    assert _resolve_auth("localhost", None, None) is None


def test_web_ui_requires_auth_for_non_loopback_bind() -> None:
    with pytest.raises(ValueError, match="Refusing to expose"):
        _resolve_auth("0.0.0.0", None, None)


def test_web_ui_accepts_auth_for_non_loopback_bind() -> None:
    assert _resolve_auth("0.0.0.0", "user", "password") == ("user", "password")


def test_web_ui_rejects_partial_auth() -> None:
    with pytest.raises(ValueError, match="Provide both"):
        _resolve_auth("127.0.0.1", "user", None)
