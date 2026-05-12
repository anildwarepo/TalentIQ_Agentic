# Kane — History Archive

Entries summarized and archived from main history.md to keep recent context accessible.

## 2026-05-09 — Backend API & Agent Build (Archived Summary)

**Full implementation of FastAPI backend with Agent Framework integration.** Created core modules:
- `talent_backend/pyproject.toml` — all runtime deps
- `talent_backend/talent_backend/config.py` — Azure OpenAI, Entra ID, Foundry, App Insights, agent instructions
- `talent_backend/talent_backend/auth.py` — JWT validation with Entra ID JWKS
- `talent_backend/talent_backend/main.py` — FastAPI lifespan (DB pool, Foundry client, TalentAgent)
- `talent_backend/talent_backend/api/{health,chat,search}.py` — endpoints with NL chat + structured search
- `talent_backend/talent_backend/agent/{talent_agent,tools,prompts}.py` — Agent Framework agent with up to 5 tool-call rounds

**Key patterns:** Lazy imports for data_access layer, `DefaultAzureCredential` for Azure OpenAI, auth bypass via `TALENTIQ_AUTH_DISABLED=true`, all endpoints under `/api/v1/`.

## 2026-05-09 — Cross-agent: Parker's Data Access Layer (Archived Summary)

**Parker completed `talent_backend/talent_backend/data_access/` with 8 async modules.** All functions accept `AsyncConnection` from psycopg3. Pool singleton with `init_pool()` / `close_pool()` for lifespan. Models: `EmployeeResult`, `SearchFilters`, `SearchRequest`, `TeamHierarchy`, `SkillGapResult`, `DashboardMetrics`, `FTSResult`, `VectorSearchResult`. Graph name from `connection.GRAPH_NAME` env var. Hybrid search with `multi_criteria_search()` and configurable weights.

## 2026-05-09 — Chat History Persistence (Archived Summary)

**Cosmos DB integration for conversation persistence.** Created `ChatHistoryService` class (async Cosmos SDK). Partition key `/session_id`. Two document types: `message` and `session_meta`. User ID enforced on all reads. Graceful degradation if Cosmos unavailable. History capped at 20 messages. Three session endpoints: `GET /sessions`, `GET /sessions/{id}`, `DELETE /sessions/{id}`. Note: `ChatHistoryStore` uses **sync** SDK — needs migration to async for production.

## 2026-05-09 — Agent Framework Rewrite (Archived Summary)

**Replaced raw OpenAI function calling with Agent Framework.** Updated pyproject.toml, config.py (`MCP_ENDPOINT`), and full rewrite of `talent_agent.py` to use `Agent`, `MCPStreamableHTTPTool`, `OpenAIChatCompletionClient`. Stripped `tools.py` to just embedding generation. Streaming via `agent.run(messages, stream=True)`. Instructions loaded from local `instructions/` dir with fallback. Lazy agent init on first `process_message()` call.

## 2026-05-09 — Entra ID Compliance (Archived Summary)

**JWT validation against Microsoft JWKS, dual-audience pattern.** Created `talent_backend/talent_backend/auth.py`. JWKS cached 1 hour. Accepts both `https://ai.azure.com` (Foundry scope) and app client ID. Dev mode: auth bypass if `AZURE_TENANT_ID` unset. `Depends(get_current_user)` on all endpoints except `/health`.

## 2026-05-10 — Session Architecture (Archived Summary)

**Agent Framework `InMemoryHistoryProvider` for per-session chat history.** `AgentSession(session_id=X)` passed to `run()`. Agent-as-tool calls are independent — each gets fresh history. Triage agent reads own history across turns. Session ID flow: UI → API → `_build_chat_history()` → agent middleware. Fixed bug: UI's graph response handler wasn't storing session_id.

## 2026-05-10 — Technical Specs & Architecture (Archived Summary)

**Documented 5 spec files under `docs/specs/`.** Key architectural patterns: Agent-as-tool handoff (triage → specialists), MCP tool logging with `[QUERY]`/`[RESULT]` tags, vector search injection prevention (column whitelist), ChatHistoryStore sync→async migration (production TODO), auth dual-audience pattern (Foundry + app client ID), JWKS retry on `kid` mismatch, future RBAC with app roles, session management feature flag.

## 2026-05-10 — Build System Fix (Archived Summary)

**Fixed `talent_backend/pyproject.toml` build-system config.** Added `[build-system]` + `[tool.hatch.build.targets.wheel]` with `packages = ["talent_backend"]`. Without these, `uv` treated it as namespace package to outer directory. After build config changes, run `uv sync --all-packages`.

## 2026-05-10 — CV Generation & Vector Search (Archived Summary)

**Two key implementation learnings.**
- python-docx: MUST preserve `w:sectPr` in body or `sections[-1]` crashes. PDF templates not supported (mark as preview-only). OpenAI ada-002 doesn't support `dimensions` param (only embedding-3-* models).
- Vector search: psycopg3 uses `%s` placeholders, not `$1`/$2`. Pre-warm `DefaultAzureCredential` with `credential.get_token()` at client creation to prevent IMDS probe storms. Wrap sync `embeddings.create` in `loop.run_in_executor()` for async MCP. Use single vector search call (limit=50) for RFP matching, not per-role calls.

## 2026-05-10 — Run Log Streaming (Archived Summary)

**MCP tool logging architecture.** Tools emit `[QUERY]` and `[RESULT]` tags via `ctx.info()`. API layer `_AgentLogHandler` captures logger output, pushes to queue. Classify: handoffs, structured tags, legacy tool messages. Suppress duplicates for MCP tools with own tags. Frontend classifies: `[QUERY]` → badge, `[RESULT]` → green, `[HANDOFF]` → purple.

## 2026-05-10: Cross-agent — Tech Spec Decisions (Archived Summary)

**From Ripley (Product):** Co-host backend+MCP on same App Service. OTel SDK for observability. JSON logging with correlation IDs.
**From Dallas (Frontend):** SSE via POST+ReadableStream. Proactive 5-min token refresh. AbortController for cancellation.
**From Parker (MCP):** 3 gaps: (a) `search_graph_nodes()` SQL function missing, (b) `employee_ageid` always 0, (c) `pg_trgm` availability on Azure.
