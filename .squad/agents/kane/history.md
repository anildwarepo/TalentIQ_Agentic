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

### 2026-05-09 — Chat history persistence (Cosmos DB)

**Files created/modified:**
- `app_config/.env` — added `COSMOS_CHAT_ENDPOINT`, `COSMOS_CHAT_DATABASE`, `COSMOS_CHAT_CONTAINER`
- `talent_backend/pyproject.toml` — added `azure-cosmos>=4.7.0`
- `talent_backend/talent_backend/config.py` — added 3 new config vars for Cosmos chat
- `talent_backend/talent_backend/chat_history.py` — NEW: `ChatHistoryService` class (async Cosmos SDK)
- `talent_backend/talent_backend/agent/talent_agent.py` — `process_message` now accepts `conversation_history` param
- `talent_backend/talent_backend/api/chat.py` — integrated history load/save + 3 new session management endpoints
- `talent_backend/talent_backend/main.py` — Cosmos client init in lifespan, graceful degradation

**Key patterns:**
- Cosmos partition key: `/session_id` — one partition per conversation session
- Two document types in the container: `message` and `session_meta`
- `user_id` enforced on every read/write — no cross-user data leakage
- Best-effort history: if Cosmos is unavailable, chat still works stateless
- `DefaultAzureCredential` reused from the existing credential instance
- Agent history capped at 20 messages to control token budget
- Session management endpoints: `GET /sessions`, `GET /sessions/{id}`, `DELETE /sessions/{id}`
- `list_user_sessions` uses cross-partition query (sessions span partition keys)

### 2026-05-09 — Agent Framework rewrite (replacing raw OpenAI function calling)

**Files modified:**
- `talent_backend/pyproject.toml` — replaced `azure-ai-projects` with `agent-framework>=1.3.0`
- `talent_backend/talent_backend/config.py` — added `MCP_ENDPOINT` env var (default `http://localhost:3002/mcp`)
- `talent_backend/talent_backend/agent/talent_agent.py` — FULL REWRITE: now uses `Agent`, `MCPStreamableHTTPTool`, `OpenAIChatCompletionClient` from `agent_framework`
- `talent_backend/talent_backend/agent/tools.py` — stripped to just `generate_embedding()` (search endpoints still need it); all tool definitions + dispatch removed
- `talent_backend/talent_backend/agent/prompts.py` — simplified to basic instruction loader; intent classification addendum removed (MCP server handles tool routing)
- `talent_backend/talent_backend/agent/__init__.py` — updated docstring
- `talent_backend/talent_backend/main.py` — TalentAgent now created with `credential=` + `mcp_endpoint=` instead of `openai_client=` + `db_pool=`
- Created `talent_backend/talent_backend/agent/instructions/` — local copy of agent instructions file

**Key patterns:**
- `MCPStreamableHTTPTool(name="talent_graph_mcp", url=MCP_ENDPOINT)` — single MCP tool replaces all 9 manual tool definitions
- `OpenAIChatCompletionClient(credential=credential)` — Entra ID auth via Agent Framework, not raw OpenAI SDK
- Agent is lazily initialized (`_ensure_agent`) on first `process_message()` call
- Streaming: `agent.run(messages, stream=True)` → async iterate `AgentResponseUpdate` / `AgentResponse`
- `_sanitize_output()` strips Unicode oddities and leaked Python object refs from agent output
- Instructions loaded from local `instructions/` dir first, fallback to repo-level path
- `openai_client` retained in `main.py` for search endpoints that call `generate_embedding()` directly
- `process_message()` signature unchanged — chat endpoint needs no changes

### 2026-05-09 — Cross-agent: Parker's MCP server is live
- MCP server at `talent_backend/talent_backend/mcp_server/` — port 3002, streamable-http
- 8 tools available via MCP: fetch_ontology, query_using_sql_cypher, search_graph, resolve_entity_ids, build_query_context, discover_nodes, analyze_graph_statistics, save_ontology
- Pre-loaded ontology eliminates discovery round-trip

### 2026-05-09 — Entra ID token audience & issuer fixes
- Entra ID v1 vs v2 token issuers: when scope targets a v1 resource like `https://ai.azure.com`, Azure AD issues v1 tokens with issuer `https://sts.windows.net/{tenant}/`. Backend must accept both.
- `AZURE_TOKEN_AUDIENCE` config var added — defaults to `https://ai.azure.com` for Foundry-scoped tokens.
- Auth validation chain: JWKS fetch → key match → RS256 signature → expiration → audience (Foundry scope + app client ID) → issuer (v1 + v2).
- Agent connects via `MCPStreamableHTTPTool(name="talent_graph_mcp", url=MCP_ENDPOINT)`
- Existing data_access layer still powers `/api/v1/search/*` structured endpoints

