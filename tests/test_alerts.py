"""Tests for alert deduplication and digest rendering."""
import json
import tempfile
import time

import pytest

from pvewatch.database import connect, migrate
from pvewatch.alerts import _alert_already_sent, _record_alert
from pvewatch.digest import build_digest_data
from pvewatch.proxmox import TaskInfo


@pytest.fixture
def conn():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db_path = f.name
    c = connect(db_path)
    migrate(c)
    yield c
    c.close()


def test_alert_not_sent_initially(conn):
    assert not _alert_already_sent(conn, "backup_failure", "UPID:pve:abc")


def test_alert_dedup(conn):
    upid = "UPID:pve:00123456:00ABCDEF:67F12345:vzdump:101:root@pam:"
    _record_alert(conn, "backup_failure", "discord", {"upid": upid}, True)
    assert _alert_already_sent(conn, "backup_failure", upid)


def test_alert_dedup_different_type(conn):
    upid = "UPID:pve:00123456:00ABCDEF:67F12345:vzdump:101:root@pam:"
    _record_alert(conn, "backup_failure", "discord", {"upid": upid}, True)
    # Same UPID but different alert type should not be deduplicated
    assert not _alert_already_sent(conn, "storage_threshold", upid)


def test_storage_dedup_daily(conn):
    dedup_key = f"storage:local:{time.strftime('%Y-%m-%d')}"
    assert not _alert_already_sent(conn, "storage_threshold", dedup_key)
    _record_alert(conn, "storage_threshold", "email", {"key": dedup_key}, True)
    assert _alert_already_sent(conn, "storage_threshold", dedup_key)


def test_digest_empty(conn):
    from unittest.mock import MagicMock
    settings = MagicMock()
    settings.pve_node = "pve"
    settings.history_days = 30

    # Insert a cluster row
    import uuid
    cluster_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO clusters (id, name, host, port, node, token_id, token_secret, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (cluster_id, "pve", "192.168.1.1", 8006, "pve", "tok", "sec", int(time.time())),
    )
    conn.commit()

    data = build_digest_data(conn, cluster_id, settings)
    assert "vms" in data
    assert "storage" in data
    assert isinstance(data["vms"], list)


def test_digest_html_renders(conn):
    """Digest template should produce valid HTML with VM data."""
    from uuid import uuid4
    from pvewatch.digest import send_weekly_digest, build_digest_data
    from pvewatch.database import kv_set
    import time

    cluster_id = str(uuid4())
    conn.execute(
        "INSERT INTO clusters (id, name, host, port, node, token_id, token_secret, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (cluster_id, "pve", "192.168.1.1", 8006, "pve", "tok", "sec", int(time.time())),
    )
    # Insert some backup results
    for i, (vmid, status) in enumerate([(101, "OK"), (102, "ERROR: disk full"), (101, "OK")]):
        conn.execute(
            "INSERT INTO backup_results "
            "(id, cluster_id, vmid, vm_name, node, upid, status, exit_code, start_time, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(uuid4()), cluster_id, vmid, f"vm-{vmid}", "pve",
             f"UPID:pve:000000{i:02d}:00000000:67F00000:vzdump:{vmid}:root@pam:",
             status, 0 if status == "OK" else 1,
             int(time.time()) - i * 3600, int(time.time())),
        )
    conn.commit()

    from unittest.mock import MagicMock
    settings = MagicMock()
    settings.pve_node = "pve"
    settings.history_days = 30

    data = build_digest_data(conn, cluster_id, settings)
    assert len(data["vms"]) == 2

    from jinja2 import Environment, FileSystemLoader
    from pathlib import Path
    env = Environment(
        loader=FileSystemLoader(str(Path(__file__).parent.parent / "src/pvewatch/templates")),
        autoescape=True,
    )
    html = env.get_template("digest.html").render(**data)
    assert "<table>" in html
    assert "vm-101" in html or "101" in html
