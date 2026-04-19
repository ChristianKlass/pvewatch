"""Read-only web dashboard."""
import logging
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from jinja2 import Environment

log = logging.getLogger(__name__)

_INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PVEWatch — {{ node }}</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    font-size: 14px;
    color: #111827;
    background: #f3f4f6;
    min-height: 100vh;
  }
  a { color: inherit; text-decoration: none; }
  /* Layout */
  .topbar {
    background: #fff;
    border-bottom: 1px solid #e5e7eb;
    padding: 0 24px;
    display: flex;
    align-items: center;
    gap: 16px;
    height: 52px;
  }
  .topbar-title { font-weight: 600; font-size: 15px; }
  .topbar-meta { color: #6b7280; font-size: 13px; margin-left: auto; }
  .topbar-meta span { margin-left: 16px; }
  .main { max-width: 1100px; margin: 0 auto; padding: 24px; }
  /* Summary bar */
  .summary {
    display: flex;
    gap: 12px;
    margin-bottom: 20px;
    flex-wrap: wrap;
  }
  .stat {
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 12px 18px;
    min-width: 130px;
  }
  .stat-label { font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: #9ca3af; }
  .stat-value { font-size: 22px; font-weight: 600; margin-top: 2px; }
  .stat-value.ok { color: #16a34a; }
  .stat-value.warn { color: #d97706; }
  .stat-value.fail { color: #dc2626; }
  /* Card */
  .card {
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    margin-bottom: 20px;
    overflow: hidden;
  }
  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 16px;
    border-bottom: 1px solid #f3f4f6;
  }
  .card-title { font-weight: 600; font-size: 13px; }
  .days-toggle { display: flex; gap: 4px; }
  .days-toggle a {
    font-size: 12px;
    padding: 3px 10px;
    border-radius: 4px;
    border: 1px solid #e5e7eb;
    color: #6b7280;
  }
  .days-toggle a.active {
    background: #111827;
    border-color: #111827;
    color: #fff;
  }
  /* Table */
  table { width: 100%; border-collapse: collapse; }
  th {
    text-align: left;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: .05em;
    color: #9ca3af;
    padding: 8px 16px;
    border-bottom: 1px solid #f3f4f6;
    white-space: nowrap;
  }
  td { padding: 10px 16px; border-bottom: 1px solid #f9fafb; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: #fafafa; }
  /* VM name cell */
  .vm-name { font-weight: 500; }
  .vm-id { font-size: 11px; color: #9ca3af; margin-top: 1px; }
  /* Type badge */
  .badge {
    display: inline-block;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .04em;
    padding: 1px 6px;
    border-radius: 3px;
    vertical-align: middle;
  }
  .badge-qemu { background: #ede9fe; color: #7c3aed; }
  .badge-lxc  { background: #e0f2fe; color: #0369a1; }
  /* Dot strip */
  .dots { display: flex; gap: 3px; align-items: center; }
  .dot {
    width: 10px; height: 10px; border-radius: 50%;
    flex-shrink: 0;
  }
  .dot.ok   { background: #16a34a; }
  .dot.fail { background: #dc2626; }
  .dot.none { background: #e5e7eb; }
  .dot-label { font-size: 10px; color: #9ca3af; margin-left: 6px; white-space: nowrap; }
  /* Status pill */
  .pill {
    display: inline-block;
    font-size: 11px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 20px;
    white-space: nowrap;
  }
  .pill-ok     { background: #dcfce7; color: #16a34a; }
  .pill-fail   { background: #fee2e2; color: #dc2626; }
  .pill-warn   { background: #fef3c7; color: #d97706; }
  .pill-never  { background: #f3f4f6; color: #9ca3af; }
  /* Storage bar */
  .bar-wrap { background: #f3f4f6; border-radius: 3px; height: 6px; width: 100px; display: inline-block; vertical-align: middle; }
  .bar { height: 6px; border-radius: 3px; background: #3b82f6; min-width: 2px; }
  .bar.warn { background: #f59e0b; }
  .bar.crit { background: #dc2626; }
  /* Unattributed failures */
  .alert-row { background: #fff8f8; }
  .alert-row td { border-bottom: 1px solid #fee2e2; }
  /* Footer */
  .footer { text-align: center; font-size: 12px; color: #d1d5db; padding: 32px 0 16px; }
  .footer a { color: #9ca3af; }
  .footer a:hover { color: #111827; }
  /* Empty state */
  .empty { text-align: center; padding: 32px; color: #9ca3af; font-size: 13px; }
</style>
</head>
<body>

<div class="topbar">
  <span class="topbar-title">PVEWatch</span>
  <div class="topbar-meta">
    <span>{{ node }}</span>
    <span>Last poll: {{ last_poll }}</span>
  </div>
</div>

<div class="main">

  <div class="summary">
    <div class="stat">
      <div class="stat-label">VMs / LXCs</div>
      <div class="stat-value">{{ total_vms }}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Backed up ({{ days }}d)</div>
      <div class="stat-value ok">{{ backed_up }}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Failures ({{ days }}d)</div>
      <div class="stat-value {% if failures > 0 %}fail{% else %}ok{% endif %}">{{ failures }}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Never backed up</div>
      <div class="stat-value {% if never > 0 %}warn{% else %}ok{% endif %}">{{ never }}</div>
    </div>
  </div>

  <div class="card">
    <div class="card-header">
      <span class="card-title">Backup history</span>
      <div class="days-toggle">
        <a href="?days=7" {% if days == 7 %}class="active"{% endif %}>7d</a>
        <a href="?days=14" {% if days == 14 %}class="active"{% endif %}>14d</a>
        <a href="?days=30" {% if days == 30 %}class="active"{% endif %}>30d</a>
      </div>
    </div>
    <table>
      <thead>
        <tr>
          <th style="width:220px">Name</th>
          <th>Last {{ days }} days</th>
          <th style="width:110px">Status</th>
          <th style="width:130px">Last run</th>
        </tr>
      </thead>
      <tbody>
      {% for vm in vms %}
      <tr>
        <td>
          <div class="vm-name">
            {{ vm.name }}
            <span class="badge badge-{{ vm.vm_type }}">{{ vm.vm_type }}</span>
          </div>
          <div class="vm-id">{{ vm.vmid }}</div>
        </td>
        <td>
          <div class="dots">
            {% for d in vm.dots %}
              <div class="dot {{ d }}" title="{{ loop.revindex0 }} days ago"></div>
            {% endfor %}
            {% if vm.ok_count > 0 or vm.fail_count > 0 %}
            <span class="dot-label">{{ vm.ok_count }}✓{% if vm.fail_count %} {{ vm.fail_count }}✗{% endif %}</span>
            {% endif %}
          </div>
        </td>
        <td>
          {% if vm.last_status == 'OK' %}
            <span class="pill pill-ok">OK</span>
          {% elif vm.last_status and vm.last_status != '' %}
            <span class="pill pill-fail" title="{{ vm.last_status }}">FAILED</span>
          {% elif vm.stale %}
            <span class="pill pill-warn">STALE</span>
          {% else %}
            <span class="pill pill-never">NEVER</span>
          {% endif %}
        </td>
        <td style="color:#6b7280">{{ vm.last_run or '—' }}</td>
      </tr>
      {% else %}
      <tr><td colspan="4" class="empty">No VMs found</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>

  {% if unattributed %}
  <div class="card">
    <div class="card-header">
      <span class="card-title">Unattributed failures</span>
    </div>
    <table>
      <thead><tr><th>Time</th><th>Error</th></tr></thead>
      <tbody>
      {% for u in unattributed %}
      <tr class="alert-row">
        <td style="white-space:nowrap;color:#6b7280">{{ u.time }}</td>
        <td style="color:#dc2626;font-size:13px">{{ u.status[:120] }}</td>
      </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}

  {% if storage %}
  <div class="card">
    <div class="card-header">
      <span class="card-title">Storage</span>
    </div>
    <table>
      <thead><tr><th>Pool</th><th style="width:280px">Usage</th><th style="width:80px">Used</th></tr></thead>
      <tbody>
      {% for s in storage %}
      <tr>
        <td>{{ s.storage_id }}</td>
        <td>
          <div class="bar-wrap">
            <div class="bar {% if s.pct >= 85 %}crit{% elif s.pct >= 70 %}warn{% endif %}"
                 style="width:{{ [s.pct|int, 100]|min }}%"></div>
          </div>
          <span style="margin-left:8px;color:#6b7280;font-size:13px">{{ s.pct|int }}%</span>
        </td>
        <td style="color:#6b7280;font-size:13px">{{ s.used_gb }} / {{ s.total_gb }} GB</td>
      </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}

</div>

<div class="footer">
  <a href="https://git.markklass.dev/markklass/pvewatch">PVEWatch</a>
</div>

</body>
</html>
"""


def _build_index(conn: sqlite3.Connection, node: str, days: int = 7) -> str:
    now = int(time.time())
    since = now - days * 86400
    today = now // 86400

    # All known VMs/LXCs (one row per vmid — latest sample)
    vm_rows = conn.execute(
        """
        SELECT DISTINCT vmid, vm_name, vm_type
        FROM vm_states
        WHERE (vmid, sampled_at) IN (
            SELECT vmid, MAX(sampled_at) FROM vm_states GROUP BY vmid
        )
        ORDER BY vm_type, vm_name
        """
    ).fetchall()

    # All backup results within the window (excluding vmid=0)
    result_rows = conn.execute(
        """
        SELECT vmid, vm_name, status, start_time
        FROM backup_results
        WHERE start_time >= ? AND vmid != 0
        ORDER BY vmid, start_time ASC
        """,
        (since,),
    ).fetchall()

    # Most recent backup ever per VM (for last_run / stale detection)
    latest_rows = conn.execute(
        """
        SELECT vmid, vm_name, status, start_time
        FROM backup_results
        WHERE vmid != 0
          AND (vmid, start_time) IN (
              SELECT vmid, MAX(start_time) FROM backup_results WHERE vmid != 0 GROUP BY vmid
          )
        """
    ).fetchall()
    latest_by_vmid = {r["vmid"]: r for r in latest_rows}

    # Group window results by vmid
    results_by_vmid: dict[int, list] = {}
    for r in result_rows:
        results_by_vmid.setdefault(r["vmid"], []).append(r)

    vms_out = []
    for vm in vm_rows:
        vmid = vm["vmid"]
        results = results_by_vmid.get(vmid, [])
        latest = latest_by_vmid.get(vmid)

        day_map: dict[int, str] = {}
        for r in results:
            day = r["start_time"] // 86400
            # keep 'fail' if already set
            if day_map.get(day) != "fail":
                day_map[day] = "ok" if r["status"] in ("OK", "") else "fail"

        dots = [day_map.get(today - (days - 1 - i), "none") for i in range(days)]
        ok_count = sum(1 for d in dots if d == "ok")
        fail_count = sum(1 for d in dots if d == "fail")

        stale = False
        last_status = None
        last_run = None
        if latest:
            last_status = latest["status"]
            last_run = time.strftime("%b %d %H:%M", time.localtime(latest["start_time"]))
            # stale = last backup was > 8 days ago (expected daily but missed)
            stale = (now - latest["start_time"]) > 8 * 86400

        vms_out.append({
            "vmid": vmid,
            "name": vm["vm_name"] or f"VM {vmid}",
            "vm_type": vm["vm_type"] or "qemu",
            "dots": dots,
            "ok_count": ok_count,
            "fail_count": fail_count,
            "last_status": last_status,
            "last_run": last_run,
            "stale": stale,
        })

    # Summary stats
    total_vms = len(vms_out)
    backed_up = sum(1 for v in vms_out if v["ok_count"] > 0 or (v["last_status"] == "OK"))
    failures = sum(1 for v in vms_out if v["fail_count"] > 0)
    never = sum(1 for v in vms_out if not latest_by_vmid.get(v["vmid"]))

    # Unattributed failures (vmid=0)
    unattr_rows = conn.execute(
        """
        SELECT start_time, status FROM backup_results
        WHERE vmid = 0 AND status != 'OK' AND status != ''
        AND start_time >= ?
        ORDER BY start_time DESC LIMIT 10
        """,
        (since,),
    ).fetchall()
    unattributed = [
        {"time": time.strftime("%b %d %H:%M", time.localtime(r["start_time"])), "status": r["status"]}
        for r in unattr_rows
    ]

    # Storage
    storage_rows = conn.execute(
        """
        SELECT storage_id, used_bytes, total_bytes
        FROM storage_snapshots
        WHERE sampled_at = (
            SELECT MAX(sampled_at) FROM storage_snapshots s2
            WHERE s2.storage_id = storage_snapshots.storage_id
        )
        ORDER BY storage_id
        """
    ).fetchall()
    storage_out = []
    for s in storage_rows:
        total = s["total_bytes"]
        used = s["used_bytes"]
        pct = (used / total * 100) if total else 0
        storage_out.append({
            "storage_id": s["storage_id"],
            "used_gb": f"{used / 1_073_741_824:.1f}",
            "total_gb": f"{total / 1_073_741_824:.1f}",
            "pct": pct,
        })

    last_poll_ts = conn.execute("SELECT value FROM kv WHERE key='last_poll_time'").fetchone()
    last_poll = (
        time.strftime("%Y-%m-%d %H:%M", time.localtime(int(last_poll_ts["value"])))
        if last_poll_ts else "never"
    )

    env = Environment(autoescape=True)
    tmpl = env.from_string(_INDEX_TEMPLATE)
    return tmpl.render(
        node=node,
        last_poll=last_poll,
        vms=vms_out,
        storage=storage_out,
        unattributed=unattributed,
        days=days,
        total_vms=total_vms,
        backed_up=backed_up,
        failures=failures,
        never=never,
    )


def run_web_server(conn: sqlite3.Connection, node: str, port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path not in ("/", "/index.html"):
                self.send_response(404)
                self.end_headers()
                return
            qs = parse_qs(parsed.query)
            try:
                days = int(qs.get("days", ["7"])[0])
                if days not in (7, 14, 30):
                    days = 7
            except (ValueError, IndexError):
                days = 7
            html = _build_index(conn, node, days)
            body = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: object) -> None:
            log.debug("web: " + fmt, *args)

    server = HTTPServer(("", port), Handler)
    log.info("Web UI available at http://0.0.0.0:%d", port)
    server.serve_forever()
