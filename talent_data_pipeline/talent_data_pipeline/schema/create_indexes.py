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
    """pg_trgm GIN indexes for fuzzy/trigram search."""
    # Ensure pg_trgm extension
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    except psycopg2.Error:
        pass

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


def create_entity_search_indexes(cur) -> None:
    """GIN + B-tree indexes for entity_search table."""
    _exec(cur,
          "CREATE INDEX IF NOT EXISTS idx_entity_search_fts "
          "ON entity_search USING gin (fts_vector);",
          "GIN index on entity_search.fts_vector")
    _exec(cur,
          "CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_search_type_name "
          "ON entity_search (entity_type, name);",
          "Unique index on entity_search(entity_type, name)")
    _exec(cur,
          "CREATE INDEX IF NOT EXISTS idx_entity_search_type_code "
          "ON entity_search (entity_type, code);",
          "B-tree on entity_search(entity_type, code)")


def create_age_graph_indexes(cur) -> None:
    """Indexes on AGE graph internal tables for query performance.

    AGE stores each label as a table under the graph schema with a
    `properties` column of type ``ag_catalog.agtype``. The bare ``->>``
    operator does not exist for agtype in AGE 1.6.0, so we index against
    ``((properties::text)::jsonb)->>'<key>'`` — the double cast that AGE
    accepts for SQL-side property extraction.
    """
    graph = pipeline_config.graph_name

    # (table, json-key, index-name). Index expression built below as
    # ((properties::text)::jsonb)->>'<key>'.
    property_indexes = [
        # Employee — most-queried node
        (f"{graph}.\"Employee\"", "workday_id", "idx_emp_workday_id"),
        (f"{graph}.\"Employee\"", "email", "idx_emp_email"),
        (f"{graph}.\"Employee\"", "is_bench", "idx_emp_is_bench"),
        (f"{graph}.\"Employee\"", "employment_status", "idx_emp_status"),
        (f"{graph}.\"Employee\"", "skill_level", "idx_emp_skill_level"),
        (f"{graph}.\"Employee\"", "job_level", "idx_emp_job_level"),
        (f"{graph}.\"Employee\"", "delivery_model", "idx_emp_delivery_model"),
        # Reference node lookups by name/code
        (f"{graph}.\"Location\"", "city", "idx_loc_city"),
        (f"{graph}.\"Skill\"", "name", "idx_skill_name"),
        (f"{graph}.\"Skill\"", "code", "idx_skill_code"),
        (f"{graph}.\"SkillDomain\"", "name", "idx_skilldomain_name"),
        (f"{graph}.\"SkillDomain\"", "code", "idx_skilldomain_code"),
        (f"{graph}.\"Certification\"", "name", "idx_cert_name"),
        (f"{graph}.\"Certification\"", "code", "idx_cert_code"),
        (f"{graph}.\"Language\"", "name", "idx_lang_name"),
        (f"{graph}.\"Language\"", "code", "idx_lang_code"),
        (f"{graph}.\"ServiceLine\"", "name", "idx_sl_name"),
        (f"{graph}.\"ServiceLine\"", "code", "idx_sl_code"),
        (f"{graph}.\"Offering\"", "name", "idx_offering_name"),
        (f"{graph}.\"Offering\"", "code", "idx_offering_code"),
        (f"{graph}.\"Manager\"", "employee_id", "idx_mgr_empid"),
        (f"{graph}.\"University\"", "name", "idx_uni_name"),
        (f"{graph}.\"University\"", "code", "idx_uni_code"),
        (f"{graph}.\"Client\"", "name", "idx_client_name"),
        (f"{graph}.\"Client\"", "code", "idx_client_code"),
        (f"{graph}.\"Project\"", "name", "idx_project_name"),
        (f"{graph}.\"Project\"", "code", "idx_project_code"),
        (f"{graph}.\"Country\"", "code", "idx_country_code"),
        (f"{graph}.\"Role\"", "name", "idx_role_name"),
        (f"{graph}.\"Role\"", "code", "idx_role_code"),
    ]

    for table, key, idx_name in property_indexes:
        expr = f"((properties::text)::jsonb)->>'{key}'"
        _exec(cur,
              f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} (({expr}));",
              f"AGE index {idx_name}")


def run_age_label_indexes() -> None:
    """Create AGE label property indexes (idempotent).

    Designed to run BEFORE bulk loading so that Cypher MERGE uses an index
    lookup (O(log N)) instead of a sequential scan of a growing label table
    (which makes MERGE-driven loads O(N²) and dominates wall time at scale).
    Index creation on empty tables is instant, so calling this right after
    schema/label setup is cheap.
    """
    print("=" * 60)
    print("AGE Label Indexes (pre-load)")
    print("=" * 60)
    conn = psycopg2.connect(**db_config.connection_dict)
    conn.autocommit = True
    cur = conn.cursor()
    try:
        create_age_graph_indexes(cur)
    finally:
        cur.close()
        conn.close()
    print("AGE label indexes ready.")


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

    print("Entity search indexes...")
    create_entity_search_indexes(cur)

    print("AGE graph property indexes...")
    create_age_graph_indexes(cur)

    cur.close()
    conn.close()
    print("Index creation complete.")


if __name__ == "__main__":
    run_index_creation()
