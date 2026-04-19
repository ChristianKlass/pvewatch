# Architecture Decisions

Significant decisions made during design and development, in chronological order.

---

## 2026-04-19 — SQLite over PostgreSQL

**Decision:** Use SQLite as the only datastore.

**Reasoning:** PVEWatch is a single-container, single-user tool. SQLite requires no separate service, has zero ops overhead, and the write volume (one poll every 15 minutes) is nowhere near its limits. The entire database fits comfortably in memory. A volume mount gives persistence without complexity.

---

## 2026-04-19 — Inline Jinja2 template, no frontend build step

**Decision:** Embed the HTML dashboard as a string in `web.py`, rendered via Jinja2. No npm, no bundler, no static file serving.

**Reasoning:** Eliminates the entire frontend toolchain from the Docker build. The dashboard is read-only and largely static — there is no state management problem that warrants a JS framework. Vanilla CSS + minimal JS is sufficient. CDN fonts (JetBrains Mono via Google Fonts) are acceptable since the page degrades gracefully without them.

---

## 2026-04-19 — `http.server.ThreadingHTTPServer`, no web framework

**Decision:** Use Python's stdlib `ThreadingHTTPServer` rather than Flask, FastAPI, or similar.

**Reasoning:** The server handles three routes (`/`, `/api/status`, `/metrics`). A framework would add a dependency for no meaningful benefit at this scale. `ThreadingHTTPServer` gives concurrent request handling — the main practical requirement — with zero new dependencies.

---

## 2026-04-19 — Cluster-wide polling via `_node_names()`

**Decision:** On every poll, discover all online cluster nodes via the Proxmox cluster API and query each independently. Fall back to `PVE_NODE` if the cluster API fails.

**Reasoning:** A single-node configuration would silently miss VMs and backups on other nodes. Auto-discovery means the user never has to configure individual nodes. The fallback handles single-node installs and temporary cluster API failures gracefully.

---

## 2026-04-19 — Batch task log parsing

**Decision:** When Proxmox runs a "backup all VMs" job, it creates one task with no associated `vmid`. PVEWatch fetches the full task log and parses per-VM results from structured `INFO: Starting/Finished Backup of VM N` lines.

**Reasoning:** Most Proxmox clusters use the "all VMs" backup mode. Without log parsing, those backups would be invisible. Parsed results are stored with a synthetic UPID (`{batch_upid}|{vmid}`) and the batch UPID is recorded in the `kv` table so the 5000-line log is never re-fetched on subsequent polls.

---

## 2026-04-19 — `ON CONFLICT(upid) DO UPDATE` upserts

**Decision:** `insert_backup_result()` uses an upsert rather than checking existence before inserting.

**Reasoning:** Makes re-polling idempotent. If a task is seen twice (e.g. after a container restart), the second write updates fields that may have changed (exit status, end time) rather than failing or silently dropping the update.

---

## 2026-04-19 — Storage deduplication by (name, total_bytes)

**Decision:** When the same storage pool appears on multiple nodes with the same name and total capacity, it is shown once in the dashboard and API, attributed to the first node that reported it.

**Reasoning:** Shared NAS/PBS storage is visible to all cluster nodes with identical capacity. Showing it N times implies N separate pools. If two pools share a name but have different capacities they are genuinely separate and both are shown, with a node prefix to disambiguate.

---

## 2026-04-19 — Single `/api/status` endpoint, no versioning

**Decision:** The JSON API uses `/api/status`, not `/api/v1/status` or similar.

**Reasoning:** PVEWatch is self-hosted and distributed as a container. Users upgrade by pulling a new image — there is no backwards-compatibility contract with third parties. Version prefixes add complexity with no practical benefit at this scale.

---

## 2026-04-19 — `_build_data()` shared across all three endpoints

**Decision:** The dashboard HTML, JSON API, and Prometheus metrics all call `_build_data()`, which runs all DB queries once and returns a plain dict. Each endpoint formats that dict differently.

**Reasoning:** Avoids duplicate DB queries when different consumers hit the server simultaneously. Keeps data logic in one place — a change to how `fail_count` is calculated is reflected in all three outputs automatically.
