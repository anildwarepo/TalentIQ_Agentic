# Kane — History

## Project Context

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

<!-- Recent learnings (2026-05-12 and current sprint). Older entries archived to history-archive.md. -->

### 2026-05-16 — Clean MCP tool descriptions for resolve-first query architecture

**Files modified:**
- `talent_backend/talent_backend/mcp_server/graph_tools.py` — Updated `query_using_sql_cypher` docstring to mandate `v.code = 'X'` matching (no regex on names). Updated `search_graph` description to clarify it's for **employee name lookup only**, not entity resolution.
- `talent_backend/talent_backend/mcp_server/vector_tools.py` — Updated `vector_search` description to state it's for **resume/skills semantic matching only** (RFP role matching, capability search). Explicit "do NOT use for entity lookups."
- `talent_backend/talent_backend/mcp_server/entity_tools.py` — Updated `resolve_entities` docstring: "CALL THIS FIRST", use returned `code` in Cypher WHERE clauses, do not fall back to regex/vector_search after resolution.

**Architecture pattern (decided by Anil):**
- `User question → resolve_entities() → clean Cypher with codes → execute`
- Vector search is ONLY for fuzzy resume/skill description matching (RFP, "someone good with X"), NOT for entity lookup.
- The resolve logic itself is unchanged (exact code → exact name → FTS → RRF → alias → not-found). Only descriptions/docstrings changed.

### 2026-05-15 — resolve_entities MCP tool

**Files created/modified:**
- `talent_backend/talent_backend/mcp_server/entity_tools.py` — NEW. `resolve_entities` MCP tool that resolves user terms to canonical entity names/codes via the `entity_search` PostgreSQL table.
- `talent_backend/talent_backend/mcp_server/server.py` — Added `entity_tools` import for tool registration.

**Architecture decisions:**
- Uses the SAME connection pool as all other MCP tools (`_pg()._pool`) — no separate pool.
- Cascading resolution strategy: exact code → exact name → FTS → alias substring → not-found. Priority order gives deterministic, highest-confidence matches first.
- All SQL uses parameterized queries (`%s` placeholders) — no f-strings with user input.
- Gracefully handles missing `entity_search` table by checking `information_schema.tables` and returning all not-found results.
- Entity type validated against a frozen set whitelist before querying.
- Processes queries sequentially within a single DB connection to avoid pool exhaustion on large batches.
- Confidence scores: 1.0 for exact matches, min(0.9, ts_rank) for FTS, 0.7 for alias substring.

**Patterns:**
- Followed `vector_tools.py` pattern for raw pool access: `pg._ensure_open()` → `pg._pool.connection()` → parameterized `cur.execute()`.
- `ctx.info()` logging mirrors existing tools.
- `_resolve_single()` helper keeps the main tool function clean.

### 2026-05-15 — Per-question pipeline logging

**Files created/modified:**
- `talent_backend/talent_backend/pipeline_logger.py` — NEW. `PipelineLogger` class that collects events during a request lifecycle and writes structured JSON to disk. `parse_log_event()` parses the existing `_AgentLogHandler` messages into pipeline events.
- `talent_backend/talent_backend/config.py` — Added `ENABLE_PIPELINE_LOGGING` and `PIPELINE_LOG_DIR` env vars.
- `talent_backend/talent_backend/api.py` — Hooked `PipelineLogger` into both `_stream_agent` (SSE) and `_stream_graph` (NDJSON). The `_AgentLogHandler.emit()` in `_stream_graph` now also feeds `parse_log_event()`.
- `.gitignore` — Added `query_logs/`.

**Architecture decisions:**
- Pipeline logger is instantiated per-request in the endpoint handler, passed into the streaming generator, and flushed after the `done` event. This keeps it scoped to a single question.
- File I/O is non-blocking via `asyncio.run_in_executor`. Logging never delays the response.
- Integration uses the existing `[QUERY]`/`[RESULT]`/handoff log messages — no changes to Agent Framework or MCP tools needed.
- Email PII masked with regex. User OIDs kept (internal Azure AD identifiers).
- Output folder: `query_logs/{timestamp}_{session_short}_{question_hash}/` — sortable by time, groupable by session.
- Each query saved as separate file in `queries/` subfolder: `.sql` for Cypher/SQL/FTS, `.json` for vector searches.

**Patterns:**
- For non-blocking async file writes: `loop.run_in_executor(None, self._write_files)` keeps the sync Path.write_text off the event loop.
- To avoid breaking existing streaming generators, the logger is an additive parameter — old call signatures are updated but all existing behavior preserved.

### 2026-05-15 — Thread management endpoints (chat history Phase 2)

