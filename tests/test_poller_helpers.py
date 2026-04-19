"""Tests for poller.py helper functions."""

import tempfile
import time
import uuid
from unittest.mock import MagicMock

import pytest

from pvewatch.database import connect, migrate
from pvewatch.poller import _import_batch_task, _import_single_task, _is_batch_task, poll_backup_tasks
from pvewatch.proxmox import TaskInfo

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


def _make_task(vmid=101, upid=None, exit_status="OK"):
    upid = upid or f"UPID:pve:1:2:3:vzdump:{vmid}:root@pam:"
    return TaskInfo(
        upid=upid,
        vmid=vmid,
        node="pve",
        status="stopped",
        exit_status=exit_status,
        start_time=NOW - 3600,
        end_time=NOW - 3000,
        duration_sec=600,
        log_tail="",
    )


# --- _is_batch_task ---


def test_is_batch_task_with_vmid():
    assert not _is_batch_task({"id": "101"})


def test_is_batch_task_no_id():
    assert _is_batch_task({"id": ""})
    assert _is_batch_task({})


def test_is_batch_task_non_numeric_id():
    assert _is_batch_task({"id": "all"})


# --- _import_single_task ---


def test_import_single_task_returns_none(conn, cluster_id):
    client = MagicMock()
    client.build_task_info.return_value = None
    result = _import_single_task(client, conn, cluster_id, {"upid": "UPID:pve:1:2:3:vzdump:101:root@pam:"}, {}, set())
    assert result == 0


def test_import_single_task_new(conn, cluster_id):
    client = MagicMock()
    task = _make_task(101)
    client.build_task_info.return_value = task
    result = _import_single_task(client, conn, cluster_id, {"upid": task.upid}, {}, set())
    assert result == 1


def test_import_single_task_already_known(conn, cluster_id):
    client = MagicMock()
    task = _make_task(101)
    client.build_task_info.return_value = task
    known = {task.upid}
    result = _import_single_task(client, conn, cluster_id, {"upid": task.upid}, {}, known)
    assert result == 0


# --- _import_batch_task ---


def test_import_batch_task_running(conn, cluster_id):
    client = MagicMock()
    raw = {"upid": "UPID:pve:1:2:3:vzdump:0:root@pam:", "status": "running"}
    result = _import_batch_task(client, conn, cluster_id, raw, {}, set())
    assert result == 0
    client.parse_batch_task.assert_not_called()


def test_import_batch_task_already_processed(conn, cluster_id):
    from pvewatch.database import kv_set

    client = MagicMock()
    upid = "UPID:pve:1:2:3:vzdump:0:root@pam:"
    kv_set(conn, f"batch_processed:{upid}", "1")
    raw = {"upid": upid, "status": "stopped"}
    result = _import_batch_task(client, conn, cluster_id, raw, {}, set())
    assert result == 0
    client.parse_batch_task.assert_not_called()


def test_import_batch_task_new(conn, cluster_id):
    client = MagicMock()
    upid = "UPID:pve:1:2:3:vzdump:0:root@pam:"
    task = _make_task(101, upid=f"{upid}|101")
    client.parse_batch_task.return_value = [task]
    raw = {"upid": upid, "status": "stopped"}
    result = _import_batch_task(client, conn, cluster_id, raw, {101: "web"}, set())
    assert result == 1


def test_import_batch_task_known_not_counted(conn, cluster_id):
    client = MagicMock()
    upid = "UPID:pve:1:2:3:vzdump:0:root@pam:"
    task = _make_task(101, upid=f"{upid}|101")
    client.parse_batch_task.return_value = [task]
    raw = {"upid": upid, "status": "stopped"}
    result = _import_batch_task(client, conn, cluster_id, raw, {}, {task.upid})
    assert result == 0


# --- poll_backup_tasks ---


def test_poll_backup_tasks_empty(conn, cluster_id):
    client = MagicMock()
    client.get_vzdump_tasks.return_value = []
    result = poll_backup_tasks(client, conn, cluster_id)
    assert result == []


def test_poll_backup_tasks_skips_no_upid(conn, cluster_id):
    client = MagicMock()
    client.get_vzdump_tasks.return_value = [{"id": "101"}]
    result = poll_backup_tasks(client, conn, cluster_id)
    assert result == []


def test_poll_backup_tasks_skips_known(conn, cluster_id):
    upid = "UPID:pve:1:2:3:vzdump:101:root@pam:"
    conn.execute(
        "INSERT INTO backup_results (id, cluster_id, vmid, vm_name, node, upid, status, exit_code, start_time, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), cluster_id, 101, "web", "pve", upid, "OK", 0, NOW - 3600, NOW),
    )
    conn.commit()
    client = MagicMock()
    client.get_vzdump_tasks.return_value = [{"upid": upid, "id": "101"}]
    result = poll_backup_tasks(client, conn, cluster_id)
    assert result == []
    client.build_task_info.assert_not_called()


def test_poll_backup_tasks_new_failure(conn, cluster_id):
    client = MagicMock()
    upid = "UPID:pve:1:2:3:vzdump:101:root@pam:"
    task = _make_task(101, upid=upid, exit_status="ERROR: disk full")
    client.get_vzdump_tasks.return_value = [{"upid": upid, "id": "101"}]
    client.build_task_info.return_value = task
    result = poll_backup_tasks(client, conn, cluster_id)
    assert len(result) == 1
    assert result[0].exit_status == "ERROR: disk full"


def test_poll_backup_tasks_ok_not_in_failures(conn, cluster_id):
    client = MagicMock()
    upid = "UPID:pve:1:2:3:vzdump:101:root@pam:"
    task = _make_task(101, upid=upid, exit_status="OK")
    client.get_vzdump_tasks.return_value = [{"upid": upid, "id": "101"}]
    client.build_task_info.return_value = task
    result = poll_backup_tasks(client, conn, cluster_id)
    assert result == []
