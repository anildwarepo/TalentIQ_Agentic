# Decisions

> Shared decision log. All agents read this before starting work.
> Only the Coordinator (via Scribe merge) writes here.

<!-- Decisions appear below, newest first. -->

### 2026-05-12: Charter clarification — talentiq_requirements READ-ONLY
**By:** Bishop (Deployment Engineer)
**Status:** Documented
**What:** `talentiq_requirements/` is READ-ONLY reference material. Bishop never edits, moves, or deletes anything under `talentiq_requirements/`. All deployment artifacts go in `talent_infra/`, `azure.yaml` (root), and `docs/deployment/`.
**Why:** User directive clarification. Keep requirements separate from implementation.

### 2026-05-12: All infra under talent_infra/
**By:** Bishop (Deployment Engineer)
**Status:** Documented
**What:** ALL deployment/infra components live under `talent_infra/` at the repo root. This includes Bicep (`talent_infra/main.bicep`, `talent_infra/modules/`), `talent_infra/azure.yaml`, parameters, and deployment docs. No `infra/` folder, no root-level `azure.yaml`.
**Why:** Centralized infrastructure location. Aligns with `talent_` prefix convention.

### 2026-05-12: VNet CIDR Plan — 10.0.0.0/16
**By:** Bishop (Deployment Engineer)
**Status:** Implemented
**What:** VNet address space 10.0.0.0/16 with three subnets:
- `snet-aca` (10.0.0.0/23) — Container Apps Environment, delegated to Microsoft.App/environments
- `snet-pe` (10.0.2.0/24) — Private endpoints for all PaaS services
- `snet-db` (10.0.3.0/24) — PostgreSQL Flexible Server, delegated to Microsoft.DBforPostgreSQL/flexibleServers
**Why:** Aligns with architecture spec in `docs/specs/vnet-integration.md`. /23 for ACA is Azure-recommended production minimum. Leaves 10.0.4.0/24+ free for NAT Gateway or future subnets.
**Impact:** All future modules reference subnet IDs from vnet module outputs (acaSubnetId, peSubnetId, dbSubnetId).

### 2026-05-12: Resource Naming Convention
**By:** Bishop (Deployment Engineer)
**Status:** Implemented
**What:** All Azure resources follow `{abbreviation}-talentiq-{environmentName}-{resourceToken}` where resourceToken = `toLower(uniqueString(subscription().id, resourceGroup().id, location))`. Standard Azure abbreviations: vnet, cae, nsg, ca, pep, pdnsz, etc.
**Why:** Deterministic, collision-free, azd-friendly. The `resourceToken` ensures uniqueness across subscriptions while keeping names human-readable. Matches patterns in `talentiq_requirements/foundy-managed-vnet-setup/`.
**Impact:** All future modules must accept `environmentName` and `resourceToken` params and follow this convention.

### 2026-05-12: ACA Environment — Single External with Consumption Profile
**By:** Bishop (Deployment Engineer)
**Status:** Implemented
**What:** Single Container Apps Environment with `internal: false` and Consumption workload profile. Frontend Container App will use `ingress.external: true` for public access; backend and MCP will use `ingress.external: false` (VNet-only). No Application Gateway needed.
**Why:** Simplest approach for mixed ingress (public frontend + internal backend/MCP). Two-environment or internal-with-AppGW approaches add cost and complexity with no benefit at this scale.
**Impact:** All Container App modules must set ingress.external correctly. If WAF is required later, can layer Application Gateway or Front Door in front without changing the CAE.