**Files modified:**
- `talent_backend/talent_backend/chat_history.py` — Added 5 new methods to `ChatHistoryStore`: `list_threads()`, `get_thread_messages()`, `get_thread_meta()`, `soft_delete_thread()`, `rename_thread()`. Modified `add_message()` to accept optional `user_id` kwarg and auto-create/update `session_meta` documents.
- `talent_backend/talent_backend/api.py` — Added 4 new endpoints: `GET /api/threads`, `GET /api/threads/{id}`, `DELETE /api/threads/{id}`, `PATCH /api/threads/{id}`. Updated CORS to allow DELETE/PATCH. Wired `user_id` (from `user["oid"]`) into `_build_chat_history()`.

**Architecture decisions:**
- `session_meta` documents live in the SAME Cosmos container/partition as messages (partition key = session_id). The `type` field distinguishes `session_meta` from `message` docs.
- `list_threads()` requires `enable_cross_partition_query=True` since it queries by `user_id` across partitions. This is acceptable for a user's thread list (low cardinality).
- Thread ownership enforced via `user["oid"]` comparison in every endpoint — returns 404 (not 403) for wrong user to avoid leaking thread existence.
- Soft delete sets `is_deleted=true` + `deleted_at` on the meta doc. Messages are retained. `list_threads` filters out deleted threads.
- `add_message()` backward-compatible — `user_id` is optional kwarg, defaults to None.
- In-memory fallback (`_fallback_meta` dict) mirrors all Cosmos operations for local dev.
- Legacy `/api/sessions/*` endpoints preserved alongside new `/api/threads/*` endpoints.

### 2026-05-12 — Cross-agent: Bishop's infrastructure Pass 3 — Container App deployment
**From Bishop (Deployment Engineer):**
- Backend Container App is now provisioned with User-Assigned Managed Identity (UAMI). Backend code MUST authenticate using `DefaultAzureCredential` with the `AZURE_CLIENT_ID` env var to specify which UAMI to use.
- Passwordless authentication now available for:
  - **PostgreSQL:** Connect via `POSTGRES_HOST` env var using `DefaultAzureCredential` to acquire Entra ID token. No SQL password in connection string.
  - **Cosmos DB:** RBAC only. Backend UAMI has Built-in Data Contributor role assigned.
  - **Azure AI Foundry:** Backend UAMI has Cognitive Services OpenAI User role assigned. Use `FOUNDRY_ENDPOINT` env var.
  - **Key Vault:** Backend UAMI has Key Vault Secrets User role assigned. Use `KEY_VAULT_URI` env var.
  - **Application Insights:** Send telemetry to `APPLICATIONINSIGHTS_CONNECTION_STRING` env var.
- **Action required:** Create `Dockerfile` under `talent_backend/`, refactor DB connection for passwordless auth, update `config.py` to read env vars (`POSTGRES_HOST`, `POSTGRES_DB`, `COSMOS_ENDPOINT`, `FOUNDRY_ENDPOINT`, `FOUNDRY_DEPLOYMENT_NAME`, `KEY_VAULT_URI`, `APPLICATIONINSIGHTS_CONNECTION_STRING`, `AZURE_CLIENT_ID`), and apply same pattern to MCP server.

### 2026-05-12 — Cross-agent: Lambert's probes module — Available for use
**From Lambert (Tester):**
- Created `talent_backend/talent_backend/probes/` package with three reusable probe modules:
  - `smoke_pg.py` — Postgres connectivity, extensions (age, vector, pg_trgm), AGE graph, Cypher count, vector top-K, full-text search
  - `smoke_foundry.py` — Foundry gpt-5.4 chat completion via UAMI (Mechanism A: `az containerapp exec`)
  - `smoke_mcp_pg.py` — MCP→Postgres connectivity, AGE, Cypher count
- Each probe prints JSON output, runs inside Container App via `az containerapp exec`
- **Positioned for future use:** These probes can be wrapped as `/health/pg`, `/health/foundry`, `/health/mcp` endpoints in the backend API
- **No action needed:** Probes ship with the existing `talent_backend` wheel — no Docker image changes required
- **Infrastructure contract:** These env vars passed to Container App at deployment time. Backend responsible for using them with `DefaultAzureCredential`.

### 2026-05-12 — Cross-agent: Lambert's smoke test expectations for backend
**From Lambert (Tester):**
- test_03_backend_foundry.py validates Foundry chat completion using deployer credentials (`azd auth context`). This is a temporary workaround.
- **Future improvement (low-risk follow-on):** Backend should expose a `/health/foundry` endpoint that uses UAMI-acquired token (not deployer creds). This enables production-safe health checks without exposing Azure credentials to test runners. The endpoint would do a minimal Foundry API call (e.g., list models or a dummy completion) and return 200 on success.
- Current test documents this gap; blocking production deployment is not necessary — the smoke suite gates deployment readiness, and the `/health/foundry` endpoint is a polish improvement for the next iteration.

