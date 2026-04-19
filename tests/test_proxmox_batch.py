"""Tests for _parse_timestamp and _parse_batch_log."""

from pvewatch.proxmox import _parse_batch_log, _parse_timestamp


def test_parse_timestamp_valid():
    ts = _parse_timestamp("2024-01-15 10:30:00")
    assert isinstance(ts, int)
    assert ts > 0


def test_parse_timestamp_invalid():
    assert _parse_timestamp("not a date") is None
    assert _parse_timestamp("") is None


def test_parse_batch_log_empty():
    assert _parse_batch_log("", "UPID:pve:1:2:3:vzdump:0:root@pam:", "pve", 1000000) == []


def test_parse_batch_log_single_vm_ok():
    log = (
        "INFO: Starting Backup of VM 101 (qemu)\n"
        "INFO: Backup started at 2024-01-15 10:00:00\n"
        "INFO: some progress\n"
        "INFO: Backup finished at 2024-01-15 10:05:00\n"
    )
    results = _parse_batch_log(log, "UPID:pve:1:2:3:vzdump:0:root@pam:", "pve", 1000000)
    assert len(results) == 1
    assert results[0].vmid == 101
    assert results[0].exit_status == "OK"
    assert results[0].node == "pve"
    assert results[0].status == "stopped"
    assert results[0].duration_sec is not None


def test_parse_batch_log_single_vm_error():
    log = (
        "INFO: Starting Backup of VM 102 (qemu)\n"
        "INFO: Backup started at 2024-01-15 10:00:00\n"
        "ERROR: Failed to create snapshot\n"
        "INFO: Backup finished at 2024-01-15 10:01:00\n"
    )
    results = _parse_batch_log(log, "UPID:pve:1:2:3:vzdump:0:root@pam:", "pve", 1000000)
    assert len(results) == 1
    assert results[0].vmid == 102
    assert results[0].exit_status != "OK"
    assert "snapshot" in results[0].log_tail.lower()


def test_parse_batch_log_multiple_vms():
    log = (
        "INFO: Starting Backup of VM 101 (qemu)\n"
        "INFO: Backup started at 2024-01-15 10:00:00\n"
        "INFO: Backup finished at 2024-01-15 10:05:00\n"
        "INFO: Starting Backup of VM 102 (lxc)\n"
        "INFO: Backup started at 2024-01-15 10:06:00\n"
        "INFO: Backup finished at 2024-01-15 10:08:00\n"
    )
    results = _parse_batch_log(log, "UPID:pve:1:2:3:vzdump:0:root@pam:", "pve", 1000000)
    assert len(results) == 2
    assert results[0].vmid == 101
    assert results[1].vmid == 102


def test_parse_batch_log_falls_back_to_batch_start():
    log = "INFO: Starting Backup of VM 101 (qemu)\nINFO: Backup finished at 2024-01-15 10:05:00\n"
    batch_start = 1705312800
    results = _parse_batch_log(log, "UPID:pve:1:2:3:vzdump:0:root@pam:", "pve", batch_start)
    assert len(results) == 1
    assert results[0].start_time == batch_start


def test_parse_batch_log_upid_contains_vmid():
    log = "INFO: Starting Backup of VM 101 (qemu)\nINFO: Backup finished at 2024-01-15 10:05:00\n"
    batch_upid = "UPID:pve:1:2:3:vzdump:0:root@pam:"
    results = _parse_batch_log(log, batch_upid, "pve", 1000000)
    assert results[0].upid == f"{batch_upid}|101"


def test_parse_batch_log_lines_before_first_vm_ignored():
    log = (
        "INFO: Starting vzdump backup job\n"
        "some header line\n"
        "INFO: Starting Backup of VM 101 (qemu)\n"
        "INFO: Backup finished at 2024-01-15 10:05:00\n"
    )
    results = _parse_batch_log(log, "UPID:pve:1:2:3:vzdump:0:root@pam:", "pve", 1000000)
    assert len(results) == 1