### 2026-05-11: Workday Integration Architecture
**By:** Ripley (Lead Architect)
**Status:** Proposed
**What:**
1. Container Apps Jobs for pipeline scheduling — no timeout limits (full load ~2.5h), same VNet, supports CRON + manual trigger. Preferred over Functions (10-min timeout), WebJobs (resource contention), K8s CronJobs (no cluster).
2. RaaS for bulk extraction, REST API for documents — six custom RaaS reports needed (Workers, Skills, Certifications, Education, Languages, Organizations). Must be created by Workday admin team.
3. Delta reports (RaaS with date range) for incremental sync — daily cadence at 02:00 UTC. Webhooks deferred to Phase 4.
4. Soft delete for terminations — terminated employees marked `employment_status='Terminated'` but not removed from graph. Search layer filters them out.
5. Dual-graph swap for zero-downtime full loads — load into `talent_graph_staging`, validate, rename to `talent_graph`. Old graph kept for rollback.
6. Workday credentials in Key Vault only — ISU client ID/secret via managed identity. Dev uses env vars for sandbox credentials only.
7. CV storage in Azure Blob (private endpoint) — path `cvs/{workday_id}/{filename}`. Managed identity RBAC. Local filesystem fallback for dev.
8. Synthetic pipeline as permanent fallback — `WORKDAY_ENABLED=false` (default) keeps synthetic pipeline operational. Rollback = flip flag + restore old graph.
**Artifacts:** `docs/specs/workday-integration.md`
**Impact:** Parker (delta upsert loaders, pipeline tables), Kane (future admin API), Dallas (future data freshness badge), DevOps (Container Apps Job, Key Vault, Blob Storage), Workday Admin (6 RaaS reports + ISU security group).

### 2026-05-10: Tech spec decisions — Infrastructure & Architecture
**By:** Ripley (Lead Architect)
**Status:** Documented
**What:**
1. Co-host Backend API + MCP Server on same App Service — MCP stays on localhost, simpler ops. Separate only when scaling demands it.
2. PostgreSQL uses delegated subnet, not private endpoint — simpler, lower latency, native VNet integration for Flex Server.
3. NAT Gateway over Azure Firewall for egress — sufficient for current needs, fraction of the cost. Add Firewall only if compliance mandates egress filtering.
4. OpenTelemetry SDK (not App Insights Python SDK) for backend — vendor-neutral, richer auto-instrumentation, same Azure Monitor backend.
5. Structured JSON logging with OTel correlation — enables trace stitching between frontend App Insights and backend spans.
**Artifacts:** `docs/specs/backend-architecture.md`, `docs/specs/vnet-integration.md`, `docs/specs/telemetry.md`
**Impact:** All agents — specs are canonical reference for infrastructure, deployment, and observability.

### 2026-05-10: Tech spec decisions — Backend Sessions & Auth
**By:** Kane (Backend Dev)
**Status:** Proposed
**What:**
1. `SESSION_PROVIDER` env var (`in_memory` | `cosmos`) controls history provider — phased migration, no big-bang cutover.
2. Chat history and session state use separate Cosmos containers — different TTL, access patterns, consumers.
3. ChatHistoryStore must migrate to async Cosmos SDK — sync calls block the event loop under concurrent load.
4. RBAC via Entra ID app roles + `require_role()` decorator — Manager, PreSales, Admin, Viewer roles from JWT claims.
5. JWKS should retry on `kid` mismatch before rejecting — handles Microsoft key rotation during 1-hour cache window.
6. All agents share one HistoryProvider instance — enables cross-agent context continuity within a session.
**Artifacts:** `docs/specs/agent-orchestration.md`, `docs/specs/mcp-server-tools.md`, `docs/specs/session-management.md`, `docs/specs/chat-history.md`, `docs/specs/authentication.md`
**Impact:** Kane, Dallas — session and auth behavior changes.

