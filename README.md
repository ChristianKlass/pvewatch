# PVEWatch

A single Docker container that tells you when your Proxmox VE backups fail, VMs go down, or storage is filling up. No hook scripts. No Prometheus. No Grafana.

PVEWatch reads your Proxmox task log via API token, stores per-VM backup history in SQLite, and sends alerts to email and/or Discord.

---

## What it monitors

- **Backup jobs** — alerts on any `vzdump` task that fails or exits non-zero, with the last 20 lines of the task log included in the alert
- **Batch backups** — "backup all VMs" jobs (single task covering all VMs) are parsed per-VM from the task log
- **Backup history** — per-VM heatmap of every backup result for the last 3–30 days, visible in the web dashboard
- **Storage pools** — alerts when any pool crosses the threshold (default 85%)
- **Weekly digest** — Sunday morning summary: which VMs backed up, storage levels, failure count

## What it does not do

- Monitor Proxmox Backup Server (PBS) directly — it sees PBS-destined backups via the Proxmox task log, but does not query PBS itself
- Modify anything on your Proxmox host

---

## Requirements

- Proxmox VE 7.4 or later (single node or cluster)
- Docker or Podman
- An SMTP server or Discord webhook for alert delivery

---

## Setup

### Step 1 — Create a read-only API token in Proxmox

PVEWatch never writes to your cluster. It needs a PVEAuditor token.

1. **Datacenter → Permissions → Users** — create `monitoring@pve` (Realm: Proxmox VE authentication server)
2. **Datacenter → Permissions → API Tokens** → Add
   - User: `monitoring@pve`, Token ID: `pvewatch`
   - **Uncheck** "Privilege Separation"
   - Copy the secret — it is only shown once
3. **Datacenter → Permissions → Add → User Permission**
   - Path: `/`, User: `monitoring@pve`, Role: `PVEAuditor`, Propagate: checked

Your `PVE_TOKEN_ID` will be `monitoring@pve!pvewatch`.

### Step 2 — Configure

```bash
cp .env.example .env
```

Minimum required:

```env
PVE_HOST=192.168.1.100
PVE_NODE=pve
PVE_TOKEN_ID=monitoring@pve!pvewatch
PVE_TOKEN_SECRET=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

Plus at least one alert target:

```env
# Discord
ALERT_DISCORD_WEBHOOK=https://discord.com/api/webhooks/CHANNEL_ID/TOKEN

# Email (SMTP)
ALERT_EMAIL_SMTP_HOST=smtp.gmail.com
ALERT_EMAIL_SMTP_PORT=587
ALERT_EMAIL_SMTP_USER=you@gmail.com
ALERT_EMAIL_SMTP_PASS=your-app-password
ALERT_EMAIL_TO=you@example.com
ALERT_EMAIL_FROM=pvewatch@example.com
```

### Step 3 — Build and run

```bash
docker build -t pvewatch:latest .
docker compose up -d
```

Or without compose:

```bash
docker run -d \
  --name pvewatch \
  --env-file .env \
  -v pvewatch-data:/data \
  -p 8080:8080 \
  --restart unless-stopped \
  pvewatch:latest
```

### Step 4 — Verify

```bash
docker logs pvewatch
```

Expected on first start:
```
PVEWatch starting...
Connected to Proxmox pve (version 9.x.x)
Importing backup history: last 30 days...
History import complete: 312 tasks across cluster
Monitoring active. Polling every 15 minutes.
```

Open `http://your-docker-host:8080` for the backup dashboard.

---

## Multi-node clusters

No extra configuration needed. PVEWatch connects to `PVE_HOST` and uses the cluster API to discover all online nodes, then polls each node's task log independently. All VMs and containers across the cluster appear in the dashboard automatically.

