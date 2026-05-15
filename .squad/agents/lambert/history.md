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

### 2026-05-12T02:00:00Z: Cross-agent — Deployment readiness assessment needed
- **Bishop:** azd-up.md runbook complete (~420 lines, 8 sections). Full deployment stack ready: VNet + data services + Container Apps + MCP + Dockerfiles.
- **Lambert pending:** Test strategy for deployment-readiness verification. Consider:
  - Connectivity test: verify Entra token flow against Azure PG
  - Container startup: health probe on /health endpoint (backend + MCP)
  - RBAC verification: list role assignments for each UAMI
  - Log streaming: check Container App logs via `az containerapp logs show`
  - End-to-end flow: ping backend → MCP → graph query → response
- **Pattern:** Deployment tests should be separate from data layer tests. Likely belongs in `tests/test_deployment_readiness.py` covering infrastructure assumptions (network connectivity, RBAC, credential flow).

### 2026-05-15 — Chat History Thread Management Test Suite

- **Test file:** `tests/test_chat_history.py` — 16 test cases covering ChatHistoryStore methods and API endpoints.
- **Architecture decision:** Tests run against the in-memory fallback path only (no Cosmos DB). The `_fallback` module-level dict is cleared between tests via autouse fixture.
- **Key patterns:**
  - `ChatHistoryStore` instantiated with `COSMOS_CHAT_ENDPOINT` patched to empty string → forces in-memory mode.
  - API tests use FastAPI `dependency_overrides` to mock `get_current_user` → returns a fixed test user dict with `oid`.
  - `api_mod._history` is replaced with a fresh in-memory store per API test to avoid cross-test contamination.
  - Kane's new methods expected: `add_message(session_id, role, text, user_id=)`, `list_threads(user_id)`, `get_thread_messages(session_id)`, `soft_delete_thread(session_id)`, `rename_thread(session_id, title)`.
  - Thread ownership enforced by returning 404 (not 403) to prevent enumeration — per spec §3.
  - Auto-title: first user message truncated to 50 chars.
- **Backward compat tests:** `get_history()` and `delete_session()` still work after thread management additions.
- **API test coverage:** GET/DELETE/PATCH on `/api/threads`, 404 for missing threads, ownership isolation between users.