### 2026-05-10: Tech spec decisions — Frontend Production Readiness
**By:** Dallas (Frontend Dev)
**Status:** Proposed
**What:**
1. SSE via POST + ReadableStream (not EventSource) — EventSource lacks auth headers and JSON body support.
2. Token cache: switch to `localStorage` for production — enables cross-tab SSO (requires CSP headers for XSS mitigation).
3. Add AbortController + "Stop generating" button for stream cancellation.
4. Proactive token refresh (5-minute window) — prevents mid-stream auth failures.
5. Fluent UI v9 for production components — Phase 3, ~80-100KB bundle addition.
6. i18n via react-i18next for ES/EN/FR/PT — Phase 3, ~130 UI chrome strings.
7. Performance budgets: LCP < 2.5s, FID < 100ms, CLS < 0.1, bundle < 350KB gzip.
**Artifacts:** `docs/specs/ui-sse-auth.md`, `docs/specs/ui-agentic-production.md`
**Impact:** Dallas — frontend implementation targets. No immediate backend changes.

### 2026-05-10: Tech spec decisions — Database Architecture
**By:** Parker (Data Engineer)
**Status:** Documented
**What:**
1. Comprehensive database architecture spec — 14 node labels, 12 edge labels, vector/FTS/relational layers documented.
2. Three production gaps: (a) `search_graph_nodes()` SQL function not in pipeline, (b) `employee_ageid` always 0, (c) `pg_trgm` extension availability on Azure.
**Artifacts:** `docs/specs/database-architecture.md`
**Impact:** Kane + Parker — gaps must be resolved before staging deployment.
**Note:** AGE query rules and vector search single-call pattern previously captured in "Architecture patterns established" entry.

### 2026-05-10: Architecture patterns established
**By:** Team (session work)
**Status:** Implemented
**What:** 
1. Session ID flow: UI stores session_id from graph responses, sends on subsequent requests. Enables chat history continuity.
2. Agent-as-tool two-phase flows managed via API-layer message augmentation (not LLM instructions) for reliability.
3. Vector search tool added — single combined call for RFP matching, not per-role.
4. Run log streaming: MCP tools emit structured [QUERY]/[RESULT] tags, frontend shows typed badges (CYPHER/FTS/VECTOR/HANDOFF).
5. CV generation: dedicated agent with MCP tools, PDF templates marked preview-only, sectPr preserved in DOCX templates.
6. AGE query rules expanded from 13 to 19 — WITH property forwarding, 3-WITH chain, cartesian product prevention.
**Impact:** All agents, all future development.

### 2026-05-09: User directive — reference_code is pattern-only
**By:** Anil (via Copilot)
**What:** `talentiq_requirements/reference_code/` is for reference patterns only. Never import from it or point paths to it directly. Study the pattern, then copy relevant content into the actual implementation location under `talent_backend/` (or wherever the code lives). All shipped code must be self-contained.
**Why:** User request — captured for team memory

### 2026-05-09: User directive — query architecture flow
**By:** Anil (via Copilot)
**What:** User queries must flow through: UI → Backend API → AI Agent (Agent Framework) → MCP Server → Cypher/SQL queries → Data access model. The agent is the query orchestrator — it interprets NL, calls MCP tools, and the MCP server executes against PostgreSQL/AGE. The data access layer provides the query implementations that the MCP server uses.
**Why:** User request — captured for team memory

### 2026-05-09: MCP Server entry point created
**By:** Kane (Backend Dev)
**Status:** Implemented
**What:** Created `talent_backend/talent_backend/mcp_server/__main__.py` with Windows compat, argparse for transport/port/host, PGAgeHelper eager init, CORS middleware. Run: `uv run python -m talent_backend.mcp_server`
**Why:** MCP server had tools but no runnable entry point.

### 2026-05-09: React/Vite frontend scaffolded under `talent_ui/`
**By:** Dallas (Frontend Dev)
**Status:** Implemented
**What:** Full React + Vite SPA under `talent_ui/`. Faithful port of reference implementation with MSAL auth, chat interface, sidebar, run log panel, chart visualization, App Insights telemetry. Dark-theme CSS with brand accent #E8845A.
**Impact:** Run with `cd talent_ui && npm run dev`. Proxies `/af` to backend.

