"""Minimal read-only web dashboard."""
import logging
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

log = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"

_INDEX_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PVEWatch</title>
<style>
  *{box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1a1a1a;margin:0;padding:16px 24px;background:#f9fafb}
  h1{font-size:18px;margin:0 0 4px}
  .sub{color:#6b7280;font-size:13px;margin-bottom:24px}
  .card{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:16px;margin-bottom:16px}
  table{width:100%;border-collapse:collapse}
  th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:#9ca3af;padding:4px 8px;border-bottom:1px solid #e5e7eb}
  td{padding:8px;font-size:14px;border-bottom:1px solid #f3f4f6}
  .dots{letter-spacing:3px;font-size:16px}
  .ok{color:#16a34a}.fail{color:#dc2626}.none{color:#d1d5db}
  .badge-ok{background:#dcfce7;color:#16a34a;border-radius:4px;padding:2px 8px;font-size:12px}
  .badge-fail{background:#fee2e2;color:#dc2626;border-radius:4px;padding:2px 8px;font-size:12px}
  .bar-wrap{background:#f3f4f6;border-radius:4px;height:6px;width:120px;display:inline-block;vertical-align:middle}
  .bar{height:6px;border-radius:4px;background:#3b82f6}
  .bar.warn{background:#f59e0b}.bar.crit{background:#dc2626}
  .meta{font-size:12px;color:#9ca3af;margin-top:16px}
</style>
</head>
<body>
<h1>PVEWatch</h1>
<p class="sub">{{ node }} · Last poll: {{ last_poll }}</p>

<div class="card">
  <table>
    <thead><tr><th>VM</th><th>Last 7 backups</th><th>Status</th><th>Last run</th></tr></thead>
    <tbody>
    {% for vm in vms %}
    <tr>
      <td>{{ vm.name }}</td>
      <td class="dots">
        {% for d in vm.dots %}
          {% if d == 'ok' %}<span class="ok">●</span>
          {% elif d == 'fail' %}<span class="fail">●</span>
          {% else %}<span class="none">○</span>{% endif %}
        {% endfor %}
      </td>
      <td>
        {% if vm.last_status == 'OK' %}<span class="badge-ok">OK</span>
        {% elif vm.last_status %}<span class="badge-fail">{{ vm.last_status[:30] }}</span>
        {% else %}—{% endif %}
      </td>
      <td>{{ vm.last_run or '—' }}</td>
    </tr>
    {% else %}
    <tr><td colspan="4" style="color:#9ca3af;text-align:center">No backup history yet</td></tr>
    {% endfor %}
    </tbody>
  </table>
</div>

{% if storage %}
<div class="card">
  <table>
    <thead><tr><th>Storage</th><th>Used</th><th></th></tr></thead>
    <tbody>
    {% for s in storage %}
    <tr>
      <td>{{ s.storage_id }}</td>
      <td>{{ s.used_gb }} GB / {{ s.total_gb }} GB ({{ s.pct|int }}%)</td>
      <td>
        <div class="bar-wrap">
          <div class="bar {% if s.pct >= 85 %}crit{% elif s.pct >= 70 %}warn{% endif %}"
               style="width:{{ [s.pct|int, 100]|min }}%"></div>
        </div>
      </td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
</div>
{% endif %}

<p class="meta">PVEWatch · <a href="https://git.markklass.dev/markklass/pvewatch">git.markklass.dev/markklass/pvewatch</a></p>
</body>
</html>
"""


def _build_index(conn: sqlite3.Connection, node: str) -> str:
    since = int(time.time()) - 7 * 86400
    today = int(time.time()) // 86400

    rows = conn.execute(
        """
        SELECT vmid, vm_name, status, start_time
        FROM backup_results
        WHERE start_time >= ?
        ORDER BY vmid, start_time ASC
        """,
        (since,),
    ).fetchall()

    vm_data: dict[int, dict] = {}
    for r in rows:
        vmid = r["vmid"]
        if vmid not in vm_data:
            vm_data[vmid] = {"vmid": vmid, "name": r["vm_name"] or f"VM {vmid}", "results": []}
        vm_data[vmid]["results"].append(dict(r))

    vms_out = []
    for vmid, data in sorted(vm_data.items()):
        results = data["results"]
        day_map: dict[int, str] = {}
        for r in results:
            day = r["start_time"] // 86400
            day_map[day] = "ok" if r["status"] in ("OK", "") else "fail"
        dots = [day_map.get(today - (6 - i), "none") for i in range(7)]
        last = max(results, key=lambda r: r["start_time"]) if results else None
        vms_out.append({
            "name": data["name"],
            "dots": dots,
            "last_status": last["status"] if last else None,
            "last_run": time.strftime("%b %d %H:%M", time.localtime(last["start_time"])) if last else None,
        })

    storage_rows = conn.execute(
        """
        SELECT storage_id, used_bytes, total_bytes
        FROM storage_snapshots
        WHERE sampled_at = (
          SELECT MAX(sampled_at) FROM storage_snapshots s2
          WHERE s2.storage_id = storage_snapshots.storage_id
        )
        """,
    ).fetchall()
    storage_out = []
    for s in storage_rows:
        total = s["total_bytes"]
        used = s["used_bytes"]
        pct = (used / total * 100) if total else 0
        storage_out.append({
            "storage_id": s["storage_id"],
            "used_gb": f"{used/1_073_741_824:.1f}",
            "total_gb": f"{total/1_073_741_824:.1f}",
            "pct": pct,
        })

    last_poll_ts = conn.execute("SELECT value FROM kv WHERE key='last_poll_time'").fetchone()
    last_poll = (
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(last_poll_ts["value"])))
        if last_poll_ts else "never"
    )

    env = Environment(autoescape=True)
    tmpl = env.from_string(_INDEX_TEMPLATE)
    return tmpl.render(vms=vms_out, storage=storage_out, node=node, last_poll=last_poll)


def run_web_server(conn: sqlite3.Connection, node: str, port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path not in ("/", "/index.html"):
                self.send_response(404)
                self.end_headers()
                return
            html = _build_index(conn, node)
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
