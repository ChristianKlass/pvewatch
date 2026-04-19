"""Tests for UPID parsing and task info building (no live Proxmox needed)."""
import pytest
from unittest.mock import MagicMock, patch

from pvewatch.proxmox import _parse_vmid_from_upid, ProxmoxClient, TaskInfo


def test_parse_vmid_standard():
    upid = "UPID:pve:00123456:00ABCDEF:67F12345:vzdump:101:root@pam:"
    assert _parse_vmid_from_upid(upid) == 101


def test_parse_vmid_three_digit():
    upid = "UPID:pve:00123456:00ABCDEF:67F12345:vzdump:200:monitoring@pve!pvewatch:"
    assert _parse_vmid_from_upid(upid) == 200


def test_parse_vmid_malformed():
    assert _parse_vmid_from_upid("bad-upid") == 0
    assert _parse_vmid_from_upid("") == 0
    assert _parse_vmid_from_upid("UPID:pve") == 0


def test_build_task_info_running_returns_none():
    settings = MagicMock()
    settings.pve_host = "192.168.1.1"
    settings.pve_port = 8006
    settings.pve_node = "pve"
    settings.pve_token_id = "monitoring@pve!pvewatch"
    settings.pve_token_secret = "secret"
    settings.pve_verify_ssl = False

    with patch("pvewatch.proxmox.ProxmoxAPI"):
        client = ProxmoxClient(settings)
        raw = {
            "upid": "UPID:pve:00123456:00ABCDEF:67F12345:vzdump:101:root@pam:",
            "status": "running",
            "starttime": 1000000,
            "node": "pve",
        }
        assert client.build_task_info(raw) is None


def test_build_task_info_ok():
    settings = MagicMock()
    settings.pve_node = "pve"

    with patch("pvewatch.proxmox.ProxmoxAPI"):
        client = ProxmoxClient(settings)
        raw = {
            "upid": "UPID:pve:00123456:00ABCDEF:67F12345:vzdump:101:root@pam:",
            "status": "stopped",
            "exitstatus": "OK",
            "starttime": 1000000,
            "endtime": 1000240,
            "node": "pve",
        }
        task = client.build_task_info(raw)
        assert task is not None
        assert task.exit_status == "OK"
        assert task.vmid == 101
        assert task.duration_sec == 240
        assert task.log_tail == ""  # no log fetch for OK tasks


def test_build_task_info_failure_fetches_log():
    settings = MagicMock()
    settings.pve_node = "pve"

    with patch("pvewatch.proxmox.ProxmoxAPI"):
        client = ProxmoxClient(settings)
        client.get_task_log = MagicMock(return_value="error: permission denied")
        raw = {
            "upid": "UPID:pve:00123456:00ABCDEF:67F12345:vzdump:102:root@pam:",
            "status": "stopped",
            "exitstatus": "ERROR: permission denied",
            "starttime": 1000000,
            "endtime": 1000060,
            "node": "pve",
        }
        task = client.build_task_info(raw)
        assert task is not None
        assert task.exit_status == "ERROR: permission denied"
        assert task.log_tail == "error: permission denied"
        client.get_task_log.assert_called_once()
