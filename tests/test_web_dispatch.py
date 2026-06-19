"""Tests for web request dispatch — liveness/readiness separation and
connection-poisoning recovery (pvewatch#32).

Root cause of the periodic restarts: the web server shared one DB connection
with the poller and queried it from the liveness probe. A single failed query
left the (postgres) connection in an aborted-transaction state, so every later
``SELECT 1`` for ``/healthz`` returned 503 until the kubelet restarted the pod.

These tests pin the fix:
  * liveness ``/healthz`` never touches the DB,
  * ``/readyz`` does the DB check and rolls back on error so the connection
    is reusable for the next request.
"""

import tempfile
import threading

import pytest

from pvewatch.database import connect, migrate
from pvewatch.web import _dispatch


class _BrokenConn:
    """Connection whose queries always raise (simulates an aborted txn)."""

    def __init__(self):
        self.execute_calls = 0
        self.rollbacks = 0

    def execute(self, sql, params=()):
        self.execute_calls += 1
        raise RuntimeError("current transaction is aborted")

    def rollback(self):
        self.rollbacks += 1


class _FlakyConn:
    """Raises on the first query, then behaves normally (rollback recovers it)."""

    def __init__(self):
        self.poisoned = True
        self.rollbacks = 0

    def execute(self, sql, params=()):
        if self.poisoned:
            raise RuntimeError("current transaction is aborted")

        class _Cur:
            def fetchone(self_inner):
                return (1,)

            def fetchall(self_inner):
                return []

        return _Cur()

    def rollback(self):
        self.rollbacks += 1
        self.poisoned = False


@pytest.fixture
def conn():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db_path = f.name
    c = connect(db_path)
    migrate(c)
    yield c
    c.close()


@pytest.fixture
def lock():
    return threading.Lock()


def test_healthz_never_queries_db(lock):
    """Liveness must succeed even when the DB connection is unusable."""
    broken = _BrokenConn()
    status, _ctype, _body = _dispatch("/healthz", 7, broken, "pve", lock)
    assert status == 200
    assert broken.execute_calls == 0  # liveness did not touch the DB


def test_readyz_ok_with_working_db(conn, lock):
    status, _ctype, body = _dispatch("/readyz", 7, conn, "pve", lock)
    assert status == 200
    assert b"ready" in body


def test_readyz_503_on_db_error_and_rolls_back(lock):
    broken = _BrokenConn()
    status, _ctype, _body = _dispatch("/readyz", 7, broken, "pve", lock)
    assert status == 503
    assert broken.rollbacks == 1  # cleared the aborted-transaction state


def test_db_error_does_not_poison_connection(lock):
    """The core regression: one failed query must not wedge every later request."""
    flaky = _FlakyConn()
    first, _c1, _b1 = _dispatch("/readyz", 7, flaky, "pve", lock)
    assert first == 503
    second, _c2, _b2 = _dispatch("/readyz", 7, flaky, "pve", lock)
    assert second == 200  # recovered after rollback, no restart needed


def test_data_endpoint_error_returns_500_and_rolls_back(lock):
    broken = _BrokenConn()
    status, _ctype, _body = _dispatch("/metrics", 7, broken, "pve", lock)
    assert status == 500
    assert broken.rollbacks == 1


def test_unknown_path_404(conn, lock):
    status, _ctype, _body = _dispatch("/nope", 7, conn, "pve", lock)
    assert status == 404
