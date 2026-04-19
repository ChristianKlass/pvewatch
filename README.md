# PVEWatch

A single Docker container that tells you when your Proxmox VE backups fail, VMs go down, or storage is filling up. No hook scripts. No Prometheus. No Grafana.

PVEWatch reads your Proxmox task log via API token, stores per-VM backup history locally, and sends alerts to email and/or Discord.

```
docker run -d \
  --name pvewatch \
  -e PVE_HOST=192.168.1.100 \
  -e PVE_NODE=pve \
  -e PVE_TOKEN_ID=monitoring@pve!pvewatch \
  -e PVE_TOKEN_SECRET=your-secret-here \
  -e ALERT_DISCORD_WEBHOOK=https://discord.com/api/webhooks/... \
  -v pvewatch-data:/data \
  ghcr.io/markklass/pvewatch:latest
```

---

## What it monitors

- **Backup jobs** — alerts on any `vzdump` task that fails or exits non-zero, with the last 20 lines of the task log included in the alert
- **Backup history** — per-VM record of every backup result, duration, and size for the last 30 days
- **Storage pools** — alerts when any pool crosses 85% used (configurable)
- **VM state** — records VM/container state on each poll
- **Weekly digest** — Sunday morning summary: which VMs backed up, how long it took, storage levels

## What it does not do

- Monitor Proxmox Backup Server (PBS) — planned for a future release
- Replace a full monitoring stack for production infrastructure
- Modify anything on your Proxmox host

---

## Requirements

- Proxmox VE 7.4 or later
- Docker (or Podman with Docker compatibility)
- An SMTP server or Discord webhook for alert delivery

---

## Setup

### Step 1 — Create a read-only API token in Proxmox

PVEWatch needs a read-only API token. It never writes to your cluster.

