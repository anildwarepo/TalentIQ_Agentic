"""Create all database indexes: AGE graph, DiskANN/HNSW vector, GIN FTS, B-tree, pg_trgm."""

from __future__ import annotations

import psycopg2

from talent_data_pipeline.config import db_config, pipeline_config


def _exec(cur, stmt: str, label: str) -> None:
    """Execute a statement, ignoring 'already exists' errors."""
    try:
        cur.execute(stmt)
        print(f"  {label} — OK")
    except psycopg2.Error as exc:
        if "already exists" in str(exc):
            print(f"  {label} — already exists")
        else:
            print(f"  {label} — ERROR: {exc}")


def create_vector_indexes(cur) -> None:
    """DiskANN (or HNSW fallback) indexes on embedding columns."""
    # Check if vectorscale/diskann is available
    cur.execute("SELECT count(*) FROM pg_extension WHERE extname IN ('vectorscale', 'pg_diskann');")
    has_diskann = cur.fetchone()[0] > 0

    if has_diskann:
        _exec(cur,
              "CREATE INDEX IF NOT EXISTS idx_emb_resume_diskann "
              "ON employee_embeddings USING diskann (resume_embedding vector_cosine_ops);",
              "DiskANN index on resume_embedding")
        _exec(cur,
              "CREATE INDEX IF NOT EXISTS idx_emb_skills_diskann "
              "ON employee_embeddings USING diskann (skills_embedding vector_cosine_ops);",
              "DiskANN index on skills_embedding")
    else:
        # Fallback to HNSW
        _exec(cur,
              "CREATE INDEX IF NOT EXISTS idx_emb_resume_hnsw "
              "ON employee_embeddings USING hnsw (resume_embedding vector_cosine_ops) "
              "WITH (m = 16, ef_construction = 200);",
              "HNSW index on resume_embedding")
        _exec(cur,
              "CREATE INDEX IF NOT EXISTS idx_emb_skills_hnsw "
              "ON employee_embeddings USING hnsw (skills_embedding vector_cosine_ops) "
              "WITH (m = 16, ef_construction = 200);",
              "HNSW index on skills_embedding")


def create_fts_indexes(cur) -> None:
    """GIN indexes for full-text search with tsvector."""
    _exec(cur,
          "CREATE INDEX IF NOT EXISTS idx_fts_vector "
          "ON employee_fts USING gin (fts_vector);",
          "GIN index on fts_vector")


def create_trigram_indexes(cur) -> None:
    """pg_trgm GIN indexes for fuzzy/trigram search.

    pg_trgm is not allow-listed on Azure Database for PostgreSQL,
    so we check availability first and skip gracefully.
    """
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    except psycopg2.Error:
        print("  ⚠️  pg_trgm extension not available — skipping trigram indexes")
        return

    _exec(cur,
          "CREATE INDEX IF NOT EXISTS idx_fts_name_trgm "
          "ON employee_fts USING gin (name gin_trgm_ops);",
          "Trigram index on name")
    _exec(cur,
          "CREATE INDEX IF NOT EXISTS idx_fts_job_title_trgm "
          "ON employee_fts USING gin (job_title gin_trgm_ops);",
          "Trigram index on job_title")
    _exec(cur,
          "CREATE INDEX IF NOT EXISTS idx_fts_skills_trgm "
          "ON employee_fts USING gin (skills_text gin_trgm_ops);",
          "Trigram index on skills_text")


def create_btree_indexes(cur) -> None:
    """B-tree indexes on frequently queried relational columns."""
    _exec(cur,
          "CREATE INDEX IF NOT EXISTS idx_emb_workday_id "
          "ON employee_embeddings (workday_id);",
          "B-tree on employee_embeddings.workday_id")
    _exec(cur,
          "CREATE INDEX IF NOT EXISTS idx_fts_workday_id "
          "ON employee_fts (workday_id);",
          "B-tree on employee_fts.workday_id")


def create_age_graph_indexes(cur) -> None:
    """Indexes on AGE graph internal tables for query performance.

    AGE stores each label as a table under the graph schema.
    We index key properties used in Cypher WHERE clauses.
    """
    graph = pipeline_config.graph_name

    # Employee indexes — most-queried node
    # AGE stores properties as agtype, not jsonb. Use agtype_access_operator
    # to extract individual property values for indexing.
    property_indexes = [
        ("Employee", "workday_id", "idx_emp_workday_id"),
        ("Employee", "email", "idx_emp_email"),
        ("Employee", "is_bench", "idx_emp_is_bench"),
        ("Employee", "employment_status", "idx_emp_status"),
        ("Employee", "skill_level", "idx_emp_skill_level"),
        ("Employee", "job_level", "idx_emp_job_level"),
        ("Employee", "delivery_model", "idx_emp_delivery_model"),
        # Reference node lookups by name
        ("Location", "city", "idx_loc_city"),
        ("Skill", "name", "idx_skill_name"),
        ("SkillDomain", "name", "idx_skilldomain_name"),
        ("Certification", "name", "idx_cert_name"),
        ("Language", "name", "idx_lang_name"),
        ("ServiceLine", "name", "idx_sl_name"),
        ("Offering", "name", "idx_offering_name"),
        ("Manager", "employee_id", "idx_mgr_empid"),
        ("University", "name", "idx_uni_name"),
        ("Client", "name", "idx_client_name"),
        ("Project", "name", "idx_project_name"),
        ("Country", "code", "idx_country_code"),
    ]

    cur.execute("SET search_path = ag_catalog, public;")
    for label, prop, idx_name in property_indexes:
        _exec(cur,
              f'CREATE INDEX IF NOT EXISTS {idx_name} ON {graph}."{label}" '
              f"((ag_catalog.agtype_access_operator(properties, '\"{prop}\"'::agtype)));",
              f"AGE index {idx_name}")


def run_index_creation() -> None:
    """Create all indexes."""
    print("=" * 60)
    print("Index Creation")
    print("=" * 60)
    conn = psycopg2.connect(**db_config.connection_dict)
    conn.autocommit = True
    cur = conn.cursor()

    print("Vector indexes...")
    create_vector_indexes(cur)

    print("Full-text search indexes...")
    create_fts_indexes(cur)

    print("Trigram indexes...")
    create_trigram_indexes(cur)

    print("B-tree indexes...")
    create_btree_indexes(cur)

    print("AGE graph property indexes...")
    create_age_graph_indexes(cur)

    cur.close()
    conn.close()
    print("Index creation complete.")


if __name__ == "__main__":
    run_index_creation()
