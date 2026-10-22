from contextlib import contextmanager
from typing import Iterator
from uuid import UUID

from pgvector.psycopg import register_vector
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.core.config import get_settings

_pool: ConnectionPool | None = None


def init_pool() -> ConnectionPool:
    """Open the shared pool. Called once from the app lifespan."""
    global _pool
    if _pool is None:
        settings = get_settings()
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is not set")
        _pool = ConnectionPool(
            settings.database_url,
            min_size=1,
            max_size=5,  # free-tier Neon computes have few connection slots
            kwargs={
                "row_factory": dict_row,
                # Neon's pooled endpoint runs PgBouncer in transaction mode,
                # which does not support server-side prepared statements.
                "prepare_threshold": None,
            },
            configure=register_vector,
            check=ConnectionPool.check_connection,
            open=False,
        )
        _pool.open(wait=True, timeout=30)
    return _pool


def get_pool() -> ConnectionPool:
    if _pool is None:
        raise RuntimeError("Database pool is not initialised")
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def user_tx(user_id: UUID | str) -> Iterator[Connection]:
    """Run one transaction as the given user.

    Sets app.user_id for the transaction only (set_config(..., true)), so the
    row-level security policies in schema.sql scope every query to that user's
    workspaces. Commits on a clean exit and rolls back on an exception.
    """
    uid = str(UUID(str(user_id)))  # reject anything that is not a UUID
    with get_pool().connection() as conn:
        conn.execute("select set_config('app.user_id', %s, true)", (uid,))
        yield conn


def ping() -> bool:
    """Cheap liveness check for /health. Also wakes a suspended Neon compute."""
    with get_pool().connection() as conn:
        return conn.execute("select 1 as ok").fetchone()["ok"] == 1
