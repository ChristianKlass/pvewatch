# DECISIONS.md

Architecture decisions log. Every non-obvious call recorded here with date and one-sentence reasoning.

---

**2026-04-20 — Use proxmoxer over raw httpx for the API client**
proxmoxer handles token auth headers, SSL verification flags, and the Proxmox-specific URL structure, saving ~150 lines of auth boilerplate we would otherwise maintain.

**2026-04-20 — SQLite over PostgreSQL**
The entire state for a single monitored cluster fits in a single small file; SQLite on a named Docker volume eliminates the need for a second container and makes backup/restore a file copy.

**2026-04-20 — stdlib sqlite3 over SQLAlchemy**
Queries are simple enough that an ORM adds more indirection than it removes; we write the SQL directly and keep the dependency count low.

**2026-04-20 — APScheduler over OS cron**
The agent runs inside a container where OS cron is not available by default; APScheduler provides in-process scheduling without requiring a second service.

**2026-04-20 — pydantic-settings for configuration**
Validates required fields at startup and gives clear error messages when environment variables are missing or wrong-typed, which is the most common user problem for self-hosted tools.

**2026-04-20 — smtplib (stdlib) over Resend/SendGrid**
Users configure their own SMTP server; no third-party email service dependency is a core product guarantee ("no data leaves your network").

**2026-04-20 — Target PVE vzdump only in v1, defer PBS**
PVE built-in backups cover the majority of homelab setups; PBS uses a separate API with different job types and would double the surface area for a first release.

**2026-04-20 — Web UI served with http.server + Jinja2, no framework**
The UI is read-only and renders a single page; adding Flask or FastAPI would triple the installed package footprint for a feature that is optional and could be cut if time runs short.

**2026-04-20 — No web UI auth (LAN-only design)**
The container is meant to run on a private LAN; adding auth adds setup friction and is a support burden; document clearly that the port should not be exposed publicly.
