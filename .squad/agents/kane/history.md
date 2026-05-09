# Project Context

- **Owner:** Anil
- **Project:** TalentIQ — Talent Matching/Searching platform. Find people with skills, generate resumes based on RFPs, show metrics visuals.
- **Stack:** React Vite (frontend), Python (backend), Agent Framework with agentic orchestration, MCP servers, Graph database (Cypher, vector search, full-text search)
- **Features:** Chat interface, FAQs, file upload, resume generation from RFPs, metrics visualization
- **Created:** 2026-05-08

## Cross-Agent Updates

### 2026-05-08T20:10 — Backend skeleton ready (from Brett)
- `talent_backend/talent_backend/` created with `__init__.py` and `config.py`
- `config.py` loads credentials from `app_config/.env` (centralized, no local `.env`)
- Root `pyproject.toml` is a uv workspace — run `uv sync` from repo root
- Data pipeline tables available: `employee_fts`, `employee_embeddings` (relational interface for search)

## Learnings

<!-- Append new learnings below. Each entry is something lasting about the project. -->

### 2026-05-09 — Backend API & Agent build

**Files created/modified:**
- `talent_backend/pyproject.toml` — added all runtime deps (fastapi, uvicorn, psycopg, azure-identity, msal, openai, etc.)
- `talent_backend/talent_backend/config.py` — extended with Azure OpenAI, Entra ID, Foundry, App Insights, and agent instructions path
- `talent_backend/talent_backend/auth.py` — Entra ID JWT validation + dev-mode bypass
- `talent_backend/talent_backend/main.py` — FastAPI app factory with lifespan (DB pool, OpenAI client, TalentAgent init)
- `talent_backend/talent_backend/api/__init__.py` — router exports
- `talent_backend/talent_backend/api/health.py` — liveness + readiness probes
- `talent_backend/talent_backend/api/chat.py` — NL chat endpoint → TalentAgent
- `talent_backend/talent_backend/api/search.py` — structured search endpoints (candidates, employee, semantic, text, team)
- `talent_backend/talent_backend/agent/__init__.py`
- `talent_backend/talent_backend/agent/talent_agent.py` — core agent class: system prompt + tool-calling loop
- `talent_backend/talent_backend/agent/tools.py` — 9 tool schemas + execute dispatch to data_access layer
- `talent_backend/talent_backend/agent/prompts.py` — system prompt assembly (loads MD file + intent classification addendum)

**Key patterns:**
- Lazy imports for `talent_backend.data_access.*` — backend loads before data access layer exists.
- Agent uses OpenAI function calling with up to 5 tool-call rounds.
- `DefaultAzureCredential` for Azure OpenAI auth (no API keys).
- Auth bypass: `TALENTIQ_AUTH_DISABLED=true` skips JWT validation for local dev.
- All endpoints under `/api/v1/` prefix.
- Embedding generation helper reused by agent and semantic search endpoint.

### 2026-05-09 — Cross-agent: Parker's data access layer
- Parker created `talent_backend/talent_backend/data_access/` (8 modules)
- All functions are `async def` accepting `AsyncConnection` from psycopg3
- Pool singleton: `init_pool()` / `close_pool()` — call from FastAPI lifespan
- Key imports: `from talent_backend.data_access.cypher_queries import ...`, same for `sql_queries`, `vector_queries`, `fts_queries`, `hybrid_queries`
- Models: `EmployeeResult`, `SearchFilters`, `SearchRequest`, `TeamHierarchy`, `SkillGapResult`, `DashboardMetrics`, `FTSResult`, `VectorSearchResult`
- Hybrid search: `multi_criteria_search()` with configurable weights dict
- AGE graph name from `connection.GRAPH_NAME` (env var `GRAPH_NAME`, default `talent_graph`)
