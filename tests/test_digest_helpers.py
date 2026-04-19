"""Tests for digest.py helper functions."""

import time

import pytest

from pvewatch.digest import (
    _build_storage_out,
    _build_vm_entry,
    _fmt_duration,
    _fmt_gb,
    _group_backup_rows,
    _vm_dots,
)

TODAY = int(time.time()) // 86400
NOW = int(time.time())


def _row(vmid, vm_name, status, start_time, duration_sec=None):
    return {"vmid": vmid, "vm_name": vm_name, "status": status, "start_time": start_time, "duration_sec": duration_sec}


def _storage_row(storage_id, node, used_bytes, total_bytes):
    return {"storage_id": storage_id, "node": node, "used_bytes": used_bytes, "total_bytes": total_bytes}


# --- _fmt_duration ---


def test_fmt_duration_none():
    assert _fmt_duration(None) == "—"


def test_fmt_duration_zero():
    assert _fmt_duration(0) == "—"


def test_fmt_duration_seconds():
    assert _fmt_duration(45) == "45s"


def test_fmt_duration_minutes():
    assert _fmt_duration(125) == "2m 5s"


# --- _fmt_gb ---


def test_fmt_gb():
    assert _fmt_gb(1_073_741_824) == "1.0"
    assert _fmt_gb(0) == "0.0"


# --- _group_backup_rows ---


def test_group_backup_rows_empty():
    assert _group_backup_rows([]) == {}


def test_group_backup_rows_single():
    rows = [_row(101, "web", "OK", NOW - 3600)]
    result = _group_backup_rows(rows)
    assert 101 in result
    assert result[101]["name"] == "web"
    assert len(result[101]["results"]) == 1


def test_group_backup_rows_multiple_runs_same_vm():
    rows = [
        _row(101, "web", "OK", NOW - 7200),
        _row(101, "web", "OK", NOW - 3600),
    ]
    result = _group_backup_rows(rows)
    assert len(result[101]["results"]) == 2


def test_group_backup_rows_no_name_fallback():
    rows = [_row(101, None, "OK", NOW - 3600)]
    result = _group_backup_rows(rows)
    assert result[101]["name"] == "VM 101"


def test_group_backup_rows_multiple_vms():
    rows = [
        _row(101, "web", "OK", NOW - 3600),
        _row(102, "db", "OK", NOW - 7200),
    ]
    result = _group_backup_rows(rows)
    assert set(result.keys()) == {101, 102}


# --- _vm_dots ---


def test_vm_dots_no_results():
    dots = _vm_dots([], TODAY)
    assert dots == ["none"] * 7


def test_vm_dots_ok_today():
    results = [{"start_time": TODAY * 86400 + 3600, "status": "OK"}]
    dots = _vm_dots(results, TODAY)
    assert dots[-1] == "ok"
    assert all(d == "none" for d in dots[:-1])


def test_vm_dots_fail_yesterday():
    results = [{"start_time": (TODAY - 1) * 86400 + 3600, "status": "ERROR: disk full"}]
    dots = _vm_dots(results, TODAY)
    assert dots[-2] == "fail"
    assert dots[-1] == "none"


def test_vm_dots_last_status_wins():
    results = [
        {"start_time": TODAY * 86400 + 100, "status": "OK"},
        {"start_time": TODAY * 86400 + 200, "status": "ERROR"},
    ]
    dots = _vm_dots(results, TODAY)
    assert dots[-1] == "fail"


# --- _build_vm_entry ---


def test_build_vm_entry_no_results():
    data = {"name": "web", "results": []}
    entry = _build_vm_entry(data, TODAY)
    assert entry["total"] == 0
    assert entry["failures"] == 0
    assert entry["last_success"] is None
    assert entry["avg_duration"] == "—"


def test_build_vm_entry_all_ok():
    data = {
        "name": "web",
        "results": [
            {"status": "OK", "start_time": NOW - 86400, "duration_sec": 120},
            {"status": "", "start_time": NOW - 3600, "duration_sec": 90},
        ],
    }
    entry = _build_vm_entry(data, TODAY)
    assert entry["total"] == 2
    assert entry["failures"] == 0
    assert entry["avg_duration"] == "1m 45s"
    assert entry["last_success"] is not None


def test_build_vm_entry_with_failure():
    data = {
        "name": "db",
        "results": [
            {"status": "ERROR: no space", "start_time": NOW - 3600, "duration_sec": None},
        ],
    }
    entry = _build_vm_entry(data, TODAY)
    assert entry["failures"] == 1
    assert entry["last_success"] is None


# --- _build_storage_out ---


def test_build_storage_out_empty():
    assert _build_storage_out([]) == []


def test_build_storage_out_single():
    rows = [_storage_row("local", "pve", 500 * 1024**3, 1024**4)]
    out = _build_storage_out(rows)
    assert len(out) == 1
    assert out[0]["storage_id"] == "local"
    assert out[0]["pct"] == pytest.approx(500 / 1024 * 100, rel=1e-3)


def test_build_storage_out_duplicate_adds_node_prefix():
    rows = [
        _storage_row("nas", "pve1", 100, 1000),
        _storage_row("nas", "pve2", 200, 1000),
    ]
    out = _build_storage_out(rows)
    assert len(out) == 2
    assert out[0]["storage_id"] == "pve1/nas"
    assert out[1]["storage_id"] == "pve2/nas"


def test_build_storage_out_single_occurrence_no_prefix():
    rows = [
        _storage_row("local", "pve1", 100, 1000),
        _storage_row("nas", "pve1", 200, 2000),
    ]
    out = _build_storage_out(rows)
    assert out[0]["storage_id"] == "local"
    assert out[1]["storage_id"] == "nas"
