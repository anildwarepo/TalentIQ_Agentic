"""Async PostgreSQL + Apache AGE helper.

Wraps psycopg_pool.AsyncConnectionPool with AGE-specific search_path
management and agtype result parsing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys

# ── Windows compatibility ────────────────────────────────────
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        import psycopg.pq._pq_ctypes  # noqa: F401
        os.environ.setdefault("PSYCOPG_IMPL", "python")
    except (ImportError, OSError):
        pass

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from talent_backend.config import pg_conninfo
from talent_backend.pg_entra import EntraTokenAsyncConnectionPool

logger = logging.getLogger("talent_backend.pg_age")

# Regex to strip AGE agtype wrappers: e.g. 1234::numeric, "text"::agtype
_AGTYPE_CAST_RE = re.compile(r"^(.+)::\w+$")


def _sanitize_sql_string(value: str) -> str:
    """Escape single quotes for safe SQL interpolation."""
    return value.replace("'", "''")


def _parse_agtype_value(val: str) -> object:
    """Parse a single agtype-formatted value into a Python object.

    AGE returns values like:
      - ``"some text"``  → ``some text``
      - ``123``          → ``123`` (int)
      - ``12.5``         → ``12.5`` (float)
      - ``true``/``false`` → bool
      - ``["Label"]``    → ``Label``
      - ``{"key": "val"}`` → dict
    """
    if not isinstance(val, str):
        return val

    val = val.strip()

    # Strip ::type cast suffix (e.g. 1234::numeric)
    m = _AGTYPE_CAST_RE.match(val)
    if m:
        val = m.group(1).strip()

    # JSON array label wrapper: ["Label"] → Label
    if val.startswith('["') and val.endswith('"]'):
        return val[2:-2]

    # Quoted string
    if val.startswith('"') and val.endswith('"') and len(val) > 1:
        return val[1:-1]

    # Boolean
    if val == "true":
        return True
    if val == "false":
        return False

    # Null
    if val == "null":
        return None

    # Try numeric
    try:
        if "." in val:
            return float(val)
        return int(val)
    except ValueError:
        pass

    # Try JSON object/array
    if val.startswith("{") or val.startswith("["):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            pass

    return val


class PGAgeHelper:
    """Async wrapper around PostgreSQL with Apache AGE extension."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool
        self._opened = False

    @classmethod
    async def create(
        cls,
        conninfo: str | None = None,
        min_size: int = 2,
        max_size: int = 10,
    ) -> "PGAgeHelper":
        """Create the helper and open the connection pool."""
        conninfo = conninfo or pg_conninfo()
        logger.info("Opening async connection pool (min=%d, max=%d)", min_size, max_size)
        pool = EntraTokenAsyncConnectionPool(
            conninfo=conninfo,
            min_size=min_size,
            max_size=max_size,
            kwargs={"row_factory": dict_row},
        )
        await pool.open()
        logger.info("Connection pool opened successfully")
        helper = cls(pool)
        helper._opened = True
        return helper

    @classmethod
    def create_deferred(
        cls,
        conninfo: str | None = None,
        min_size: int = 2,
        max_size: int = 10,
    ) -> "PGAgeHelper":
        """Create the helper WITHOUT opening the pool.

        The pool will be opened lazily on the first query,
        inside the caller's event loop.
        """
        conninfo = conninfo or pg_conninfo()
        logger.info("Creating deferred connection pool (min=%d, max=%d)", min_size, max_size)
        pool = EntraTokenAsyncConnectionPool(
            conninfo=conninfo,
            min_size=min_size,
            max_size=max_size,
            kwargs={"row_factory": dict_row},
            open=False,
        )
        return cls(pool)

    async def _ensure_open(self) -> None:
        """Open the pool if it hasn't been opened yet."""
        if not self._opened:
            logger.info("Opening deferred connection pool...")
            await self._pool.open()
            self._opened = True
            logger.info("Connection pool opened successfully")

    async def query_using_sql_cypher(
        self,
        sql: str,
        graph_name: str | None = None,
    ) -> list[dict]:
        """Execute a SQL (or SQL-wrapped Cypher) query and return rows as dicts.

        Sets the AGE search_path before every query.  The graph name
        is passed directly to ``ag_catalog.cypher()`` in the SQL.
        """
        await self._ensure_open()
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                # AGE requires ag_catalog on the search_path
                await cur.execute(
                    'SET search_path = ag_catalog, "$user", public;'
                )

                await cur.execute(sql)

                # DDL / DML without result set
                if cur.description is None:
                    return []

                raw_rows = await cur.fetchall()

        # Parse agtype values in each row
        parsed: list[dict] = []
        for row in raw_rows:
            parsed_row: dict = {}
            for key, value in row.items():
                parsed_row[key] = _parse_agtype_value(value) if isinstance(value, str) else value
            parsed.append(parsed_row)

        return parsed

    async def close(self) -> None:
        """Close the connection pool."""
        logger.info("Closing connection pool")
        await self._pool.close()