1. Open the Proxmox web UI and go to **Datacenter → Permissions → Users**
2. Create a user: `monitoring@pve` (Realm: Proxmox VE authentication server)
3. Go to **Datacenter → Permissions → API Tokens**
4. Click **Add**, select user `monitoring@pve`, Token ID: `pvewatch`
5. **Uncheck** "Privilege Separation" (token inherits the user's permissions)
6. Click **Add** — copy the token secret shown. It will not be shown again.
7. Go to **Datacenter → Permissions → Add → User Permission**
   - Path: `/`
   - User: `monitoring@pve`
   - Role: `PVEAuditor`
   - Propagate: checked

`PVEAuditor` is a built-in Proxmox role with read-only access to all resources.

Your `PVE_TOKEN_ID` will be `monitoring@pve!pvewatch` and `PVE_TOKEN_SECRET` is what you copied.

### Step 2 — Create your .env file

```bash
cp .env.example .env
```

Edit `.env` with your values. Minimum required:

```env
PVE_HOST=192.168.1.100
PVE_NODE=pve
PVE_TOKEN_ID=monitoring@pve!pvewatch
PVE_TOKEN_SECRET=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

Plus at least one alert target:

```env
# Option A: Discord
ALERT_DISCORD_WEBHOOK=https://discord.com/api/webhooks/CHANNEL_ID/TOKEN

# Option B: Email
ALERT_EMAIL_SMTP_HOST=smtp.gmail.com
ALERT_EMAIL_SMTP_PORT=587
ALERT_EMAIL_SMTP_USER=you@gmail.com
ALERT_EMAIL_SMTP_PASS=your-app-password
ALERT_EMAIL_TO=you@example.com
ALERT_EMAIL_FROM=pvewatch@example.com
```

### Step 3 — Run

```bash
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
  ghcr.io/markklass/pvewatch:latest
```

### Step 4 — Verify

```bash
docker logs pvewatch
```

On first start you should see:
```
PVEWatch starting...
Connected to Proxmox pve (version 8.x.x)
Importing backup history: last 30 days...
Found 47 backup tasks across 12 VMs. 2 failures in the last 7 days.
Monitoring active. Next poll in 15 minutes.
```

Open http://your-docker-host:8080 to see the backup status dashboard.

---

## Configuration reference

| Variable | Default | Description |
|----------|---------|-------------|
| `PVE_HOST` | — | Proxmox node IP or hostname (required) |
| `PVE_PORT` | `8006` | Proxmox API port |
| `PVE_NODE` | — | Node name as shown in the Proxmox sidebar (required) |
| `PVE_TOKEN_ID` | — | API token ID, format: `user@realm!tokenname` (required) |
| `PVE_TOKEN_SECRET` | — | API token secret UUID (required) |
| `PVE_VERIFY_SSL` | `false` | Set `true` if your Proxmox has a valid SSL certificate |
| `ALERT_EMAIL_SMTP_HOST` | — | SMTP server hostname |
| `ALERT_EMAIL_SMTP_PORT` | `587` | SMTP port |
| `ALERT_EMAIL_SMTP_USER` | — | SMTP username |
| `ALERT_EMAIL_SMTP_PASS` | — | SMTP password or app password |
| `ALERT_EMAIL_TO` | — | Recipient address for alerts and digests |
| `ALERT_EMAIL_FROM` | — | From address |
| `ALERT_DISCORD_WEBHOOK` | — | Discord webhook URL |
| `POLL_INTERVAL_MINUTES` | `15` | How often to check for new backup tasks |
| `DIGEST_DAY` | `sunday` | Day to send the weekly digest |
| `DIGEST_HOUR` | `9` | Hour to send the digest (0–23, container local time) |
| `STORAGE_ALERT_THRESHOLD` | `85` | Storage usage % that triggers an alert |
| `WEB_UI_ENABLED` | `true` | Enable the read-only web dashboard |
| `WEB_UI_PORT` | `8080` | Port for the web dashboard |
| `DATA_PATH` | `/data` | Path inside the container for SQLite database |
| `HISTORY_DAYS` | `30` | Days of backup history to retain |

---

## Troubleshooting

**`Authentication failed` on startup**

Check `PVE_TOKEN_ID` format — it must be `user@realm!tokenname` e.g. `monitoring@pve!pvewatch`. Check that the token secret is correct (it was only shown once when created).

**`SSL certificate verify failed`**

Most Proxmox installations use a self-signed certificate. Set `PVE_VERIFY_SSL=false` (the default). If you have Let's Encrypt configured for Proxmox, set it to `true`.

**No backup results appearing**

Check `PVE_NODE` matches exactly the node name shown in your Proxmox web UI sidebar (it is case-sensitive). Verify the `PVEAuditor` permission was applied with Propagate checked.

**Email alerts not arriving**

For Gmail: enable 2FA on your Google account and generate an App Password at https://myaccount.google.com/apppasswords. Use the app password as `ALERT_EMAIL_SMTP_PASS`, not your regular Gmail password.

For Office 365: Microsoft retired basic SMTP AUTH in September 2025. Use Discord instead, or configure an SMTP relay service.

**Discord webhook not working**

Ensure the webhook URL starts with `https://discord.com/api/webhooks/`. Test it:
```bash
curl -X POST -H 'Content-Type: application/json' \
  -d '{"content":"PVEWatch test"}' \
  YOUR_WEBHOOK_URL
```

**Container exits immediately**

Run `docker logs pvewatch`. If the error is `No alert target configured`, add at least one of `ALERT_DISCORD_WEBHOOK` or `ALERT_EMAIL_TO`.

---

## How it works

PVEWatch polls the Proxmox task API (`GET /nodes/{node}/tasks?typefilter=vzdump`) every 15 minutes. For each new completed backup task it has not seen before, it fetches the task status and the last 20 lines of the task log, then stores the result in a local SQLite database. If the task exit status is not `OK`, it sends an alert immediately.

No changes are made to your Proxmox host. No hook scripts required. The SQLite database lives in the Docker volume at `/data/pvewatch.db`.

---

## Scope

PVEWatch v1 monitors **Proxmox VE built-in backups (vzdump) only**. PBS monitoring is planned. Feature requests for Synology, TrueNAS, Docker, or other platforms will not be accepted in v1 — this tool does one thing well.

---

## License

MIT. See [LICENSE](LICENSE).