### 2026-05-09: Entra ID token issuer fix — accept both v1 and v2 issuers
**By:** Kane (Backend Dev)
**Status:** Implemented
**What:** Backend auth was rejecting tokens with "Invalid token issuer" because the `https://ai.azure.com/user_impersonation` scope is a v1 resource, so Azure AD issues tokens with v1 issuer format (`https://sts.windows.net/{tenant}/`) instead of v2.0 format (`https://login.microsoftonline.com/{tenant}/v2.0`). Fixed by:
- Added `_issuers()` function returning both v1 and v2 issuer URLs
- Changed JWT validation to skip built-in issuer check and validate manually against both formats
**Why:** Microsoft's token issuance uses v1 format when the resource (scope) is registered as a v1 app (like `https://ai.azure.com`). Both formats must be accepted.
**Key learning:** When using `https://ai.azure.com/user_impersonation` as the scope, tokens will always have v1 issuer format. This is a Microsoft platform behavior, not a configuration issue.

### 2026-05-09: Entra ID token audience fix — accept Foundry API scope
**By:** Kane (Backend Dev)
**Status:** Implemented
**What:** Backend auth was rejecting tokens because `AZURE_CLIENT_ID` was commented out in `app_config/.env` and the token audience (`https://ai.azure.com`) didn't match the empty string validation. Fixed by:
- Set `AZURE_CLIENT_ID=48449491-8390-4af0-8121-da7af091ad56` in `app_config/.env`
- Added `AZURE_TOKEN_AUDIENCE` config var (default: `https://ai.azure.com`)
- Backend auth now accepts both `https://ai.azure.com` (Foundry scope) and the app client ID as valid audiences
**Why:** The frontend acquires tokens with scope `https://ai.azure.com/user_impersonation`, so the token audience is `https://ai.azure.com`, not the app's client ID.

### 2026-05-09: FAQ categories expanded to cover all user stories
**By:** Dallas (Frontend Dev)
**Status:** Implemented
**What:** Expanded FAQ sidebar from 7→15 categories and 21→35 questions. New categories: Data Provenance, Resume & CV Generation, Export & Reporting, Notifications & Reminders, Tender & RFP, Candidate Management, Pre-Sales & CPQ. Each category annotated with US-xxx user story references.
**Why:** Original FAQ set only covered core search. Expanded to give users guided access to all platform capabilities.
**Impact:** All agents: FAQ list in `talent_ui/src/App.jsx` is the canonical prompt catalogue.

### 2026-05-09: Graph responses NDJSON endpoint added
**By:** Kane (Backend Dev)
**Status:** Implemented
**What:** Added `POST /af/graph/responses` to backend API. Streams NDJSON with `response_message` wrappers matching the frontend's SSE parser. Vite proxy rule: `/af` → `http://localhost:8000` (no path rewrite needed since route includes `/af`).
**Why:** Frontend run-log panel requires structured streaming events (orchestrator, agent, query, result) for real-time visibility.
**Impact:** Dallas: frontend wired to this endpoint for graph-search backend. Kane: endpoint lives in `talent_backend/talent_backend/api.py`.

### 2026-05-09: Single-terminal launcher `run_all.py`
**By:** Squad (Coordinator)
**Status:** Implemented
**What:** `run_all.py` at repo root starts all three services as child processes: MCP Server (port 3002), Backend API (port 8000), Frontend UI (port 5173). Uses `uv run --package talent_backend` for Python services, `npm run dev` for UI. Staggered startup (2s between services). Ctrl+C shuts all down cleanly.
**Why:** Eliminates need for 3 separate terminals during local dev.
**Impact:** All agents: `uv run python run_all.py` is the single command to start the full stack.

