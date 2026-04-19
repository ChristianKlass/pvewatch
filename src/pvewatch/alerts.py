"""Alert delivery: SMTP email and Discord webhook."""

import json
import logging
import smtplib
import sqlite3
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from uuid import uuid4

import httpx

from pvewatch.config import Settings
from pvewatch.proxmox import TaskInfo

log = logging.getLogger(__name__)

_DISCORD_MAX_LEN = 1900  # leave room for markdown overhead


def _alert_already_sent(conn: sqlite3.Connection, alert_type: str, ref_key: str) -> bool:
    """Return True if we already sent this alert (deduplicate by alert_type + ref_key)."""
    row = conn.execute(
        "SELECT id FROM alerts_sent WHERE alert_type = ? AND payload LIKE ? LIMIT 1",
        (alert_type, f"%{ref_key}%"),
    ).fetchone()
    return row is not None


def _record_alert(
    conn: sqlite3.Connection,
    alert_type: str,
    target: str,
    payload: dict,
    success: bool,
) -> None:
    conn.execute(
        "INSERT INTO alerts_sent (id, alert_type, target, payload, sent_at, success) VALUES (?,?,?,?,?,?)",
        (str(uuid4()), alert_type, target, json.dumps(payload), int(time.time()), 1 if success else 0),
    )
    conn.commit()


def _send_email(settings: Settings, subject: str, body_text: str, body_html: str | None = None) -> bool:
    if not (settings.alert_email_to and settings.alert_email_smtp_host):
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.alert_email_from or settings.alert_email_smtp_user
        msg["To"] = settings.alert_email_to

        msg.attach(MIMEText(body_text, "plain"))
        if body_html:
            msg.attach(MIMEText(body_html, "html"))

        with smtplib.SMTP(settings.alert_email_smtp_host, settings.alert_email_smtp_port) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(settings.alert_email_smtp_user, settings.alert_email_smtp_pass)
            smtp.sendmail(
                settings.alert_email_from or settings.alert_email_smtp_user,
                settings.alert_email_to,
                msg.as_string(),
            )
        return True
    except Exception as exc:
        log.error("Email delivery failed: %s", exc)
        return False


def _send_discord(settings: Settings, content: str) -> bool:
    if not settings.alert_discord_webhook:
        return False
    try:
        payload = {"content": content[:_DISCORD_MAX_LEN]}
        r = httpx.post(settings.alert_discord_webhook, json=payload, timeout=10)
        r.raise_for_status()
        return True
    except Exception as exc:
        log.error("Discord delivery failed: %s", exc)
        return False


def send_backup_failure_alert(
    conn: sqlite3.Connection,
    settings: Settings,
    task: TaskInfo,
    vm_name: str | None,
) -> None:
    """Send a backup failure alert. Deduplicated: one alert per UPID."""
    if _alert_already_sent(conn, "backup_failure", task.upid):
        return

    display_name = f"{vm_name} (VM {task.vmid})" if vm_name else f"VM {task.vmid}"
    start_fmt = time.strftime("%Y-%m-%d %H:%M", time.localtime(task.start_time))
    duration_fmt = f"{task.duration_sec}s" if task.duration_sec else "unknown"

    subject = f"PVEWatch: Backup failed — {display_name}"

    text_body = (
        f"Backup FAILED on {task.node}\n\n"
        f"VM:       {display_name}\n"
        f"Time:     {start_fmt}\n"
        f"Duration: {duration_fmt}\n"
        f"Exit:     {task.exit_status}\n"
    )
    if task.log_tail:
        text_body += f"\nLast log lines:\n{task.log_tail}\n"

    discord_msg = (
        f"🔴 **Backup failed** — {display_name}\n"
        f"Node: `{task.node}` | Time: `{start_fmt}` | Exit: `{task.exit_status}`\n"
    )
    if task.log_tail:
        tail_trimmed = task.log_tail[-800:]
        discord_msg += f"```\n{tail_trimmed}\n```"

    payload_ref = {"upid": task.upid, "vmid": task.vmid}

    email_ok = _send_email(settings, subject, text_body)
    if email_ok:
        _record_alert(conn, "backup_failure", "email", payload_ref, True)

    discord_ok = _send_discord(settings, discord_msg)
    if discord_ok:
        _record_alert(conn, "backup_failure", "discord", payload_ref, True)

    if not email_ok and not discord_ok:
        log.error("All alert targets failed for backup failure %s", task.upid)
        _record_alert(conn, "backup_failure", "failed", payload_ref, False)


def send_storage_alert(
    conn: sqlite3.Connection,
    settings: Settings,
    storage_id: str,
    used_pct: float,
    used_bytes: int,
    total_bytes: int,
) -> None:
    """Send a storage threshold alert. Deduplicated: one per storage per 24h."""
    dedup_key = f"storage:{storage_id}:{time.strftime('%Y-%m-%d')}"
    if _alert_already_sent(conn, "storage_threshold", dedup_key):
        return

    def _fmt_gb(b: int) -> str:
        return f"{b / 1_073_741_824:.1f} GB"

    subject = f"PVEWatch: Storage high — {storage_id} at {used_pct:.0f}%"
    text_body = (
        f"Storage pool '{storage_id}' is at {used_pct:.1f}% capacity.\n\n"
        f"Used:  {_fmt_gb(used_bytes)}\n"
        f"Total: {_fmt_gb(total_bytes)}\n"
    )
    discord_msg = (
        f"⚠️ **Storage high** — `{storage_id}` at {used_pct:.0f}%\nUsed: {_fmt_gb(used_bytes)} / {_fmt_gb(total_bytes)}"
    )

    payload_ref = {"key": dedup_key, "storage_id": storage_id}

    email_ok = _send_email(settings, subject, text_body)
    if email_ok:
        _record_alert(conn, "storage_threshold", "email", payload_ref, True)

    discord_ok = _send_discord(settings, discord_msg)
    if discord_ok:
        _record_alert(conn, "storage_threshold", "discord", payload_ref, True)

    if not email_ok and not discord_ok:
        _record_alert(conn, "storage_threshold", "failed", payload_ref, False)
