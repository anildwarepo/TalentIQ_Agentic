"""Shared pytest fixtures for TalentIQ database tests.

Provides connections to Azure PostgreSQL with Apache AGE, pgvector,
and full-text search capabilities.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg2
import pytest
from dotenv import load_dotenv

# Load env from centralized config
_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _REPO_ROOT / "app_config" / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)

GRAPH_NAME = os.getenv("GRAPH_NAME", "talent_graph")


@pytest.fixture(scope="session")
def db_conn():
    """Session-scoped raw psycopg2 connection to Azure PostgreSQL."""
    conn = psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "postgres"),
        user=os.getenv("PGUSER", ""),
        password=os.getenv("PGPASSWORD", ""),
        sslmode=os.getenv("PGSSLMODE", "require"),
    )
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def graph_name():
    """Return the configured AGE graph name."""
    return GRAPH_NAME


@pytest.fixture()
def cur(db_conn):
    """Per-test cursor — rolled back on teardown for read-only safety."""
    db_conn.autocommit = False
    cursor = db_conn.cursor()
    yield cursor
    db_conn.rollback()
    cursor.close()
    db_conn.autocommit = True


@pytest.fixture()
def age_cur(db_conn, graph_name):
    """Per-test cursor with AGE search_path set for Cypher queries."""
    db_conn.autocommit = False
    cursor = db_conn.cursor()
    cursor.execute("SET search_path = ag_catalog, '$user', public;")
    yield cursor
    db_conn.rollback()
    cursor.close()
    db_conn.autocommit = True


# ---------------------------------------------------------------------------
# Helper: execute a Cypher query via AGE and return parsed rows
# ---------------------------------------------------------------------------
def cypher_query(cursor, graph: str, cypher: str, params: tuple = ()) -> list[dict]:
    """Execute a Cypher query through AGE and return result rows as dicts.

    AGE returns agtype columns.  We parse them via ::text casting
    since psycopg2 does not have a native agtype adapter.
    """
    wrapped = f"SELECT * FROM cypher('{graph}', $$ {cypher} $$) AS (result agtype);"
    cursor.execute(wrapped, params)
    rows = cursor.fetchall()
    return rows


def cypher_query_cols(cursor, graph: str, cypher: str, col_defs: str) -> list[tuple]:
    """Execute a Cypher query with explicit column definitions.

    col_defs example: 'name agtype, email agtype, score agtype'
    """
    wrapped = f"SELECT * FROM cypher('{graph}', $$ {cypher} $$) AS ({col_defs});"
    cursor.execute(wrapped)
    return cursor.fetchall()