### 2026-05-09: Backend package build fix — pyproject.toml
**By:** Squad (Coordinator)
**Status:** Implemented
**What:** `talent_backend/pyproject.toml` was missing `[build-system]` and `[tool.hatch.build.targets.wheel]` sections. Without these, `uv` resolved it as a namespace package pointing to the outer directory. Fix: added hatchling build-system config with `packages = ["talent_backend"]`. Must run `uv sync --all-packages` after this change.
**Why:** `import talent_backend` was resolving to the wrong directory, causing `ModuleNotFoundError` on all sub-modules.
**Impact:** All agents: if you modify `pyproject.toml` build config, run `uv sync --all-packages` to rebuild.

### 2026-05-09: Entra ID JWT validation on backend
**By:** Kane (Backend Dev)
**Status:** Implemented
**What:** `talent_backend/talent_backend/auth.py` validates JWT signature, exp, iss, aud against Microsoft JWKS endpoint. JWKS cached 1 hour. Dev mode: if `AZURE_TENANT_ID` not set, auth bypassed with warning. `Depends(get_current_user)` applied to all endpoints except `/health`. Added `PyJWT[crypto]` and `httpx` to dependencies.
**Why:** Entra ID auth required for production; dev bypass needed for local iteration.
**Impact:** Kane/Dallas: all API calls must include `Authorization: Bearer <token>`. Dev mode auto-activates when `AZURE_TENANT_ID` is unset.

### 2026-05-09: Entra ID authentication — frontend sends Bearer tokens
**By:** Dallas (Frontend Dev)
**Status:** Implemented
**What:** All API calls from the React frontend include `Authorization: Bearer <token>` via MSAL. MSAL config: clientId `48449491-8390-4af0-8121-da7af091ad56`, tenant `150305b3-cc4b-46dd-9912-425678db1498`. Scope: `https://ai.azure.com/user_impersonation`. SPA redirect URI: `http://localhost:5173`. Config at `talent_ui/src/authConfig.js`.
**Why:** Backend validates Entra ID JWTs; frontend must acquire and attach tokens.
**Impact:** All agents: MSAL values are currently hardcoded for dev. Production will use env vars via `VITE_*` prefix.

### 2026-05-09: Frontend UI scaffolded at `talent_ui/`
**By:** Dallas (Frontend Dev)
**Status:** Implemented
**What:** Full React 18 + Vite SPA. MSAL auth, react-markdown, recharts, Application Insights telemetry. Entry: `talent_ui/src/main.jsx` → `App.jsx`. Dark theme with #E8845A accent. Start: `cd talent_ui && npm run dev` (port 5173).
**Why:** UI implementation for TalentIQ v2 chat-based search interface.
**Impact:** All agents: frontend exists at `talent_ui/`. Backend endpoints must match routes in `vite.config.js` proxy.

### 2026-05-09: Agent Framework rewrite — replacing raw OpenAI function calling
**By:** Kane (Backend Dev)
**Status:** Implemented
**What:** Rewrote `TalentAgent` to use Microsoft Agent Framework (`agent_framework` package) with `MCPStreamableHTTPTool` instead of raw OpenAI function calling with manual tool definitions. The agent now delegates all data queries to the MCP graph server rather than dispatching to the data_access layer directly.
**Why:** Aligns with the reference architecture. MCP-based tooling is the project's standard pattern — eliminates 400+ lines of manual tool schemas and dispatch code.
**Impact:** `azure-ai-projects` removed, `agent-framework>=1.3.0` added. `tools.py` reduced to just `generate_embedding()`. `MCP_ENDPOINT` config var added (default: `http://localhost:3002/mcp`). Chat endpoint unchanged.

### 2026-05-09: Chat history persistence via Azure Cosmos DB
**By:** Kane (Backend Dev)
**Status:** Implemented
**What:** Full chat history support using Azure Cosmos DB async SDK. Partition key `/session_id`, two document types (`message`, `session_meta`). User ID enforced on all ops. Graceful degradation if Cosmos unavailable. History capped at 20 messages.
**New endpoints:** `GET /sessions`, `GET /sessions/{id}`, `DELETE /sessions/{id}`. `POST /api/v1/chat` now returns `message_id`.
**Why:** Multi-turn conversation support required. Cosmos DB already exists in the Azure subscription.

