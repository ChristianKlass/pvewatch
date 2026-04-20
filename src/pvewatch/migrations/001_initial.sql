CREATE TABLE clusters (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    host       TEXT NOT NULL,
    port       INTEGER NOT NULL DEFAULT 8006,
    node       TEXT NOT NULL,
    token_id   TEXT NOT NULL,
    token_secret TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE backup_results (
    id           TEXT PRIMARY KEY,
    cluster_id   TEXT NOT NULL REFERENCES clusters(id),
    vmid         INTEGER NOT NULL,
    vm_name      TEXT,
    node         TEXT NOT NULL,
    upid         TEXT UNIQUE NOT NULL,
    status       TEXT NOT NULL,
    exit_code    INTEGER,
    start_time   INTEGER NOT NULL,
    end_time     INTEGER,
    duration_sec INTEGER,
    size_bytes   BIGINT,
    log_tail     TEXT,
    created_at   INTEGER NOT NULL
);

CREATE INDEX idx_backup_results_cluster_time
    ON backup_results(cluster_id, start_time DESC);

CREATE INDEX idx_backup_results_cluster_vm_time
    ON backup_results(cluster_id, vmid, start_time DESC);

CREATE TABLE storage_snapshots (
    id          TEXT PRIMARY KEY,
    cluster_id  TEXT NOT NULL REFERENCES clusters(id),
    storage_id  TEXT NOT NULL,
    total_bytes BIGINT NOT NULL,
    used_bytes  BIGINT NOT NULL,
    sampled_at  INTEGER NOT NULL
);

CREATE INDEX idx_storage_snapshots_cluster_storage_time
    ON storage_snapshots(cluster_id, storage_id, sampled_at DESC);

CREATE TABLE vm_states (
    id         TEXT PRIMARY KEY,
    cluster_id TEXT NOT NULL REFERENCES clusters(id),
    vmid       INTEGER NOT NULL,
    vm_name    TEXT,
    status     TEXT NOT NULL,
    vm_type    TEXT NOT NULL,
    sampled_at INTEGER NOT NULL
);

CREATE INDEX idx_vm_states_cluster_vm_time
    ON vm_states(cluster_id, vmid, sampled_at DESC);

CREATE TABLE alerts_sent (
    id         TEXT PRIMARY KEY,
    alert_type TEXT NOT NULL,
    target     TEXT NOT NULL,
    payload    TEXT,
    sent_at    INTEGER NOT NULL,
    success    INTEGER NOT NULL DEFAULT 1
);

-- Generic key-value store for internal state
CREATE TABLE kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
