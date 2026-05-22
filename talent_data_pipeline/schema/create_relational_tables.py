"""Create AGE graph labels and relational support tables (vectors, FTS)."""

from __future__ import annotations

import psycopg2
from psycopg2 import sql

from talent_data_pipeline.config import db_config, pipeline_config
from talent_data_pipeline.pg_entra import pg_connect

NODE_LABELS = [
    "Employee", "Location", "Country", "Subregion",
    "Skill", "SkillDomain", "Certification", "Language",
    "ServiceLine", "Offering", "Manager", "University",
    "Client", "Project", "Role",
]

EDGE_LABELS = [
    "LOCATED_IN", "IN_COUNTRY", "SPECIALIZES_IN", "HAS_SKILL",
    "HOLDS_CERT", "SPEAKS", "BELONGS_TO_SL", "WORKS_IN_OFFERING",
    "REPORTS_TO", "STUDIED_AT", "WORKED_FOR", "WORKED_ON",
    "HAS_ROLE",
]


def _ensure_label(cur, conn, graph: str, label: str, is_edge: bool = False) -> None:
    """Create a vertex or edge label if it doesn't exist."""
    func = "ag_catalog.create_elabel" if is_edge else "ag_catalog.create_vlabel"
    # Check existence first
    cur.execute(
        """
        SELECT count(*) FROM ag_catalog.ag_label
        WHERE graph = (SELECT graphid FROM ag_catalog.ag_graph WHERE name = %s)
          AND name = %s;
        """,
        (graph, label),
    )
    if cur.fetchone()[0] > 0:
        return
    try:
        cur.execute(f"SELECT {func}(%s, %s);", (graph, label))
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        # May already exist in a concurrent run — safe to ignore
        pass


def create_graph_labels() -> None:
    """Create all node and edge labels in the AGE graph."""
    conn = pg_connect()
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SET search_path = ag_catalog, '$user', public;")

    graph = pipeline_config.graph_name

    print("Creating node labels...")
    for label in NODE_LABELS:
        _ensure_label(cur, conn, graph, label, is_edge=False)
        print(f"  {label} — OK")

    print("Creating edge labels...")
    for label in EDGE_LABELS:
        _ensure_label(cur, conn, graph, label, is_edge=True)
        print(f"  {label} — OK")

    cur.close()
    conn.close()


def create_relational_tables() -> None:
    """Create relational support tables for vectors and full-text search."""
    conn = pg_connect()
    conn.autocommit = True
    cur = conn.cursor()

    dim = pipeline_config.embedding_dim

    # Employee embeddings table — stores vectors alongside AGE vertex IDs
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS employee_embeddings (
            id              BIGSERIAL PRIMARY KEY,
            employee_ageid  BIGINT NOT NULL UNIQUE,
            workday_id      VARCHAR(20) NOT NULL UNIQUE,
            resume_embedding vector({dim}),
            skills_embedding vector({dim}),
            updated_at       TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    print("  Table 'employee_embeddings' — OK")

    # Full-text search support table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS employee_fts (
            id              BIGSERIAL PRIMARY KEY,
            employee_ageid  BIGINT NOT NULL UNIQUE,
            workday_id      VARCHAR(20) NOT NULL UNIQUE,
            name            TEXT NOT NULL,
            job_title       TEXT,
            resume_summary  TEXT,
            skills_text     TEXT,
            certs_text      TEXT,
            fts_vector      tsvector,
            updated_at      TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    print("  Table 'employee_fts' — OK")

    # Entity search — unified FTS + vector for all reference/dimension entities
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS entity_search (
            id              BIGSERIAL PRIMARY KEY,
            entity_type     VARCHAR(30) NOT NULL,
            name            TEXT NOT NULL,
            code            VARCHAR(30),
            aliases         TEXT,
            search_text     TEXT NOT NULL,
            fts_vector      tsvector,
            embedding       vector({dim}),
            updated_at      TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (entity_type, name)
        );
    """)
    print("  Table 'entity_search' — OK")

    cur.close()
    conn.close()


def run_schema_creation() -> None:
    """Run all schema creation steps."""
    print("=" * 60)
    print("Schema Creation")
    print("=" * 60)
    create_graph_labels()
    print()
    print("Creating relational support tables...")
    create_relational_tables()
    print("Schema creation complete.")


if __name__ == "__main__":
    run_schema_creation()