`PVE_NODE` is used as a fallback if the cluster API is unreachable, and for storage monitoring (storage is queried per-node — only the configured node's pools are shown).

---

## Configuration reference

| Variable | Default | Description |
|----------|---------|-------------|
| `PVE_HOST` | — | Proxmox node IP or hostname (required) |
| `PVE_PORT` | `8006` | Proxmox API port |
| `PVE_NODE` | — | Node name as shown in Proxmox sidebar (required; used as fallback and for storage) |
| `PVE_TOKEN_ID` | — | API token ID, format `user@realm!tokenname` (required) |
| `PVE_TOKEN_SECRET` | — | API token secret UUID (required) |
| `PVE_VERIFY_SSL` | `false` | Set `true` if Proxmox has a valid SSL cert |
| `ALERT_EMAIL_SMTP_HOST` | — | SMTP server hostname |
| `ALERT_EMAIL_SMTP_PORT` | `587` | SMTP port |
| `ALERT_EMAIL_SMTP_USER` | — | SMTP username |
| `ALERT_EMAIL_SMTP_PASS` | — | SMTP password or app password |
| `ALERT_EMAIL_TO` | — | Alert recipient address |
| `ALERT_EMAIL_FROM` | — | From address |
| `ALERT_DISCORD_WEBHOOK` | — | Discord webhook URL |
| `POLL_INTERVAL_MINUTES` | `15` | How often to check for new backup tasks |
| `DIGEST_DAY` | `sunday` | Day to send the weekly digest |
| `DIGEST_HOUR` | `9` | Hour to send the digest (0–23, container local time) |
| `STORAGE_ALERT_THRESHOLD` | `85` | Storage usage % that triggers an alert |
| `WEB_UI_ENABLED` | `true` | Enable the read-only web dashboard |
| `WEB_UI_PORT` | `8080` | Port for the web dashboard |
| `DATA_PATH` | `/data` | Path inside container for SQLite database |
| `HISTORY_DAYS` | `30` | Days of backup history to import on first start |

---

## Dashboard

The web UI is read-only and requires no authentication. Open `http://your-docker-host:8080`.

- Summary stats: total VMs, backed-up count, failure events (with unresolved indicator), never-backed-up count
- Per-VM backup heatmap with 3/5/7/14/30 day range selector
- Sortable columns: Node, VM/Container, Status, Last backup
- Per-node filter toggle for both VMs and storage pools
- Storage pool usage cards, deduplicated across nodes
- Four colour themes: Dark, Light, Monokai, Solarized — persists in browser

---

## API

All endpoints are unauthenticated and served on the same port as the dashboard. Requests are handled concurrently.

### `GET /api/status`

Returns a JSON snapshot of current cluster state. Accepts an optional `?days=` query parameter (3, 5, 7, 14, or 30 — default 7) which controls the backup history window.

```json
{
  "node": "proxmox",
  "last_poll": "2026-04-20 13:00",
  "last_poll_ts": 1776627197,
  "days": 7,
  "summary": {
    "total_vms": 16,
    "backed_up": 16,
    "failure_events": 2,
    "failure_vms": 1,
    "unresolved_failures": 0,
    "never_backed_up": 0
  },
  "vms": [ ... ],
  "vm_nodes": ["prox2", "proxmox"],
  "storage": [ ... ],
  "storage_nodes": ["prox2", "proxmox"],
  "unattributed": [ ... ]
}
```

**Top-level fields**

| Field | Type | Description |
|-------|------|-------------|
| `node` | string | Configured primary node name |
| `last_poll` | string | Human-readable time of last successful Proxmox poll |
| `last_poll_ts` | integer | Unix timestamp of last successful poll |
| `days` | integer | History window in use for this response |
| `vm_nodes` | string[] | Ordered list of unique node names that have VMs |
| `storage_nodes` | string[] | Ordered list of unique node names that have storage |
| `unattributed` | object[] | Batch task failures that could not be attributed to a specific VM — each has `time` (string) and `status` (string) |

**`summary` object**

| Field | Type | Description |
|-------|------|-------------|
| `total_vms` | integer | Total VMs and containers known to PVEWatch |
| `backed_up` | integer | VMs with at least one successful backup in the window |
| `failure_events` | integer | Total individual failed backup days across all VMs in the window |
| `failure_vms` | integer | Number of distinct VMs that had at least one failure in the window |
| `unresolved_failures` | integer | VMs whose *most recent* backup is a failure (not yet recovered) |
| `never_backed_up` | integer | VMs with no backup record at all |

**`vms` array — each object**

| Field | Type | Description |
|-------|------|-------------|
| `vmid` | integer | Proxmox VM ID |
| `name` | string | VM or container name |
| `vm_type` | string | `"qemu"` or `"lxc"` |
| `node` | string | Cluster node the VM lives on |
| `dots` | string[] | Per-day backup result for the window, oldest→newest: `"ok"`, `"fail"`, or `"none"` |
| `ok_count` | integer | Number of successful backup days in the window |
| `fail_count` | integer | Number of failed backup days in the window |
| `last_status` | string\|null | Exit status of the most recent backup ever (`"OK"`, error string, or `null`) |
| `last_run` | string\|null | Human-readable timestamp of most recent backup |
| `last_run_ts` | integer | Unix timestamp of most recent backup (0 if never) |
| `stale` | boolean | `true` if most recent backup is more than 8 days ago |

**`storage` array — each object**

| Field | Type | Description |
|-------|------|-------------|
| `storage_id` | string | Pool name as shown in Proxmox |
| `node` | string | Node this pool belongs to |
| `used_bytes` | integer | Bytes used |
| `total_bytes` | integer | Total capacity in bytes |
| `used_gb` | string | Used space formatted as GB (1 decimal place) |
| `total_gb` | string | Total capacity formatted as GB |
| `pct` | float | Usage percentage (0–100) |

Shared storage visible from multiple nodes (same name and same total capacity) is deduplicated — it appears once attributed to the first node that reported it.

---

### `GET /metrics`

Returns Prometheus-format metrics. Scrape this endpoint with your Prometheus instance. The `days` query parameter is not supported here — the window always uses the configured default (7 days).

The primary value-add over the [native Proxmox exporter](https://github.com/prometheus-pve/prometheus-pve-exporter) is per-VM backup outcome history, which Proxmox does not expose as metrics.

**Cluster-level gauges**

| Metric | Description |
|--------|-------------|
| `pvewatch_vms_total` | Total VMs and containers |
| `pvewatch_vms_backed_up` | VMs with at least one successful backup in the window |
| `pvewatch_vms_never_backed_up` | VMs with no backup record |
| `pvewatch_backup_failure_events` | Total failed backup days in the window |
| `pvewatch_vms_unresolved_failures` | VMs whose most recent backup is still a failure |
| `pvewatch_last_poll_timestamp_seconds` | Unix timestamp of the last successful Proxmox poll |

**Per-VM gauges** — labels: `vmid`, `vm`, `node`, `type`

| Metric | Description |
|--------|-------------|
| `pvewatch_backup_last_success_timestamp_seconds` | Unix timestamp of the most recent *successful* backup. `0` if the VM has never had a successful backup. |
| `pvewatch_backup_last_status` | Most recent backup result: `1`=ok, `0`=failed, `-1`=stale (>8 days ago), `-2`=never |
| `pvewatch_backup_failures_window` | Number of failed backup days in the current window |

**Per-pool gauges** — labels: `pool`, `node`

| Metric | Description |
|--------|-------------|
| `pvewatch_storage_used_bytes` | Bytes used |
| `pvewatch_storage_total_bytes` | Total capacity in bytes |

**Example Alertmanager rule**

```yaml
- alert: VMBackupMissing
  expr: time() - pvewatch_backup_last_success_timestamp_seconds > 86400 * 2
  for: 1h
  labels:
    severity: warning
  annotations:
    summary: "No successful backup for {{ $labels.vm }} in 48h"
```

---

## Troubleshooting

**`Authentication failed` on startup**

Check `PVE_TOKEN_ID` format — must be `user@realm!tokenname` e.g. `monitoring@pve!pvewatch`. The secret is the UUID copied when the token was created.

**`SSL certificate verify failed`**

Most Proxmox installs use a self-signed cert. Set `PVE_VERIFY_SSL=false` (the default).

**No backup results / all VMs show no history**

1. Confirm the token has `PVEAuditor` on path `/` with Propagate checked.
2. Check whether your backup jobs are "backup all VMs" jobs — these are batch tasks. PVEWatch parses them from the task log. If you only ever ran batch backups, the per-VM results come from log parsing, not the task API directly.
3. Run `docker logs pvewatch` and look for `History import complete: N tasks` — if N is 0, the token likely lacks permission to read tasks.

**VMs appear on the wrong node**

Not an issue — PVEWatch queries all cluster nodes and the cluster resource API, so VM placement does not matter.

**Email alerts not arriving**

For Gmail: generate an App Password at https://myaccount.google.com/apppasswords and use it as `ALERT_EMAIL_SMTP_PASS`.

**Discord webhook not working**

Test it directly:
```bash
curl -X POST -H 'Content-Type: application/json' \
  -d '{"content":"PVEWatch test"}' \
  YOUR_WEBHOOK_URL
```

**Container exits immediately**

Run `docker logs pvewatch`. If the error is `No alert target configured`, add at least one of `ALERT_DISCORD_WEBHOOK` or `ALERT_EMAIL_TO`.

---

## How it works

On startup, PVEWatch imports the last `HISTORY_DAYS` of backup tasks from all cluster nodes into a local SQLite database. After that it polls every `POLL_INTERVAL_MINUTES`.

For each poll it:
1. Fetches `vzdump` tasks from every online cluster node
2. For single-VM tasks: stores the result directly
3. For batch tasks (all-VM jobs): fetches the full task log and parses per-VM start/finish/error lines
4. For any new failure, sends an immediate alert with the last 20 log lines

Nothing is written to your Proxmox host. The SQLite database lives at `/data/pvewatch.db` inside the container volume.

---

## License

MIT. See [LICENSE](LICENSE).