---

## Archived Entries

Earlier learnings from 2026-05-08 through 2026-05-10 have been summarized and moved to [kane/history-archive.md](history-archive.md) to keep this file focused on recent context. Topics archived:
- Backend API & Agent Framework build (full implementation notes)
- Cosmos DB chat history persistence
- Session architecture (InMemoryHistoryProvider)
- Technical specs & architecture decisions
- Build system configuration
- Vector search + CV generation patterns
- Run log streaming architecture
- Cross-agent tech spec decisions (Ripley, Dallas, Parker)
- Entra ID token audience & issuer fixes
- NDJSON streaming endpoint
- pyproject.toml build-system fix
- Agent-as-tool handoff limitations
**From Bishop (Deployment Engineer):**
- Backend Container App is now provisioned with User-Assigned Managed Identity (UAMI). Backend code MUST authenticate using `DefaultAzureCredential` with the `AZURE_CLIENT_ID` env var to specify which UAMI to use.
- Passwordless authentication now available for:
  - **PostgreSQL:** Connect via `POSTGRES_HOST` env var using `DefaultAzureCredential` to acquire Entra ID token. No SQL password in connection string.
  - **Cosmos DB:** RBAC only. Backend UAMI has Built-in Data Contributor role assigned.
  - **Azure AI Foundry:** Backend UAMI has Cognitive Services OpenAI User role assigned. Use `FOUNDRY_ENDPOINT` env var.
  - **Key Vault:** Backend UAMI has Key Vault Secrets User role assigned. Use `KEY_VAULT_URI` env var.
  - **Application Insights:** Send telemetry to `APPLICATIONINSIGHTS_CONNECTION_STRING` env var.
- **Action required:** Create `Dockerfile` under `talent_backend/`, refactor DB connection for passwordless auth, update `config.py` to read env vars (`POSTGRES_HOST`, `POSTGRES_DB`, `COSMOS_ENDPOINT`, `FOUNDRY_ENDPOINT`, `FOUNDRY_DEPLOYMENT_NAME`, `KEY_VAULT_URI`, `APPLICATIONINSIGHTS_CONNECTION_STRING`, `AZURE_CLIENT_ID`), and apply same pattern to MCP server.

### 2026-05-12 — Cross-agent: Lambert's probes module — Available for use
**From Lambert (Tester):**
- Created `talent_backend/talent_backend/probes/` package with three reusable probe modules:
  - `smoke_pg.py` — Postgres connectivity, extensions (age, vector, pg_trgm), AGE graph, Cypher count, vector top-K, full-text search
  - `smoke_foundry.py` — Foundry gpt-5.4 chat completion via UAMI (Mechanism A: `az containerapp exec`)
  - `smoke_mcp_pg.py` — MCP→Postgres connectivity, AGE, Cypher count
- Each probe prints JSON output, runs inside Container App via `az containerapp exec`
- **Positioned for future use:** These probes can be wrapped as `/health/pg`, `/health/foundry`, `/health/mcp` endpoints in the backend API
- **No action needed:** Probes ship with the existing `talent_backend` wheel — no Docker image changes required
- **Infrastructure contract:** These env vars passed to Container App at deployment time. Backend responsible for using them with `DefaultAzureCredential`.

### 2026-05-12 — Cross-agent: Lambert's smoke test expectations for backend
**From Lambert (Tester):**
- test_03_backend_foundry.py validates Foundry chat completion using deployer credentials (`azd auth context`). This is a temporary workaround.
- **Future improvement (low-risk follow-on):** Backend should expose a `/health/foundry` endpoint that uses UAMI-acquired token (not deployer creds). This enables production-safe health checks without exposing Azure credentials to test runners. The endpoint would do a minimal Foundry API call (e.g., list models or a dummy completion) and return 200 on success.
- Current test documents this gap; blocking production deployment is not necessary — the smoke suite gates deployment readiness, and the `/health/foundry` endpoint is a polish improvement for the next iteration.

## Cross-agent note — 2026-05-21 (Scribe)
- `Get-ParameterValue` in `talent_infra_modules/shared/common.ps1` now safely handles secure prompts. Bishop fixed a case-insensitive variable/parameter shadow on 2026-05-21 — the local `$secure = Read-Host -AsSecureString` was overwriting the `[switch]$Secure` parameter (PowerShell variable names are case-insensitive, so `$secure` and `$Secure` are the same slot). Local renamed to `$secureValue`. Toolkit rule (captured in `decisions.md`): when a natural local name would collide with a parameter, use suffixed names (`$secureValue`, `$nameStr`, `$promptText`). Relevant to `02-backend/deploy.ps1` redeploys when Anil supplies the admin password interactively rather than via env var.
