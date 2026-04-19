"""Storage pool monitoring."""

import logging
import sqlite3
import time
from uuid import uuid4

from pvewatch.alerts import send_storage_alert
from pvewatch.config import Settings
from pvewatch.proxmox import ProxmoxClient

log = logging.getLogger(__name__)


def poll_storage(
    client: ProxmoxClient,
    conn: sqlite3.Connection,
    cluster_id: str,
    settings: Settings,
) -> None:
    now = int(time.time())
    try:
        pools = client.get_storage()
    except Exception as exc:
        log.warning("Storage poll failed: %s", exc)
        return

    for pool in pools:
        conn.execute(
            "INSERT INTO storage_snapshots (id, cluster_id, node, storage_id, total_bytes, used_bytes, sampled_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid4()), cluster_id, pool.node, pool.storage_id, pool.total_bytes, pool.used_bytes, now),
        )
        used_pct = (pool.used_bytes / pool.total_bytes * 100) if pool.total_bytes else 0
        if used_pct >= settings.storage_alert_threshold:
            log.warning("Storage %s at %.1f%% — alerting", pool.storage_id, used_pct)
            send_storage_alert(conn, settings, pool.storage_id, used_pct, pool.used_bytes, pool.total_bytes)

    conn.commit()
    log.debug("Storage poll: %d pools sampled", len(pools))
