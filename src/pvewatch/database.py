import sqlite3
import time
from pathlib import Path

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class Connection:
    """Thin adapter over sqlite3.Connection or a psycopg2 connection."""

    def __init__(self, raw, dialect: str) -> None:
        self._raw = raw
        self._dialect = dialect  # "sqlite" | "postgres"

    def _sql(self, sql: str) -> str:
        if self._dialect == "postgres":
            return sql.replace("?", "%s")
        return sql

    def execute(self, sql: str, params=()):
        if self._dialect == "postgres":
            cur = self._raw.cursor()
            cur.execute(self._sql(sql), params)
            return cur
        return self._raw.execute(sql, params)

    def executemany(self, sql: str, params_seq):
        if self._dialect == "postgres":
            cur = self._raw.cursor()
            cur.executemany(self._sql(sql), params_seq)
            return cur
        return self._raw.executemany(sql, params_seq)

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()


def connect(url_or_path: str) -> Connection:
    if url_or_path.startswith(("postgresql://", "postgres://")):
        import psycopg2
        from psycopg2.extras import RealDictCursor

        raw = psycopg2.connect(url_or_path, cursor_factory=RealDictCursor)
        return Connection(raw, "postgres")
    # "memory" or ":memory:" → in-memory SQLite (no persistence, history re-pulled on restart)
    path = ":memory:" if url_or_path in ("memory", ":memory:") else url_or_path
    raw = sqlite3.connect(path, check_same_thread=False)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    return Connection(raw, "sqlite")


def migrate(conn: Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL)"
    )
    conn.commit()

    applied = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()}

    migration_files = sorted(_MIGRATIONS_DIR.glob("*.sql"), key=lambda p: int(p.stem.split("_")[0]))
    for path in migration_files:
        version = int(path.stem.split("_")[0])
        if version in applied:
            continue
        for stmt in path.read_text().split(";"):
            stmt = stmt.strip()
            if not stmt:
                continue
            # ALTER COLUMN TYPE is postgres-only; SQLite type affinity handles large ints natively
            if conn._dialect == "sqlite" and "ALTER COLUMN" in stmt.upper():
                continue
            conn.execute(stmt)
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (version, int(time.time())),
        )
        conn.commit()


def kv_get(conn: Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def kv_set(conn: Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
