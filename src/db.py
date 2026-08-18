"""Connection handling for CockroachDB.

Uses psycopg 3. CockroachDB can return transient `40001` (serialization
failure) errors under contention; the recommended pattern is client-side
retry of the whole transaction body, which `run_in_transaction` implements.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Callable, Iterator, TypeVar

import psycopg
from psycopg import Connection
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .config import settings

logger = logging.getLogger("sentinel.db")

T = TypeVar("T")

_RETRYABLE_SQLSTATE = "40001"


def _is_retryable(exc: BaseException) -> bool:
    return (
        isinstance(exc, psycopg.errors.SerializationFailure)
        or getattr(exc, "sqlstate", None) == _RETRYABLE_SQLSTATE
    )


def get_connection() -> Connection:
    """Open a new connection to CockroachDB.

    Lambda note: for a real deployment, prefer a connection pool (e.g.
    psycopg_pool) initialized outside the handler so it's reused across warm
    invocations. Kept simple here for demo clarity.
    """
    return psycopg.connect(settings.database_url, autocommit=False)


@contextmanager
def transaction(conn: Connection | None = None) -> Iterator[Connection]:
    """Commit on success, roll back on any exception.

    Pass an existing connection to participate in a caller-managed
    transaction (e.g. from `run_in_transaction`); otherwise a fresh
    connection is opened and closed automatically.
    """
    owns_connection = conn is None
    active = conn or get_connection()
    try:
        yield active
        active.commit()
    except Exception:
        active.rollback()
        raise
    finally:
        if owns_connection:
            active.close()


@retry(
    reraise=True,
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=0.1, max=2),
    retry=retry_if_exception(_is_retryable),
)
def run_in_transaction(fn: Callable[[Connection], T]) -> T:
    """Run `fn(conn)` inside a transaction, retrying the *entire* callable on
    CockroachDB serialization failures (the standard CockroachDB retry
    pattern, since the whole transaction must be replayed, not just the
    failing statement).
    """
    conn = get_connection()
    try:
        with transaction(conn):
            return fn(conn)
    finally:
        conn.close()
