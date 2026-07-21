"""Tests for optional HTTP Basic Auth on the web UI.

Auth is off unless both WEB_UI_USERNAME and WEB_UI_PASSWORD are set. When on,
every endpoint except the k8s probes (/healthz, /readyz) requires credentials.
"""

import base64

import pytest

from pvewatch.config import Settings
from pvewatch.web import _auth_required, _check_auth


def _basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


# --- _check_auth ---


def test_auth_disabled_allows_any_request():
    assert _check_auth(None, "", "") is True
    assert _check_auth("Basic garbage", "", "") is True


def test_correct_credentials_allowed():
    assert _check_auth(_basic("admin", "hunter2"), "admin", "hunter2") is True


def test_wrong_password_denied():
    assert _check_auth(_basic("admin", "wrong"), "admin", "hunter2") is False


def test_wrong_username_denied():
    assert _check_auth(_basic("bob", "hunter2"), "admin", "hunter2") is False


def test_missing_header_denied():
    assert _check_auth(None, "admin", "hunter2") is False


def test_non_basic_scheme_denied():
    assert _check_auth("Bearer sometoken", "admin", "hunter2") is False


def test_malformed_base64_denied():
    assert _check_auth("Basic not-valid-b64!!!", "admin", "hunter2") is False


def test_password_containing_colon_allowed():
    assert _check_auth(_basic("admin", "pa:ss:word"), "admin", "pa:ss:word") is True


# --- _auth_required ---


def test_probes_exempt_from_auth():
    assert _auth_required("/healthz") is False
    assert _auth_required("/readyz") is False


def test_everything_else_requires_auth():
    assert _auth_required("/") is True
    assert _auth_required("/api/status") is True
    assert _auth_required("/metrics") is True


# --- Settings validation ---

_BASE = dict(
    pve_host="pve.example",
    pve_node="pve",
    pve_token_id="user@pve!tok",
    pve_token_secret="s3cr3t",
    alert_discord_webhook="https://discord.example/hook",
)


def test_settings_auth_off_by_default():
    s = Settings(_env_file=None, **_BASE)
    assert s.web_ui_username == ""
    assert s.web_ui_password == ""


def test_settings_username_without_password_rejected():
    with pytest.raises(ValueError, match="WEB_UI_USERNAME and WEB_UI_PASSWORD"):
        Settings(_env_file=None, web_ui_username="admin", **_BASE)


def test_settings_password_without_username_rejected():
    with pytest.raises(ValueError, match="WEB_UI_USERNAME and WEB_UI_PASSWORD"):
        Settings(_env_file=None, web_ui_password="hunter2", **_BASE)


def test_settings_both_set_accepted():
    s = Settings(_env_file=None, web_ui_username="admin", web_ui_password="hunter2", **_BASE)
    assert s.web_ui_username == "admin"
    assert s.web_ui_password == "hunter2"