### 2026-05-09 — Entra ID JWT validation module
- `talent_backend/talent_backend/auth.py` — validates JWT signature, exp, iss, aud against Microsoft JWKS
- JWKS cached 1 hour for performance
- Dev mode: if `AZURE_TENANT_ID` not set, auth bypassed with warning log
- `Depends(get_current_user)` applied to all endpoints except `/health`
- Added `PyJWT[crypto]` and `httpx` to `talent_backend/pyproject.toml`

### 2026-05-09 — NDJSON streaming endpoint for graph responses
- Added `POST /af/graph/responses` to `talent_backend/talent_backend/api.py`
- Streams NDJSON with `response_message` wrappers matching Dallas's frontend SSE parser
- Frontend proxies `/af` → `http://localhost:8000` via Vite config

### 2026-05-09 — pyproject.toml build-system fix
- `talent_backend/pyproject.toml` was missing `[build-system]` and `[tool.hatch.build.targets.wheel]`
- Without these, `uv` couldn't build it as a proper package — resolved as namespace package to outer directory
- Fix: added hatchling build-system config with `packages = ["talent_backend"]`
- After any build config change, must run `uv sync --all-packages`

### 2026-05-10: Session architecture — AgentSession + InMemoryHistoryProvider
- Agent Framework's `InMemoryHistoryProvider` middleware gives each agent per-session chat history
- `AgentSession(session_id=X)` passed to `run()` keys the history
- `propagate_session=True` on `as_tool()` passes session to child agents
- BUT: agent-as-tool calls are independent — child agents DON'T inherit parent's history. Each call is fresh.
- The triage agent CAN see its own history (including tool call results) across user turns
- Session ID must flow: UI → API request body → `_build_chat_history()` → `AgentSession` → agent middleware
- Critical bug fixed: UI's graph response handler wasn't storing `session_id` from `done` events — every request created a new session

### 2026-05-10: Agent-as-tool handoff limitations
- Agent-as-tool pattern: child agent runs to completion in ONE call, returns text. Cannot pause for user input.
- Two-phase flows (list options → wait → act) require the PARENT (triage) to manage state, not the child
- The triage agent reads its own chat history to reconstruct context for the second handoff
- For reliable mapping (e.g., "1" → template filename), code-level augmentation in the API layer is more reliable than LLM instructions
- `_augment_cv_template_choice()` in api.py rewrites short user replies to full handoff messages before they enter chat history

### 2026-05-10: CV generation with python-docx templates
- python-docx `Document(template_path)` + clearing body elements: MUST preserve `w:sectPr` elements or `sections[-1]` crashes with IndexError
- PDF templates cannot be used for generation — docx only. Mark PDFs as "preview only" in the template list
- OpenAI ada-002 does NOT support the `dimensions` parameter — that's only for text-embedding-3-* models

### 2026-05-10: Vector search MCP tool
- Created `vector_search` tool using pgvector cosine similarity against `employee_embeddings` table
- DiskANN or HNSW index depending on availability
- psycopg3 uses `%s` placeholders (not PostgreSQL-native `$1`/$2`)
- `DefaultAzureCredential` pre-warm: call `credential.get_token()` once at client creation to cache the credential provider — prevents 10 parallel IMDS timeout probes (5s each)
- Sync OpenAI `embeddings.create` must be wrapped in `loop.run_in_executor()` for async MCP tools
- For RFP matching: ONE combined vector search call (limit=50) instead of per-role calls (10x latency)

### 2026-05-10: Run log streaming architecture
- MCP tools emit structured `[QUERY] TYPE: ...` and `[RESULT] TYPE: ...` via `ctx.info()`
- `_AgentLogHandler` in api.py captures `agent_framework` logger, pushes to queue
- `_drain_log_events()` classifies: handoffs, structured tags, legacy tool messages
- Suppress duplicate `Function name: X` / `Function X succeeded` for MCP tools that emit their own structured tags
- Frontend classifies by prefix: `[QUERY]` → badge CYPHER/SQL/FTS/VECTOR/STATS, `[RESULT]` → green, `[HANDOFF]` → purple
