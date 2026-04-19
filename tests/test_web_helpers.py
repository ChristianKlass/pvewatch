"""Tests for web.py helper functions and _build_data."""

import tempfile
import time
import uuid

import pytest

from pvewatch.database import connect, migrate
from pvewatch.web import _build_data, _build_vm_entry_web, _dedup_storage, _vm_day_dots, _vm_last_info

TODAY = int(time.time()) // 86400
NOW = int(time.time())


@pytest.fixture
def conn():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db_path = f.name
    c = connect(db_path)
    migrate(c)
    yield c
    c.close()


@pytest.fixture
def cluster_id(conn):
    cid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO clusters (id, name, host, port, node, token_id, token_secret, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (cid, "pve", "192.168.1.1", 8006, "pve", "tok", "sec", NOW),
    )
    conn.commit()
    return cid


# --- _vm_day_dots ---


def test_vm_day_dots_empty():
    assert _vm_day_dots([], TODAY, 7) == ["none"] * 7


def test_vm_day_dots_ok_today():
    results = [{"start_time": TODAY * 86400 + 100, "status": "OK"}]
    dots = _vm_day_dots(results, TODAY, 7)
    assert dots[-1] == "ok"


def test_vm_day_dots_fail_overrides_ok():
    results = [
        {"start_time": TODAY * 86400 + 100, "status": "OK"},
        {"start_time": TODAY * 86400 + 200, "status": "ERROR"},
    ]
    dots = _vm_day_dots(results, TODAY, 7)
    assert dots[-1] == "fail"


def test_vm_day_dots_ok_does_not_override_fail():
    results = [
        {"start_time": TODAY * 86400 + 100, "status": "ERROR"},
        {"start_time": TODAY * 86400 + 200, "status": "OK"},
    ]
    dots = _vm_day_dots(results, TODAY, 7)
    assert dots[-1] == "fail"


def test_vm_day_dots_custom_days():
    dots = _vm_day_dots([], TODAY, 14)
    assert len(dots) == 14


# --- _vm_last_info ---


def test_vm_last_info_none():
    status, last_run, ts, stale = _vm_last_info(None, NOW)
    assert status is None
    assert last_run is None
    assert ts == 0
    assert stale is False


def test_vm_last_info_recent():
    latest = {"status": "OK", "start_time": NOW - 3600}
    status, last_run, ts, stale = _vm_last_info(latest, NOW)
    assert status == "OK"
    assert last_run is not None
    assert ts == NOW - 3600
    assert stale is False


def test_vm_last_info_stale():
    latest = {"status": "OK", "start_time": NOW - 9 * 86400}
    _, _, _, stale = _vm_last_info(latest, NOW)
    assert stale is True


def test_vm_last_info_exactly_8_days_not_stale():
    latest = {"status": "OK", "start_time": NOW - 8 * 86400}
    _, _, _, stale = _vm_last_info(latest, NOW)
    assert stale is False


# --- _build_vm_entry_web ---


def _make_vm(vmid=101, name="web", vm_type="qemu", node="pve"):
    return {"vmid": vmid, "vm_name": name, "vm_type": vm_type, "node": node}


def test_build_vm_entry_web_no_results_no_latest():
    vm = _make_vm()
    entry = _build_vm_entry_web(vm, [], None, TODAY, 7, NOW)
    assert entry["vmid"] == 101
    assert entry["name"] == "web"
    assert entry["vm_type"] == "qemu"
    assert entry["node"] == "pve"
    assert entry["ok_count"] == 0
    assert entry["fail_count"] == 0
    assert entry["last_status"] is None
    assert entry["stale"] is False


def test_build_vm_entry_web_fallback_name():
    vm = {"vmid": 101, "vm_name": None, "vm_type": None, "node": None}
    entry = _build_vm_entry_web(vm, [], None, TODAY, 7, NOW)
    assert entry["name"] == "VM 101"
    assert entry["vm_type"] == "qemu"
    assert entry["node"] == ""


