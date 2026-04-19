"""Backup task poller: reads new vzdump tasks, stores results, triggers alerts."""

import logging
import sqlite3
import time
from uuid import uuid4

from pvewatch.config import Settings
from pvewatch.proxmox import ProxmoxClient, TaskInfo, VMInfo

log = logging.getLogger(__name__)


def _vm_name_map(conn: sqlite3.Connection, cluster_id: str) -> dict[int, str]:
    """Return {vmid: name} from the most recent vm_states snapshot."""
    rows = conn.execute(
        """
        SELECT DISTINCT vmid, vm_name
        FROM vm_states
        WHERE cluster_id = ?
          AND vm_name IS NOT NULL
        """,
        (cluster_id,),
    ).fetchall()
    return {row["vmid"]: row["vm_name"] for row in rows}


def _known_upids(conn: sqlite3.Connection, cluster_id: str) -> set[str]:
    rows = conn.execute(
        "SELECT upid FROM backup_results WHERE cluster_id = ?",
        (cluster_id,),
    ).fetchall()
    return {row["upid"] for row in rows}


def insert_backup_result(
    conn: sqlite3.Connection,
    cluster_id: str,
    task: TaskInfo,
    vm_name: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO backup_results
          (id, cluster_id, vmid, vm_name, node, upid, status, exit_code,
           start_time, end_time, duration_sec, size_bytes, log_tail, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(upid) DO UPDATE SET
          vmid       = excluded.vmid,
          vm_name    = COALESCE(excluded.vm_name, backup_results.vm_name),
          status     = excluded.status,
          exit_code  = excluded.exit_code,
          end_time   = excluded.end_time,
          duration_sec = excluded.duration_sec,
          log_tail   = excluded.log_tail
        """,
        (
            str(uuid4()),
            cluster_id,
            task.vmid,
            vm_name,
            task.node,
            task.upid,
            task.exit_status if task.exit_status else task.status,
            1 if (task.exit_status and task.exit_status != "OK") else 0,
            task.start_time,
            task.end_time,
            task.duration_sec,
            None,  # size_bytes: not returned by task API; future enhancement
            task.log_tail or None,
            int(time.time()),
        ),
    )
    conn.commit()


def _is_batch_task(raw: dict) -> bool:
    """True if this is a batch vzdump task (covers all VMs, no specific vmid)."""
    raw_id = raw.get("id", "")
    try:
        vmid = int(raw_id) if raw_id else 0
    except (ValueError, TypeError):
        vmid = 0
    return vmid == 0


def _batch_processed_key(upid: str) -> str:
    return f"batch_processed:{upid}"


def _process_batch(
    client: ProxmoxClient,
    conn: sqlite3.Connection,
    cluster_id: str,
    raw: dict,
    names: dict,
    known: set,
) -> list[TaskInfo]:
    """Parse a batch task log, insert per-VM results. Returns newly-failed tasks."""
    from pvewatch.database import kv_get, kv_set

    upid = raw.get("upid", "")
    if raw.get("status") == "running":
        return []

    if kv_get(conn, _batch_processed_key(upid)):
        return []

    vm_results = client.parse_batch_task(raw)
    failures = []
    for task in vm_results:
        if task.upid not in known:
            vm_name = names.get(task.vmid)
            insert_backup_result(conn, cluster_id, task, vm_name)
            if task.exit_status and task.exit_status != "OK":
                failures.append(task)
                log.warning("Backup FAILED (batch): VM %s (%s) — %s", task.vmid, vm_name or "?", task.exit_status)
            else:
                log.debug("Backup OK (batch): VM %s (%s)", task.vmid, vm_name or "?")

    kv_set(conn, _batch_processed_key(upid), "1")
    return failures


def poll_backup_tasks(
    client: ProxmoxClient,
    conn: sqlite3.Connection,
    cluster_id: str,
) -> list[TaskInfo]:
    """Poll for new completed backup tasks. Returns list of newly-failed tasks."""
    known = _known_upids(conn, cluster_id)
    names = _vm_name_map(conn, cluster_id)

    raw_tasks = client.get_vzdump_tasks()
    new_failures: list[TaskInfo] = []

    for raw in raw_tasks:
        upid = raw.get("upid", "")
        if not upid:
            continue

        if _is_batch_task(raw):
            new_failures.extend(_process_batch(client, conn, cluster_id, raw, names, known))
            continue

        if upid in known:
            continue

        task = client.build_task_info(raw)
        if task is None:
            continue

        vm_name = names.get(task.vmid)
        insert_backup_result(conn, cluster_id, task, vm_name)

        if task.exit_status and task.exit_status != "OK":
            new_failures.append(task)
            log.warning("Backup FAILED: VM %s (%s) on %s — %s", task.vmid, vm_name or "?", task.node, task.exit_status)
        else:
            log.debug("Backup OK: VM %s (%s)", task.vmid, vm_name or "?")

    return new_failures


def refresh_vm_names(
    client: ProxmoxClient,
    conn: sqlite3.Connection,
    cluster_id: str,
) -> None:
    """Fetch current VM/CT list and insert a new vm_states snapshot.

    Skips if a snapshot was already taken within the last 60 seconds to
    avoid duplicate rows when called multiple times on startup.
    """
    now = int(time.time())
    last = conn.execute("SELECT MAX(sampled_at) FROM vm_states WHERE cluster_id = ?", (cluster_id,)).fetchone()[0]
    if last and (now - last) < 60:
        return

    try:
        vms: list[VMInfo] = client.get_vms()
    except Exception as exc:
        log.warning("Could not fetch VM list: %s", exc)
        return

    for vm in vms:
        conn.execute(
            """
            INSERT INTO vm_states (id, cluster_id, vmid, vm_name, status, vm_type, node, sampled_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (str(uuid4()), cluster_id, vm.vmid, vm.name, vm.status, vm.vm_type, vm.node, now),
        )
    conn.commit()
    log.debug("Refreshed %d VM names", len(vms))


def _import_batch_task(
    client: ProxmoxClient,
    conn: sqlite3.Connection,
    cluster_id: str,
    raw: dict,
    names: dict,
    known: set,
) -> int:
    from pvewatch.database import kv_get, kv_set

    upid = raw.get("upid", "")
    if raw.get("status") == "running" or kv_get(conn, _batch_processed_key(upid)):
        return 0
    imported = 0
    for task in client.parse_batch_task(raw):
        if task.upid not in known:
            imported += 1
        insert_backup_result(conn, cluster_id, task, names.get(task.vmid))
    kv_set(conn, _batch_processed_key(upid), "1")
    return imported


def _import_single_task(
    client: ProxmoxClient,
    conn: sqlite3.Connection,
    cluster_id: str,
    raw: dict,
    names: dict,
    known: set,
) -> int:
    upid = raw.get("upid", "")
    task = client.build_task_info(raw)
    if task is None:
        return 0
    is_new = upid not in known
    insert_backup_result(conn, cluster_id, task, names.get(task.vmid))
    return 1 if is_new else 0


def import_history(
    client: ProxmoxClient,
    conn: sqlite3.Connection,
    cluster_id: str,
    settings: Settings,
) -> int:
    """Backfill backup task history on first run. Returns count of tasks imported."""
    from pvewatch.database import kv_get, kv_set

    if kv_get(conn, "history_imported"):
        return 0

    log.info("Importing backup history: last %d days...", settings.history_days)
    since = int(time.time()) - (settings.history_days * 86400)
    names = _vm_name_map(conn, cluster_id)
    known = _known_upids(conn, cluster_id)

    imported = 0
    for raw in client.get_vzdump_tasks(since=since):
        if not raw.get("upid"):
            continue
        if _is_batch_task(raw):
            imported += _import_batch_task(client, conn, cluster_id, raw, names, known)
        else:
            imported += _import_single_task(client, conn, cluster_id, raw, names, known)

    kv_set(conn, "history_imported", "1")
    log.info("History import complete: %d tasks across cluster", imported)
    return imported
