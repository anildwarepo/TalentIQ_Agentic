# Project Context

- **Owner:** Anil
- **Project:** TalentIQ — Talent Matching/Searching platform. Find people with skills, generate resumes based on RFPs, show metrics visuals.
- **Stack:** React Vite (frontend), Python (backend), Agent Framework with agentic orchestration, MCP servers, Graph database (Cypher, vector search, full-text search)
- **Features:** Chat interface, FAQs, file upload, resume generation from RFPs, metrics visualization
- **Created:** 2026-05-08

## Learnings

<!-- Append new learnings below. Each entry is something lasting about the project. -->

### 2026-05-09: Data Access Layer Created
- **Path:** `talent_backend/talent_backend/data_access/` — 8 files (init, connection, models, cypher_queries, sql_queries, vector_queries, fts_queries, hybrid_queries)
- **Pattern:** All functions are async, accept `AsyncConnection` from psycopg3, return Pydantic v2 models
- **Connection:** `AsyncConnectionPool` singleton with optional Entra ID token auth via `azure.identity.aio`
- **AGE queries:** Use `_cypher()` helper that wraps `ag_catalog.cypher('{graph_name}', $$ ... $$)`. Search path set on connection acquire via pool configure callback
- **agtype parsing:** `_parse_agtype()` strips ::vertex/::edge suffixes then JSON-parses. AGE returns properties inside a `properties` key in vertex JSON
- **Input sanitization:** `_sanitize_identifier()` escapes `\` and `'` for values injected into Cypher `$$` blocks. All SQL queries use `%s` parameterised placeholders
- **Hybrid search:** `multi_criteria_search()` fans out to graph + vector + FTS, normalises scores per-engine, then weighted-merges with configurable weights dict
- **Key tables:** `employee_embeddings` (vector(1536) resume + skills), `employee_fts` (tsvector + trigram indexes)
- **Graph name:** loaded from `GRAPH_NAME` env var, default `talent_graph`, available as `connection.GRAPH_NAME`

### 2026-05-09 — Cross-agent: Kane's API & Agent layer
- Kane built the FastAPI backend that consumes this data access layer
- Chat endpoint: `/api/v1/chat` → `TalentAgent` (OpenAI function calling, 9 tools mapped to data_access functions)
- Search endpoints: `/api/v1/search/candidates`, `/search/employee/{id}`, `/search/semantic`, `/search/text`, `/search/team/{id}`
- Health: `/health/live` + `/health/ready` (checks DB pool)
- Auth: Entra ID JWT validation; bypass with `TALENTIQ_AUTH_DISABLED=true` for local dev
- Lazy imports: Kane's tools.py and search.py use lazy `from talent_backend.data_access import ...` — no startup crash
- Agent tool dispatch in `tools.py` calls data_access functions by name

### 2026-05-09: MCP Server Created
- **Path:** `talent_backend/talent_backend/mcp_server/` — 4 files (__init__, pg_age_helper, server, run_server)
- **Architecture:** Standalone FastMCP process on port 3002 (env: `MCP_PORT`), separate from FastAPI backend
- **Transport:** `streamable-http` — agent connects via `MCPStreamableHTTPTool`
- **Tools exposed:** `fetch_ontology`, `save_ontology`, `query_using_sql_cypher`, `discover_nodes`, `search_graph`, `resolve_entity_ids`, `build_query_context`, `analyze_graph_statistics`
- **Pre-loaded ontology:** Full talent_graph schema (14 node labels, 12 edge labels) hardcoded in `_TALENT_GRAPH_ONTOLOGY` — eliminates discovery round-trip
- **PGAgeHelper:** Async psycopg3 `AsyncConnectionPool`, sets AGE search_path on every query, parses agtype results
- **Name verification:** FTS results are name-verified via Cypher follow-up to filter false positives
- **FTS dependency:** Uses `public.search_graph_nodes()` SQL function — must exist in DB
- **Existing data_access layer preserved:** Still used by `/api/v1/search/*` structured endpoints — MCP server is additive for agent workflow
- **Windows compat:** `WindowsSelectorEventLoopPolicy` + `PSYCOPG_IMPL=python` fallback for Windows dev
- **CORS:** Permissive CORS middleware for local dev (origins=*, expose Mcp-Session-Id header)
- **SQL sanitization:** `_sanitize_sql_string()` helper escapes single quotes for f-string SQL interpolation

### 2026-05-09 — Cross-agent: Kane's Agent Framework rewrite
- Kane rewrote `talent_agent.py` to use Agent Framework SDK (`agent_framework>=1.3.0`) with `MCPStreamableHTTPTool`
- Agent now connects to this MCP server at `MCP_ENDPOINT` (default `http://localhost:3002/mcp`)
- All 9 manual tool definitions removed from agent side — MCP server is the sole tool provider for agent queries
- `tools.py` retained only `generate_embedding()` for search endpoints
- Chat history added via Cosmos DB — new endpoints: `GET/DELETE /sessions`, `POST /chat` returns `message_id`
- Existing data_access layer still powers structured search endpoints (`/api/v1/search/*`)