def test_build_vm_entry_web_with_ok_backup():
    vm = _make_vm()
    results = [{"start_time": TODAY * 86400 + 100, "status": "OK"}]
    latest = {"status": "OK", "start_time": NOW - 3600}
    entry = _build_vm_entry_web(vm, results, latest, TODAY, 7, NOW)
    assert entry["ok_count"] == 1
    assert entry["fail_count"] == 0
    assert entry["last_status"] == "OK"
    assert entry["stale"] is False


def test_build_vm_entry_web_with_failure():
    vm = _make_vm()
    results = [{"start_time": TODAY * 86400 + 100, "status": "ERROR"}]
    latest = {"status": "ERROR", "start_time": NOW - 3600}
    entry = _build_vm_entry_web(vm, results, latest, TODAY, 7, NOW)
    assert entry["fail_count"] == 1
    assert entry["ok_count"] == 0


# --- _dedup_storage ---


def _srow(storage_id, node, used, total):
    return {"storage_id": storage_id, "node": node, "used_bytes": used, "total_bytes": total}


def test_dedup_storage_empty():
    assert _dedup_storage([]) == []


def test_dedup_storage_unique():
    rows = [_srow("local", "pve", 100, 1000), _srow("nas", "pve", 200, 2000)]
    out = _dedup_storage(rows)
    assert len(out) == 2


def test_dedup_storage_same_name_same_size_deduped():
    rows = [_srow("nas", "pve1", 100, 1000), _srow("nas", "pve2", 100, 1000)]
    out = _dedup_storage(rows)
    assert len(out) == 1
    assert out[0]["storage_id"] == "nas"


def test_dedup_storage_same_name_different_size_kept():
    rows = [_srow("local", "pve1", 100, 1000), _srow("local", "pve2", 200, 2000)]
    out = _dedup_storage(rows)
    assert len(out) == 2


def test_dedup_storage_pct_calculated():
    rows = [_srow("local", "pve", 500, 1000)]
    out = _dedup_storage(rows)
    assert out[0]["pct"] == pytest.approx(50.0)


def test_dedup_storage_node_empty_string_fallback():
    rows = [_srow("local", None, 100, 1000)]
    out = _dedup_storage(rows)
    assert out[0]["node"] == ""


# --- _build_data (integration) ---


def test_build_data_empty_db(conn):
    data = _build_data(conn, "pve")
    assert data["vms"] == []
    assert data["storage"] == []
    assert "summary" in data
    assert data["summary"]["total_vms"] == 0


def test_build_data_with_vm_and_backup(conn, cluster_id):
    conn.execute(
        "INSERT INTO vm_states (id, cluster_id, vmid, vm_name, status, vm_type, node, sampled_at) VALUES (?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), cluster_id, 101, "web", "running", "qemu", "pve", NOW),
    )
    conn.execute(
        "INSERT INTO backup_results (id, cluster_id, vmid, vm_name, node, upid, status, exit_code, start_time, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            str(uuid.uuid4()),
            cluster_id,
            101,
            "web",
            "pve",
            "UPID:pve:1:2:3:vzdump:101:root@pam:",
            "OK",
            0,
            NOW - 3600,
            NOW,
        ),
    )
    conn.commit()
    data = _build_data(conn, "pve")
    assert len(data["vms"]) == 1
    assert data["vms"][0]["vmid"] == 101
    assert data["summary"]["total_vms"] == 1


def test_build_data_failure_counted(conn, cluster_id):
    conn.execute(
        "INSERT INTO vm_states (id, cluster_id, vmid, vm_name, status, vm_type, node, sampled_at) VALUES (?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), cluster_id, 102, "db", "running", "qemu", "pve", NOW),
    )
    conn.execute(
        "INSERT INTO backup_results (id, cluster_id, vmid, vm_name, node, upid, status, exit_code, start_time, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            str(uuid.uuid4()),
            cluster_id,
            102,
            "db",
            "pve",
            "UPID:pve:1:2:3:vzdump:102:root@pam:",
            "ERROR: disk full",
            1,
            NOW - 3600,
            NOW,
        ),
    )
    conn.commit()
    data = _build_data(conn, "pve")
    assert data["summary"]["failure_events"] == 1
    assert data["summary"]["failure_vms"] == 1
