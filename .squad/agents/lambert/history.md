# Project Context

- **Owner:** Anil
- **Project:** TalentIQ — Talent Matching/Searching platform. Find people with skills, generate resumes based on RFPs, show metrics visuals.
- **Stack:** React Vite (frontend), Python (backend), Agent Framework with agentic orchestration, MCP servers, Graph database (Cypher, vector search, full-text search)
- **Features:** Chat interface, FAQs, file upload, resume generation from RFPs, metrics visualization
- **Created:** 2026-05-08

## Learnings

<!-- Append new learnings below. Each entry is something lasting about the project. -->

### 2026-05-09 — Database Query Test Suite Created

- **Architecture decision:** Tests run against the live Azure PostgreSQL database (not mocks). This is intentional — the ontology is complex enough that mock data would miss real edge cases. All tests are read-only (no writes, rollback on teardown).
- **AGE Cypher pattern:** Queries go through `cypher('{graph_name}', $$ ... $$) AS (col agtype)`. The `agtype` return type needs `::text` casting or string parsing — psycopg2 has no native adapter.
- **Key file paths:**
  - Tests: `tests/test_database_queries.py` (88 test cases), `tests/conftest.py` (fixtures)
  - Coverage matrix: `docs/test-coverage-matrix.md`
  - Schema: `talent_data_pipeline/schema/create_relational_tables.py`
  - Indexes: `talent_data_pipeline/schema/create_indexes.py`
  - Config: `talent_data_pipeline/talent_data_pipeline/config.py`
  - Ontology: `talentiq_requirements/talent_ontology/DXC_Talent_Ontology.md`
- **Graph name:** Configured via `GRAPH_NAME` env var, default `talent_graph`.
- **Embedding dimension:** 1536 (text-embedding-ada-002 via Azure OpenAI).
- **Vector indexes:** DiskANN preferred, HNSW fallback. Both use cosine distance (`<=>`).
- **FTS indexes:** GIN on `fts_vector`, pg_trgm GIN on `name`, `job_title`, `skills_text`.
- **Ontology constants validated:** 14 node labels, 12 edge types, 13 SkillDomains, CEFR levels, cert statuses, seniority tiers.
- **User preferences (Anil):** Wants tests grouped by query type (Graph/FTS/Vector/Combined/Dashboard/Filter), each test docstring referencing the user story ID.
