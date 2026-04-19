"""PVEWatch main entrypoint."""
import logging
import os
import signal
import sqlite3
import threading
import time
from uuid import uuid4

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from pvewatch.alerts import send_backup_failure_alert
from pvewatch.config import Settings
from pvewatch.database import connect, kv_set, migrate
from pvewatch.digest import send_weekly_digest
from pvewatch.poller import import_history, poll_backup_tasks, refresh_vm_names
from pvewatch.proxmox import ProxmoxClient
from pvewatch.storage import poll_storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pvewatch")

_DAY_TO_DOW = {
    "monday": "mon", "tuesday": "tue", "wednesday": "wed",
    "thursday": "thu", "friday": "fri", "saturday": "sat", "sunday": "sun",
}


def _ensure_cluster(conn: sqlite3.Connection, settings: Settings) -> str:
    """Return cluster_id, creating the row if it does not exist."""
    row = conn.execute("SELECT id FROM clusters WHERE host = ? AND node = ?",
                       (settings.pve_host, settings.pve_node)).fetchone()
    if row:
        return row["id"]
    cluster_id = str(uuid4())
    conn.execute(
        "INSERT INTO clusters (id, name, host, port, node, token_id, token_secret, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (cluster_id, settings.pve_node, settings.pve_host, settings.pve_port,
         settings.pve_node, settings.pve_token_id, settings.pve_token_secret, int(time.time())),
    )
    conn.commit()
    kv_set(conn, "node", settings.pve_node)
    return cluster_id


def _poll_cycle(client: ProxmoxClient, conn: sqlite3.Connection, cluster_id: str, settings: Settings) -> None:
    refresh_vm_names(client, conn, cluster_id)
    failed = poll_backup_tasks(client, conn, cluster_id, settings)
    for task in failed:
        vm_name_row = conn.execute(
            "SELECT vm_name FROM backup_results WHERE upid = ?", (task.upid,)
        ).fetchone()
        vm_name = vm_name_row["vm_name"] if vm_name_row else None
        send_backup_failure_alert(conn, settings, task, vm_name)
    poll_storage(client, conn, cluster_id, settings)
    kv_set(conn, "last_poll_time", str(int(time.time())))


def main() -> None:
    log.info("PVEWatch starting...")

    settings = Settings()  # raises ValidationError with clear message on bad config

    os.makedirs(settings.data_path, exist_ok=True)
    conn = connect(settings.db_path)
    migrate(conn)

    client = ProxmoxClient(settings)
    version = client.validate()
    log.info("Connected to Proxmox %s (version %s)", settings.pve_node, version)

    cluster_id = _ensure_cluster(conn, settings)

    # Backfill history on first run
    refresh_vm_names(client, conn, cluster_id)
    imported = import_history(client, conn, cluster_id, settings)
    if imported:
        log.info("History import: %d backup tasks loaded", imported)

    # Purge old records beyond HISTORY_DAYS
    cutoff = int(time.time()) - (settings.history_days * 86400)
    conn.execute("DELETE FROM backup_results WHERE start_time < ?", (cutoff,))
    conn.execute("DELETE FROM storage_snapshots WHERE sampled_at < ?", (cutoff,))
    conn.execute("DELETE FROM vm_states WHERE sampled_at < ?", (cutoff,))
    conn.commit()

    scheduler = BackgroundScheduler()

    scheduler.add_job(
        _poll_cycle,
        trigger=IntervalTrigger(minutes=settings.poll_interval_minutes),
        args=[client, conn, cluster_id, settings],
        id="poll",
        next_run_time=None,  # run immediately below, then schedule
    )

    dow = _DAY_TO_DOW.get(settings.digest_day, "sun")
    scheduler.add_job(
        send_weekly_digest,
        trigger=CronTrigger(day_of_week=dow, hour=settings.digest_hour, minute=0),
        args=[conn, cluster_id, settings],
        id="digest",
    )

    scheduler.start()

    # Run first poll immediately (don't wait POLL_INTERVAL_MINUTES)
    log.info("Monitoring active. Polling every %d minutes.", settings.poll_interval_minutes)
    _poll_cycle(client, conn, cluster_id, settings)

    # Reschedule the poll job now that we've run it once
    scheduler.reschedule_job("poll", trigger=IntervalTrigger(minutes=settings.poll_interval_minutes))

    if settings.web_ui_enabled:
        from pvewatch.web import run_web_server

        web_thread = threading.Thread(
            target=run_web_server,
            args=[conn, settings.pve_node, settings.web_ui_port],
            daemon=True,
        )
        web_thread.start()

    def _shutdown(signum: int, frame: object) -> None:
        log.info("Shutting down...")
        scheduler.shutdown(wait=False)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        while True:
            time.sleep(60)
    except SystemExit:
        pass


if __name__ == "__main__":
    main()
