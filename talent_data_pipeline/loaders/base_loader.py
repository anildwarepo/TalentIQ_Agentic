"""Base loader with connection pool management, batching, and progress reporting."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Generator

import psycopg2
from psycopg2 import pool

from talent_data_pipeline.config import db_config, pipeline_config


class BaseLoader:
    """Manages a connection pool and provides batch helper methods."""

    def __init__(self):
        self._pool: pool.ThreadedConnectionPool | None = None

    def _get_pool(self) -> pool.ThreadedConnectionPool:
        if self._pool is None:
            self._pool = pool.ThreadedConnectionPool(
                minconn=db_config.pool_min,
                maxconn=db_config.pool_max,
                **db_config.connection_dict,
            )
        return self._pool

    @contextmanager
    def get_conn(self) -> Generator[Any, None, None]:
        """Borrow a connection from the pool."""
        p = self._get_pool()
        conn = p.getconn()
        try:
            yield conn
        finally:
            p.putconn(conn)

    def close(self) -> None:
        if self._pool:
            self._pool.closeall()
            self._pool = None

    @staticmethod
    def execute_with_retry(
        conn, cur, stmt: str, params: tuple | None = None, max_retries: int = 3
    ) -> Any:
        """Execute a statement with retry on transient errors."""
        for attempt in range(max_retries):
            try:
                cur.execute(stmt, params)
                return cur
            except psycopg2.OperationalError:
                if attempt < max_retries - 1:
                    conn.rollback()
                    time.sleep(2 ** attempt)
                else:
                    raise
            except psycopg2.InterfaceError:
                raise
        return None

    @staticmethod
    def batched(items: list[Any], size: int | None = None):
        """Yield batches of items."""
        size = size or pipeline_config.batch_size
        for i in range(0, len(items), size):
            yield items[i : i + size]