### 2026-05-09: MCP Server Architecture — implemented
**By:** Parker (Data Engineer)
**Status:** Implemented
**What:** Standalone FastMCP server at `talent_backend/talent_backend/mcp_server/` (port 3002, `streamable-http` transport). 8 tools: `fetch_ontology`, `save_ontology`, `query_using_sql_cypher`, `discover_nodes`, `search_graph`, `resolve_entity_ids`, `build_query_context`, `analyze_graph_statistics`. Pre-loaded talent_graph ontology eliminates discovery round-trip. Existing data_access layer preserved for structured API endpoints.
**Dependencies:** `fastmcp`, `psycopg[binary]`, `psycopg-pool`, `starlette`. Requires `public.search_graph_nodes()` SQL function.

### 2026-05-09: Backend API & Agent architecture — implemented
**By:** Kane (Backend Dev)
**Status:** Implemented
**What:** Built complete FastAPI backend with OpenAI function-calling agent (9 tools), Entra ID JWT auth (dev-mode bypass via `TALENTIQ_AUTH_DISABLED=true`), NL chat endpoint (`/api/v1/chat`), structured search endpoints (`/api/v1/search/*`), health probes. Agent uses `DefaultAzureCredential` for Azure OpenAI auth. Lazy imports for data access layer — backend loads before Parker's layer exists. Lifespan manages DB pool + credential cleanup. 12 files across `talent_backend/talent_backend/`.
**Impact:** All agents: backend is runnable with `uvicorn talent_backend.main:app`. Parker's data access layer is imported lazily — no startup crash if missing.

### 2026-05-09: Data Access Layer — implemented
**By:** Parker (Data Engineer)
**Status:** Implemented
**What:** 8-module async data access layer at `talent_backend/talent_backend/data_access/`. Async psycopg3 pool with Entra ID token support, 10+ Pydantic v2 models, Cypher/SQL/Vector/FTS/Hybrid query functions. AGE Cypher safety via `_sanitize_identifier()`. Hybrid search normalises per-engine scores with configurable weights (0.3 graph, 0.3 vector, 0.2 FTS, 0.2 SQL).
**Impact:** Kane's API/agent layer calls these functions. All queries return typed Pydantic models. Vector search operates on 1536-dim embeddings.

### 2026-05-09: Checkpoint/resume for data loading pipeline — implemented
**By:** Brett (Data Generator & Loader)
**Status:** Implemented
**What:** Added `LoadCheckpoint` class with thread-safe batch tracking, atomic disk writes, per-phase status management. All loaders accept optional `checkpoint` parameter. Orchestrator creates checkpoint, passes to all loaders, supports `--reset` flag.
**Why:** Loading 130K employees + 2.6M edges to Azure PostgreSQL takes 7+ hours. Without checkpointing, crashes restart from scratch.

### 2026-05-09: Edge loading — Cypher MERGE → direct SQL batch INSERT
**By:** Brett (Data Generator & Loader)
**Status:** Implemented
**What:** Replaced per-row Cypher MERGE edge loading with direct SQL batch INSERT into AGE internal tables. `build_all_lookups()` queries AGE tables for ID dicts; `load_edges_direct()` uses `execute_values()` with page_size=5000. Node loading stays on Cypher MERGE. Performance: ~1 edge/sec → 10,000+ edges/sec.
**Impact:** Load pipeline uses new direct path automatically. Old Cypher method kept for backward compat but unused.

