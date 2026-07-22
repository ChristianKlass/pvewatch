"""Tests for the optional dead-man's-switch heartbeat.

When HEARTBEAT_URL is set, a successful poll cycle ends with an HTTP GET to
that URL. A failed cycle sends nothing (silence is the signal), and a failed
ping never breaks monitoring.
"""

import logging
from unittest.mock import MagicMock

import pytest

import pvewatch.main as main_mod
from pvewatch.config import Settings
from pvewatch.main import _poll_cycle, _send_heartbeat

_BASE = dict(
    pve_host="pve.example",
    pve_node="pve",
    pve_token_id="user@pve!tok",
    pve_token_secret="s3cr3t",
    alert_discord_webhook="https://discord.example/hook",
)


def _settings(**kwargs):
    return Settings(_env_file=None, **_BASE, **kwargs)


@pytest.fixture
def quiet_cycle(monkeypatch):
    """Stub every side effect of _poll_cycle so only the heartbeat remains."""
    monkeypatch.setattr(main_mod, "refresh_vm_names", MagicMock())
    monkeypatch.setattr(main_mod, "poll_backup_tasks", MagicMock(return_value=[]))
    monkeypatch.setattr(main_mod, "poll_storage", MagicMock())
    monkeypatch.setattr(main_mod, "kv_set", MagicMock())


def test_heartbeat_fires_after_successful_cycle(monkeypatch, quiet_cycle):
    get = MagicMock(return_value=MagicMock(status_code=200))
    monkeypatch.setattr(main_mod.httpx, "get", get)
    settings = _settings(heartbeat_url="https://hc.example/ping/abc")

    _poll_cycle(MagicMock(), MagicMock(), "cid", settings)

    get.assert_called_once_with("https://hc.example/ping/abc", timeout=5)


def test_heartbeat_skipped_when_unset(monkeypatch, quiet_cycle):
    get = MagicMock()
    monkeypatch.setattr(main_mod.httpx, "get", get)

    _poll_cycle(MagicMock(), MagicMock(), "cid", _settings())

    get.assert_not_called()


def test_heartbeat_skipped_when_cycle_raises(monkeypatch, quiet_cycle):
    monkeypatch.setattr(main_mod, "poll_storage", MagicMock(side_effect=RuntimeError("proxmox down")))
    get = MagicMock()
    monkeypatch.setattr(main_mod.httpx, "get", get)
    settings = _settings(heartbeat_url="https://hc.example/ping/abc")

    with pytest.raises(RuntimeError):
        _poll_cycle(MagicMock(), MagicMock(), "cid", settings)

    get.assert_not_called()


def test_heartbeat_failure_is_swallowed_and_logged(monkeypatch, caplog):
    monkeypatch.setattr(main_mod.httpx, "get", MagicMock(side_effect=OSError("dns failure")))
    settings = _settings(heartbeat_url="https://hc.example/ping/abc")

    with caplog.at_level(logging.WARNING):
        _send_heartbeat(settings)  # must not raise

    assert any("heartbeat" in r.message.lower() for r in caplog.records)


def test_heartbeat_non_2xx_response_is_logged(monkeypatch, caplog):
    """httpx does not raise on 4xx/5xx, so a mistyped ping URL must still warn."""
    monkeypatch.setattr(main_mod.httpx, "get", MagicMock(return_value=MagicMock(status_code=404)))
    settings = _settings(heartbeat_url="https://hc.example/ping/wrong-uuid")

    with caplog.at_level(logging.WARNING):
        _send_heartbeat(settings)

    assert any("404" in r.message or "404" in str(r.args) for r in caplog.records)


def test_heartbeat_2xx_response_logs_nothing(monkeypatch, caplog):
    monkeypatch.setattr(main_mod.httpx, "get", MagicMock(return_value=MagicMock(status_code=200)))
    settings = _settings(heartbeat_url="https://hc.example/ping/abc")

    with caplog.at_level(logging.WARNING):
        _send_heartbeat(settings)

    assert not caplog.records


def test_heartbeat_noop_without_url(monkeypatch):
    get = MagicMock()
    monkeypatch.setattr(main_mod.httpx, "get", get)

    _send_heartbeat(_settings())

    get.assert_not_called()
