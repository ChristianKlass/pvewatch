"""Tests for reopening a postgres connection the server closed (failover/restart).

Uses fake raw connections, so psycopg2 and a server are not needed.
"""

import pytest

from pvewatch.database import Connection


class _FakeCursor:
    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=()):
        if self._raw.closed:
            raise RuntimeError("connection already closed")
        self._raw.statements.append(sql)

    def executemany(self, sql, params_seq):
        self.execute(sql)


class _FakeRaw:
    def __init__(self):
        self.closed = 0
        self.statements = []
        self.rollbacks = 0

    def cursor(self):
        return _FakeCursor(self)

    def rollback(self):
        if self.closed:
            raise RuntimeError("connection already closed")
        self.rollbacks += 1


def _conn():
    opened = []

    def reconnect():
        raw = _FakeRaw()
        opened.append(raw)
        return raw

    first = _FakeRaw()
    return Connection(first, "postgres", reconnect=reconnect), first, opened


def test_open_connection_is_reused():
    conn, first, opened = _conn()
    conn.execute("SELECT 1")
    conn.execute("SELECT 2")
    assert opened == []
    assert first.statements == ["SELECT 1", "SELECT 2"]


def test_closed_connection_is_reopened_on_next_execute():
    conn, first, opened = _conn()
    first.closed = 2  # what psycopg2 sets after the server drops the socket
    conn.execute("SELECT 1")
    assert len(opened) == 1
    assert opened[0].statements == ["SELECT 1"]


def test_closed_connection_is_reopened_on_executemany():
    conn, first, opened = _conn()
    first.closed = 1
    conn.executemany("INSERT INTO t VALUES (?)", [(1,), (2,)])
    assert len(opened) == 1
    assert opened[0].statements == ["INSERT INTO t VALUES (%s)"]


def test_rollback_on_closed_connection_does_not_raise():
    conn, first, _ = _conn()
    first.closed = 2
    conn.rollback()
    assert first.rollbacks == 0


def test_rollback_on_open_connection_rolls_back():
    conn, first, _ = _conn()
    conn.rollback()
    assert first.rollbacks == 1


def test_without_reconnect_a_closed_connection_still_raises():
    first = _FakeRaw()
    conn = Connection(first, "postgres")
    first.closed = 2
    with pytest.raises(RuntimeError):
        conn.execute("SELECT 1")