### 2026-05-09: Embeddings — sentence-transformers → Azure OpenAI ada-002
**By:** Brett (Data Generator & Loader)
**Status:** Implemented
**What:** Replaced local `all-MiniLM-L6-v2` (384-dim) with Azure OpenAI `text-embedding-ada-002` (1536-dim). Auth via `DefaultAzureCredential`. Batch size 100, 3 retries with exponential backoff. Deterministic synthetic fallback if Azure OpenAI unavailable.
**Impact:** Parker's vector search now operates on 1536-dim embeddings. Schema column already `vector(1536)`.

### 2026-05-09: Database query test strategy — implemented
**By:** Lambert (QA)
**Status:** Implemented
**What:** Live database testing (not mocks) — 7 test classes, 88 tests covering graph/FTS/vector/hybrid queries. Every test docstring references its user story ID. Coverage matrix at `docs/test-coverage-matrix.md`.
**Impact:** Tests require a running Azure PostgreSQL instance with loaded data. Session-scoped connection fixture.

### 2026-05-08T20:20: User directive — synthetic data location
**By:** Anil (via Copilot)
**What:** All synthetic data must be generated under `talent_synthetic_data/` at the repo root. Never write generated data files elsewhere.
**Why:** User request — captured for team memory

### 2026-05-08T20:10: User directive — talent_ prefix, centralized config, single root pyproject

**By:** Anil (via Copilot)  
**What:** Implementation folders must use `talent_` prefix (e.g., `talent_data_pipeline/`, `talent_backend/`). All code must load `.env` from `app_config/` — never create local `.env` files. A single `pyproject.toml` at the repo root manages all implementation folders as uv workspace members.  
**Why:** User request — captured for team memory

### 2026-05-08T19:55: User directive — uv sync only, no pip

**By:** Anil (via Copilot)  
**What:** All Python development must use `uv sync` in each code folder for dependency management. Never use `pip install` directly. Each code folder maintains its own `pyproject.toml`.  
**Why:** User request — captured for team memory

### 2026-05-08: Project restructuring — uv workspace, rename, centralized config

**By:** Brett (Data Generator & Loader)  
**Status:** Implemented  
**What:** Renamed `data_pipeline/` → `talent_data_pipeline/` (nested package layout). Updated all 15 Python imports. Aligned config.py env vars to `app_config/.env` (`PGHOST`, `PGPORT`, etc.). Created root `pyproject.toml` as uv workspace. Created `talent_backend/` skeleton for Kane. Deleted per-folder `.env.example`. `uv sync --all-packages` succeeds (47 packages).  
**Impact:**
- All agents: run `uv sync` from the repo root, not inside subfolders.
- All agents: credentials come from `app_config/.env` exclusively.
- Kane: `talent_backend/talent_backend/` is your code folder, `config.py` is ready.
- Parker: graph query code should import from `talent_data_pipeline.config` if needed.

### 2026-05-08: Data Pipeline Architecture — implemented

**By:** Brett (Data Generator & Loader)  
**Status:** Implemented  
**What:** Greenfield data pipeline under `data_pipeline/` — 18 Python files + 1 SQL + pyproject.toml. Covers 130K employees, 2.6M edges, vector embeddings, FTS indexes. Key choices: psycopg2 + ThreadedConnectionPool over asyncpg, Cypher MERGE for idempotency, DiskANN→HNSW fallback at runtime, Faker locale-per-country for culturally appropriate names, hardcoded reference data (46 locations, 96 skills, 39 certs) for ontology fidelity.  
**Impact:** Parker should use `properties->>'key'` index pattern for graph queries. Kane should use `employee_fts` and `employee_embeddings` relational tables as the search API interface.

### 2026-05-08: Requirements decomposition — fresh start

**By:** Ash (Scrum Master)  
**What:** Complete fresh requirements decomposition from source CSVs. 72 files: 1 product spec, 1 backlog, 1 traceability matrix, 17 epics, 52 user stories. 30 of 48 features.csv entries identified as gaps needing backlog grooming.  
**Why:** Clean decomposition from scratch for TalentIQ v2 platform.  
**Impact:** All team members should use `docs/` as the canonical requirements source.
