"""Weekly digest generation and delivery."""

import logging
import sqlite3
import time
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from pvewatch.alerts import _send_email
from pvewatch.config import Settings

log = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _fmt_duration(seconds: int | None) -> str:
    if not seconds:
        return "—"
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60}s"


def _fmt_gb(b: int) -> str:
    return f"{b / 1_073_741_824:.1f}"


def _group_backup_rows(rows: list) -> dict[int, dict]:
    vm_data: dict[int, dict] = {}
    for r in rows:
        vmid = r["vmid"]
        if vmid not in vm_data:
            vm_data[vmid] = {"vmid": vmid, "name": r["vm_name"] or f"VM {vmid}", "results": []}
        vm_data[vmid]["results"].append(dict(r))
    return vm_data


def _vm_dots(results: list, today: int) -> list[str]:
    day_map: dict[int, str] = {}
    for r in results:
        day = r["start_time"] // 86400
        day_map[day] = "ok" if r["status"] in ("OK", "") else "fail"
    return [day_map.get(today - (6 - i), "none") for i in range(7)]


def _build_vm_entry(data: dict, today: int) -> dict:
    results = data["results"]
    failures = sum(1 for r in results if r["status"] not in ("OK", ""))
    ok_results = [r for r in results if r["status"] in ("OK", "")]
    durations = [r["duration_sec"] for r in results if r["duration_sec"]]
    avg_dur = int(sum(durations) / len(durations)) if durations else None
    last_ok = max((r["start_time"] for r in ok_results), default=None)
    return {
        "name": data["name"],
        "total": len(results),
        "failures": failures,
        "avg_duration": _fmt_duration(avg_dur),
        "last_success": time.strftime("%b %d", time.localtime(last_ok)) if last_ok else None,
        "dots": _vm_dots(results, today),
    }


def _build_storage_out(storage_rows: list) -> list[dict]:
    sid_counts: dict[str, int] = {}
    for s in storage_rows:
        sid_counts[s["storage_id"]] = sid_counts.get(s["storage_id"], 0) + 1
    out = []
    for s in storage_rows:
        total = s["total_bytes"]
        used = s["used_bytes"]
        pct = (used / total * 100) if total else 0
        label = s["storage_id"]
        if sid_counts[label] > 1 and s["node"]:
            label = f"{s['node']}/{label}"
        out.append({"storage_id": label, "used_gb": _fmt_gb(used), "total_gb": _fmt_gb(total), "pct": pct})
    return out


def build_digest_data(conn: sqlite3.Connection, cluster_id: str, settings: Settings) -> dict:
    since = int(time.time()) - 7 * 86400
    today = int(time.time()) // 86400

    rows = conn.execute(
        """
        SELECT vmid, vm_name, status, start_time, end_time, duration_sec
        FROM backup_results
        WHERE cluster_id = ? AND start_time >= ?
        ORDER BY vmid, start_time ASC
        """,
        (cluster_id, since),
    ).fetchall()

    vm_data = _group_backup_rows(rows)
    vms_out = [_build_vm_entry(data, today) for _, data in sorted(vm_data.items())]

    storage_rows = conn.execute(
        """
        SELECT node, storage_id, used_bytes, total_bytes
        FROM storage_snapshots
        WHERE cluster_id = ?
          AND sampled_at = (
            SELECT MAX(sampled_at) FROM storage_snapshots s2
            WHERE s2.cluster_id = storage_snapshots.cluster_id
              AND s2.node = storage_snapshots.node
              AND s2.storage_id = storage_snapshots.storage_id
          )
        ORDER BY node, storage_id
        """,
        (cluster_id,),
    ).fetchall()

    node_row = conn.execute("SELECT value FROM kv WHERE key = 'node'").fetchone()
    node = node_row["value"] if node_row else settings.pve_node

    return {
        "vms": vms_out,
        "storage": _build_storage_out(storage_rows),
        "week_start": time.strftime("%b %d, %Y", time.localtime(since)),
        "node": node,
    }


def send_weekly_digest(
    conn: sqlite3.Connection,
    cluster_id: str,
    settings: Settings,
) -> None:
    if not (settings.alert_email_to and settings.alert_email_smtp_host):
        log.info("No email configured — skipping weekly digest")
        return

    data = build_digest_data(conn, cluster_id, settings)

    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=True)
    template = env.get_template("digest.html")
    html = template.render(**data)

    total_vms = len(data["vms"])
    failed_vms = sum(1 for v in data["vms"] if v["failures"] > 0)
    subject = f"PVEWatch Weekly Digest — {total_vms} VMs" + (
        f", {failed_vms} with failures" if failed_vms else ", all OK"
    )

    text_fallback = f"PVEWatch weekly digest: {total_vms} VMs, {failed_vms} failures. Enable HTML to view full report."

    ok = _send_email(settings, subject, text_fallback, html)
    if ok:
        log.info("Weekly digest sent to %s", settings.alert_email_to)
    else:
        log.error("Weekly digest delivery failed")
