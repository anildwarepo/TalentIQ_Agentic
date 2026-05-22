"""Connectivity test — verify PostgreSQL, AGE, pgvector, and DiskANN before any data ops."""

from __future__ import annotations

import sys

import psycopg2
from psycopg2 import sql

from talent_data_pipeline.config import db_config, pipeline_config
from talent_data_pipeline.pg_entra import pg_connect


def _connect():
    """Return a psycopg2 connection authenticated via Entra ID."""
    return pg_connect()


def _test_basic_connection(cur) -> bool:
    """Test that PostgreSQL is reachable and return version."""
    cur.execute("SELECT version();")
    version = cur.fetchone()[0]
    print(f"  PostgreSQL connected: {version.split(',')[0]}")
    return True


def _ensure_extension(cur, conn, ext_name: str) -> str | None:
    """Create extension if not exists, return installed version or None."""
    try:
        cur.execute(
            sql.SQL("CREATE EXTENSION IF NOT EXISTS {} CASCADE;").format(sql.Identifier(ext_name))
        )
        conn.commit()
    except psycopg2.Error as exc:
        conn.rollback()
        print(f"  WARNING: Could not create extension '{ext_name}': {exc.pgrep if hasattr(exc, 'pgrep') else exc}")
        return None

    cur.execute(
        "SELECT extversion FROM pg_extension WHERE extname = %s;",
        (ext_name,),
    )
    row = cur.fetchone()
    if row:
        print(f"  Extension '{ext_name}' v{row[0]} — OK")
        return row[0]
    print(f"  Extension '{ext_name}' — NOT FOUND after CREATE attempt")
    return None


def _ensure_graph(cur, conn, graph_name: str) -> bool:
    """Create the AGE graph if it doesn't exist."""
    # Make sure the ag_catalog schema is on the search_path
    cur.execute("SET search_path = ag_catalog, '$user', public;")

    cur.execute(
        "SELECT count(*) FROM ag_catalog.ag_graph WHERE name = %s;",
        (graph_name,),
    )
    exists = cur.fetchone()[0] > 0
    if exists:
        print(f"  Graph '{graph_name}' already exists — OK")
        return True

    try:
        cur.execute("SELECT ag_catalog.create_graph(%s);", (graph_name,))
        conn.commit()
        print(f"  Graph '{graph_name}' created — OK")
        return True
    except psycopg2.Error as exc:
        conn.rollback()
        print(f"  ERROR creating graph '{graph_name}': {exc}")
        return False


def run_connectivity_test() -> bool:
    """Run all connectivity checks. Returns True if all critical checks pass."""
    print("=" * 60)
    print("TalentIQ Connectivity Test")
    print("=" * 60)
    print(f"  Target: {db_config.host}:{db_config.port}/{db_config.database}")
    print()

    try:
        conn = _connect()
    except psycopg2.OperationalError as exc:
        print(f"  FATAL: Cannot connect to PostgreSQL — {exc}")
        return False

    conn.autocommit = False
    cur = conn.cursor()
    all_ok = True

    # 1. Basic connection
    print("[1/5] PostgreSQL connection")
    if not _test_basic_connection(cur):
        return False

    # 2. Apache AGE
    print("[2/5] Apache AGE extension")
    age_ver = _ensure_extension(cur, conn, "age")
    if not age_ver:
        all_ok = False

    # 3. pgvector
    print("[3/5] pgvector extension")
    vec_ver = _ensure_extension(cur, conn, "vector")
    if not vec_ver:
        all_ok = False

    # 4. DiskANN (vectorscale) — optional, not fatal
    print("[4/5] DiskANN / vectorscale extension (optional)")
    diskann_ver = _ensure_extension(cur, conn, "vectorscale")
    if not diskann_ver:
        # Try pg_diskann as alternative name
        diskann_ver = _ensure_extension(cur, conn, "pg_diskann")
    if not diskann_ver:
        print("  INFO: DiskANN not available — will use ivfflat or hnsw indexes instead")

    # 5. Create graph
    print(f"[5/5] AGE graph '{pipeline_config.graph_name}'")
    if age_ver:
        if not _ensure_graph(cur, conn, pipeline_config.graph_name):
            all_ok = False
    else:
        print("  SKIPPED — AGE extension not available")
        all_ok = False

    cur.close()
    conn.close()

    print()
    print("=" * 60)
    if all_ok:
        print("ALL CHECKS PASSED — ready for data operations")
    else:
        print("SOME CHECKS FAILED — review output above")
    print("=" * 60)
    return all_ok


def main() -> None:
    success = run_connectivity_test()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
