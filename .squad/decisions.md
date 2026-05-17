# Decisions

> Shared decision log. All agents read this before starting work.
> Only the Coordinator (via Scribe merge) writes here.

<!-- Decisions appear below, newest first. -->

### 2026-05-16: Infrastructure rebuild complete
**By:** Bishop (Deployment Engineer)
**Status:** Implemented
**What:** Rebuilt all 17 `talent_infra/` files from history blueprint after prior passes were lost to disk. Full Bicep IaC validated with zero errors. Architecture unchanged — VNet, 3 Container Apps (frontend public, backend+MCP internal), Cosmos DB + PostgreSQL + Foundry + KV + ACR all with private endpoints/delegated subnets, RBAC-only auth, Entra ID-only on PostgreSQL. Ready for `azd up`.
**Why:** Files from Passes 1-3 did not survive to disk. History.md served as complete blueprint for faithful recreation.
**Impact:** All team members can now reference `talent_infra/` for infrastructure. Lambert's smoke tests should pass against the Bicep outputs unchanged.

### 2026-05-16: Role added as canonical entity to data model
**By:** Brett (Data Generator & Loader)
**Status:** Implemented
**What:** Added `Role` as a first-class graph node (17 roles with name/code/aliases) and `HAS_ROLE` as a 1:1 edge from Employee → Role. Previously, job roles were free-text strings hardcoded in multiple generators.
**Key decisions:**
1. **17 canonical roles** — Unified from three separate hardcoded lists.
2. **`role_name` field on Employee** — Added alongside existing `job_title`.
3. **`HAS_ROLE` edge is 1:1** — Each employee has exactly one role.
4. **ROLES in ENTITY_SOURCES** — Roles get FTS + vector embeddings via entity_search.
5. **AGE property indexes** — `idx_role_name` and `idx_role_code` added.
**Impact:** Kane/MCP agents can now query `MATCH (e:Employee)-[:HAS_ROLE]->(r:Role) WHERE r.code = 'PM'`. Ontology now has 15 node labels (was 14) and 13 edge types (was 12). Backward compatible — `job_title` property unchanged.

### 2026-05-16: Resolve-first query architecture — MCP tool descriptions cleaned
**By:** Kane (Backend Dev)
**Status:** Implemented
**What:** Updated all MCP tool descriptions to enforce the resolve-first query pattern. `resolve_entities` docstring says "CALL THIS FIRST". `query_using_sql_cypher` mandates `v.code = 'RESOLVED_CODE'` matching. `search_graph` narrowed to employee name lookup only. `vector_search` narrowed to resume/skills semantic matching only. Tool implementations unchanged — only descriptions/docstrings updated.
**Why:** The agent was calling wrong tools for entity lookups (search_graph, vector_search instead of resolve_entities), degrading result quality.
**Impact:** All agents using MCP tools — follow pattern: `resolve_entities → Cypher with .code = 'X'`, only vector_search for semantic resume/skills matching.

### 2026-05-16: Batch embeddings in resolve_entities — performance optimization
**By:** Kane (Backend Dev)
**Status:** Implemented
**What:** Restructured `resolve_entities` into a two-pass architecture: Pass 1 (fast, no HTTP) runs exact-code, exact-name, and FTS checks for ALL queries in a single DB cursor pass. Pass 2 (one HTTP call) batches all unresolved terms into a single Azure OpenAI embeddings API call. Previously ~28 seconds for 47 entities (sequential HTTP per term), now estimated ~3-5 seconds.
**Why:** Sequential embedding calls (~30 × 300ms) dominated resolution latency.
**Impact:** All MCP tool consumers — resolve_entities is significantly faster. Resolution priority, thresholds, and confidence scoring unchanged.

### 2026-05-16: Agent instructions rewritten — resolve-first, no hardcoded rules
**By:** Parker (Data Engineer)
**Status:** Implemented
**What:** Rewrote `TALENT_GRAPH_QUERY_GENERATION_AGENT_v1.md` to enforce clean resolve-first architecture. All hardcoded entity values removed. Instructions teach patterns, not specific values. Workflow: parse → resolve_entities → build Cypher with codes → execute → format. The `resolve_entities` tool is the sole source of truth for entity→code mapping. All 19 AGE Query Rules, RFP Multi-Role Matching Workflow, Response Format, and Graph Ontology sections preserved.
**Why:** Hardcoded entity names and regex patterns in instructions were brittle and caused mismatches.

### 2026-05-15: Entity search table and reference data enrichment
**By:** Brett (Data Generator & Loader)
**Status:** Implemented
**What:** Added `code` and `aliases` fields to all 10 reference entity types in reference_data.py. Created `entity_search` relational table for unified FTS + vector search across all reference/dimension entities. Updated SKILLS_BY_DOMAIN from `list[str]` to `list[dict]` format, updated edge_generator for compatibility, added entity_search_loader.py, wired into pipeline main.py as step 4g.
**Why:** Enables fast code-based lookups, alias resolution, and unified entity search across all reference data types.
**Impact:** Breaking change to SKILLS_BY_DOMAIN API (str→dict); all consumers updated. Entity search table schema added with GIN + B-tree indexes.

### 2026-05-15: Per-question pipeline logging
**By:** Kane (Backend Dev)
**Status:** Implemented
**What:** Added `PipelineLogger` — per-question trace logger capturing the full request pipeline (triage, handoffs, MCP tool calls, queries, errors, final response) and writing structured logs to disk. Folder structure: `query_logs/{timestamp}_{session_short}_{question_hash}/`. Toggle: `ENABLE_PIPELINE_LOGGING=true`. Non-blocking flush via thread pool. PII sanitization (email masking). Hooked into both `POST /api/chat` (SSE) and `POST /af/graph/responses` (NDJSON).
**Why:** Enables detailed per-question debugging and analysis without impacting response streaming.
**Impact:** Lambert — new module needs tests. Dallas — no impact, backend-only.

### 2026-05-15: resolve_entities MCP tool — entity resolution via entity_search table
**By:** Kane (Backend Dev)
**Status:** Implemented
**What:** Added `resolve_entities` MCP tool. Resolves user-supplied terms to canonical entity names and codes from the `entity_search` PostgreSQL table. Resolution cascade: exact code match (1.0) → exact name match (1.0) → FTS via plainto_tsquery → alias substring ILIKE (0.7) → not found (0.0). Shared pool, entity type whitelist, graceful degradation if table missing, all queries parameterized.
**Why:** Enables fuzzy-to-canonical entity resolution before building Cypher queries, improving accuracy.
**Impact:** Agent orchestration can now resolve fuzzy user input to canonical entities before Cypher.

### 2026-05-15: Agent instructions updated for entity resolution workflow
**By:** Parker (Data Engineer)
**Status:** Implemented
**What:** Updated `TALENT_GRAPH_QUERY_GENERATION_AGENT_v1.md` to integrate `resolve_entities` MCP tool. Entity resolution required before Cypher for all canonical entity references. Code-based matching (`entity.code = 'RESOLVED_CODE'`) instead of regex. Three-tier classification: enum values (direct), free text (regex/vector), canonical entities (resolve first). Batch resolution for all entities in single call.
**Why:** Code-based matching is faster (index hit) and deterministic vs regex approximation.
**Impact:** All agents using Talent Graph Query Agent instructions.

### 2026-05-15: Chat history thread management — backend endpoints
**By:** Kane (Backend Dev)
**Status:** Implemented

**What:**
Added thread management endpoints that the frontend (App.jsx) is already calling:
- `GET /api/threads?limit=20` — list user's threads
- `GET /api/threads/{id}` — get thread messages
- `DELETE /api/threads/{id}` — soft delete thread
- `PATCH /api/threads/{id}` — rename thread (body: `{"title": "..."}`)

**Key decisions:**
1. **session_meta co-located with messages** — The `session_meta` document lives in the same Cosmos container and partition as messages (keyed by `session_id`). A `type` field (`session_meta` vs `message`) distinguishes them. Avoids a second container; single-partition reads stay fast.
2. **Ownership = 404** — Wrong user gets 404 (not 403) to avoid leaking thread IDs.
3. **Soft delete** — `DELETE /api/threads/{id}` sets `is_deleted=true` on the meta doc. Messages retained for future retention/export features.
4. **Cross-partition query for list_threads** — `list_threads()` uses `enable_cross_partition_query=True` since user_id spans partitions. Acceptable for a user's thread list (low cardinality, limited to 20 results).
5. **Legacy endpoints preserved** — `/api/sessions/*` endpoints still exist alongside new `/api/threads/*` endpoints. Frontend should migrate to threads.
6. **CORS updated** — `allow_methods` now includes `DELETE` and `PATCH`.

**Impact:** Dallas (Frontend) — The four endpoints the frontend is already calling now exist. No frontend changes needed. Lambert (Tester) — 16 tests written and passing.

### 2026-05-12T21:40:00Z: HARD RULE — Reference code patterns are authoritative
**By:** Anil Dwarakanath (via Copilot Coordinator)
**Status:** Documented

**What:** The patterns in `talentiq_requirements/reference_code/` (and the mirror at `C:\repos\TalentIQFoundry\af-backend`) are the canonical implementation reference. When implementing or fixing any feature that has a corresponding pattern in `reference_code/` (Azure OpenAI / Foundry client construction, MCP client, telemetry, Cosmos service, AGE/MCP server, etc.), agents MUST replicate the reference pattern as-is — same env var names, same precedence order, same audience scopes, same client class, same constructor kwargs.

**Specifically:** Azure OpenAI client uses `AZURE_OPENAI_ENDPOINT` (Cognitive Services route, `*.openai.azure.com`), NOT the Foundry project URL. Do not invent new env var names, alternative audiences, or wrapper token providers when the reference pattern already works.

**Enforcement:** Before any agent writes or modifies Foundry/OpenAI/MCP/Cosmos/telemetry client code, they must first read the corresponding file in `talentiq_requirements/reference_code/` and mirror it. Deviations require explicit user approval.

**Why:** Divergence from the reference code caused Foundry client 401 audience mismatch and Cosmos endpoint precedence inversion. Reference code is battle-tested.

**Note:** Supersedes and strengthens the earlier "2026-05-09: User directive — reference_code is pattern-only" entry.

### 2026-05-12T03:00:00Z: VNet-aware smoke suite — Mechanism A/B/C strategy
**By:** Lambert (Tester)
**Status:** Implemented

**What:**
Refactored `tests/deployment/` smoke suite so every test that touches a private
resource runs INSIDE the VNet.  The laptop is not on the VNet — direct Postgres /
Cosmos / Foundry / KV connections from the laptop would time out.

**Three mechanisms (A + B cover everything, C not needed):**

| Mechanism | Description | Used by |
|-----------|-------------|---------|
| **A — Container App exec** | `az containerapp exec` runs a probe module (`talent_backend.probes.*`) inside a running CA.  The CA is on-VNet with its UAMI. | test_02 (Postgres), test_03 (Foundry), test_04 (MCP→PG) |
| **B — Control plane CLI** | `az` commands against ARM (public API, works from anywhere) | test_01 (Entra/UAMI), test_03 (CA status), test_04 (CA status, PG Entra admin), test_05 (CA status) |
| **C — Dedicated probe CA** | NOT USED.  A + B cover all checks.  Documented as fallback. | — |

**Probe modules added** (`talent_backend/talent_backend/probes/`):
- `smoke_pg.py` — Postgres connect, extensions, AGE graph, Cypher count, vector top-K, FTS
- `smoke_foundry.py` — Foundry gpt-5.4 chat completion via UAMI
- `smoke_mcp_pg.py` — MCP→Postgres connect, AGE, Cypher count

**Why probes-in-the-app (not inline `python -c`):**
- Inline strings are quoting nightmares across PowerShell/bash
- Probes are versioned with the app code (release-correct)
- Reusable by future health endpoints (`/health/pg`, `/health/foundry`)
- Debuggable: `az containerapp exec --command "python -m talent_backend.probes.smoke_pg"`

**Bicep output mapping fixed:**
- Old: `BACKEND_CONTAINER_APP_NAME` / `MCP_CONTAINER_APP_NAME` / `FRONTEND_CONTAINER_APP_NAME`
- New: `AZURE_CONTAINER_APP_BACKEND_NAME` / `AZURE_CONTAINER_APP_MCP_NAME` / `AZURE_CONTAINER_APP_FRONTEND_NAME` (matches actual main.bicep outputs)
- Convention fallback retained for backward compat.

**MCP UAMI Entra admin check (test_04):**
Switched from `SELECT rolname FROM pg_roles` (requires VNet) to
`az postgres flexible-server ad-admin list` (Mechanism B, works from laptop).
Uses `POSTGRES_FQDN` to derive server name.

**Impact:** All agents — Container App name env vars are now tested via the
Bicep output names.  Probes are a new package in the backend image — no Docker
image change needed (they ship with the existing `talent_backend` wheel).

**Open items / follow-on for Bishop:**
None critical.  All required Bicep outputs already exist: `AZURE_CONTAINER_APP_BACKEND_NAME`,
`AZURE_CONTAINER_APP_MCP_NAME`, `AZURE_CONTAINER_APP_FRONTEND_NAME`, `POSTGRES_FQDN`.

### 2026-05-12T02:30:00Z: Deployment smoke test suite — contracts and strategy
**By:** Lambert (Tester)
**Status:** Implemented

**What:**
Created `tests/deployment/` — an ordered, fail-fast smoke test suite that gates go/no-go after `azd up`.

**Test order (earlier failures block later tests):**
1. Entra auth (DefaultAzureCredential token, principal ID match, 3 UAMIs exist)
2. PostgreSQL (connect via Brett's `db.connect()`, extensions, AGE graph, Cypher count, vector search, FTS)
3. Backend Container App (running status, Foundry gpt-5.4 chat completion)
4. MCP Container App (running status, UAMI in pg_roles)
5. Frontend Container App (running status, SPA served, `/af/health` proxy to backend)

**Infra contracts the tests assume (env var names from Bishop's Pass 3):**
- `AZURE_ENV_NAME`, `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP` — from `azd env`
- `PGHOST`/`POSTGRES_HOST`, `PGDATABASE`/`POSTGRES_DB`, `PGUSER`/`POSTGRES_USER` — PG connection
- `FOUNDRY_ENDPOINT`, `FOUNDRY_DEPLOYMENT_NAME` — Foundry model
- `AZURE_PRINCIPAL_ID` (optional) — deploying user OID sanity check
- Container App names default to `ca-talentiq-{backend|frontend|mcp}-{env}` — overridable via `BACKEND_CONTAINER_APP_NAME`, `MCP_CONTAINER_APP_NAME`, `FRONTEND_CONTAINER_APP_NAME`
- UAMI names: `uami-talentiq-{backend|frontend|mcp}-{env}`

**Design choice — no `az containerapp exec`:**
Container exec requires TTY + running replica + VNet access. Instead: `az containerapp show` for status, deployer-credential Foundry check for AI connectivity. Cypher/vector/FTS validated via Brett's `db.connect()` (same path the pipeline uses). Documents the future requirement for a `/health/foundry` backend endpoint.

**Why:** Deployment verification must be deterministic, fast, and require zero manual inspection. Fail-fast ensures the first broken layer is immediately visible.

**Impact:** All agents — Container App names, UAMI names, and azd env var names are now tested contracts. Changing them requires updating the smoke suite (or the overridable env vars).

### 2026-05-12T01:35:00Z: Frontend runtime config strategy
**By:** Dallas (Frontend Dev)
**What:** Runtime configuration for the talent_ui production container image uses a `window.__ENV__` pattern injected at container start, not baked at build time.

#### Decision

The Vite SPA is built once (static `dist/`) and shipped in a multi-stage Docker image. Runtime environment values (backend URL, MSAL client ID, App Insights connection string) vary per deployment target and cannot be baked into the Vite bundle with `VITE_*` vars.

**Pattern chosen:** `envsubst` templating at container start.

1. `config.js.template` lives at `/etc/talentiq/config.js.template` inside the image (outside the nginx `root`, so never served raw).
2. `entrypoint.sh` runs `envsubst '${BACKEND_URL} ${AZURE_CLIENT_ID} ${APPLICATIONINSIGHTS_CONNECTION_STRING}'` to write `/usr/share/nginx/html/config.js`.
3. `index.html` loads `/config.js` via a plain `<script src="/config.js">` **before** the main ESM bundle, so `window.__ENV__` is set before any React code executes.

Container App injects: `BACKEND_URL`, `KEY_VAULT_URI`, `APPLICATIONINSIGHTS_CONNECTION_STRING`, `AZURE_CLIENT_ID`.

#### Caveats / Follow-on work

- `telemetry.js` currently reads `import.meta.env.VITE_APPINSIGHTS_CONNECTION_STRING` (baked at build). Future pass: change to `window.__ENV__.APPLICATIONINSIGHTS_CONNECTION_STRING`.
- `authConfig.js` has hardcoded clientId and tenantId. Future pass: change to read from `window.__ENV__.AZURE_CLIENT_ID` (tenantId can come from MSAL authority metadata or a separate env var).
- The `/config.js` endpoint will return a 404 in local Vite dev mode (no nginx, no entrypoint.sh). Wrap reads with `window.__ENV__ ?? {}` in source to degrade gracefully.

#### Nginx proxy path

Proxied prefix is `/af/` (not `/api/`). The frontend codebase routes all backend calls under `/af/`. The task spec mentioned `/api/*` — this was not applied to avoid breaking existing API calls.
**Why:** `proxy_buffering off` + `proxy_read_timeout 300s` on the `/af/` location ensures NDJSON SSE streaming (run-log panel) is not buffered or prematurely closed by nginx.

### 2026-05-12T01:30:00Z: Passwordless auth pattern — azure_clients.py
**By:** Kane (Backend Dev)
**Status:** Implemented

**What:**
- Created `talent_backend/talent_backend/azure_clients.py` as the single source of truth for all Azure service connections.
- `get_credential()` — process-wide `DefaultAzureCredential` singleton with pre-warm. In Azure: `AZURE_CLIENT_ID` env var auto-selects the UAMI. Locally: falls back to `az login`.
- `PostgresPoolManager` — async psycopg3 pool with Entra token-as-password refresh. Gets token from scope `https://ossrdbms-aad.database.windows.net/.default`. Recreates the pool 5 minutes before token expiry (~1h TTL). Thread-safe with asyncio.Lock.
- `get_cosmos_client()` — singleton `CosmosClient` with `DefaultAzureCredential`. RBAC-only (no key).
- `get_keyvault_client()` / `get_secret()` — lazy `SecretClient` with `DefaultAzureCredential`.
- `configure_app_insights()` — idempotent OTel setup via `azure-monitor-opentelemetry`. No-op if `APPLICATIONINSIGHTS_CONNECTION_STRING` unset.
- `get_foundry_token_provider()` — returns a bearer-token callable for `AzureOpenAI(azure_ad_token_provider=...)`.

**Why:** Centralizes credential management. Eliminates duplicate `DefaultAzureCredential()` instantiations (pre-existing in vector_tools.py, chat_history.py). Enables token rotation without changing callers.

**Impact:**
- `pg_age_helper.py` — delegates to `PostgresPoolManager` when `IS_AZURE_DEPLOY`. Local dev path unchanged.
- `chat_history.py` — uses `get_cosmos_client()` instead of its own `CosmosClient(credential=DefaultAzureCredential())`.
- `vector_tools.py` — uses `get_credential()` singleton instead of creating a new `DefaultAzureCredential()`.
- `api.py` lifespan + `mcp_server/__main__.py` — call `configure_app_insights()` at startup.

### 2026-05-12T01:30:00Z: Dockerfile strategy — backend + MCP
**By:** Kane (Backend Dev)
**Status:** Implemented

**What:**
- `talent_backend/Dockerfile` — backend service (port 8000, `python -m talent_backend`).
- `talent_backend/Dockerfile.mcp` — MCP service (port 3002, `python -m talent_backend.mcp_server`).
- Both use multi-stage build: `python:3.11-slim` builder + runtime, uv-based install.
- Build pattern: `uv venv /opt/venv && . /opt/venv/bin/activate && uv pip install --no-cache .` using pyproject.toml as the manifest.
- Non-root `app` user in runtime stage.
- `talent_backend/.dockerignore` excludes .venv, __pycache__, *.env, tests, logs, docs.
- HEALTHCHECK left as TODO comment — needs curl/wget in image or Python urllib check against `/health`.

**Why:**
- azure.yaml `project: ../talent_backend` for both backend and mcp services → build context is `talent_backend/`. Both Dockerfiles live there.
- `uv pip install .` (not `uv sync`) avoids needing the workspace-root `uv.lock` inside the `talent_backend/` build context.

**Outstanding action for Bishop/infra:**
- `talent_infra/azure.yaml` mcp service needs `docker.dockerfile: Dockerfile.mcp` added so azd uses the correct Dockerfile for the MCP Container App. Without it, azd defaults to `Dockerfile` and starts the backend entrypoint for both services.

### 2026-05-12T01:30:00Z: azure_clients module — shape and import contract
**By:** Kane (Backend Dev)
**Status:** Implemented

**What:**
- Module: `talent_backend/talent_backend/azure_clients.py`
- Public API:
  - `get_credential()` → `DefaultAzureCredential` singleton
  - `get_pg_pool_manager()` → `PostgresPoolManager` singleton (Azure Postgres token rotation)
  - `get_cosmos_client()` → `CosmosClient` singleton
  - `get_keyvault_client()` → `SecretClient` singleton (lazy)
  - `get_secret(name)` → `str` (on-demand Key Vault read)
  - `configure_app_insights()` → void (OTel setup, idempotent)
  - `get_foundry_token_provider()` → `Callable[[], str]` (for AzureOpenAI SDK)
- `IS_AZURE_DEPLOY` in `config.py`: `True` when `AZURE_CLIENT_ID` + `POSTGRES_HOST` env vars are both present.
- `config.py` env var aliases: `FOUNDRY_ENDPOINT` → `AZURE_OPENAI_ENDPOINT`, `COSMOS_ENDPOINT` → `COSMOS_CHAT_ENDPOINT`, `POSTGRES_HOST` → `PGHOST`, etc. All old names still work for local dev.
- No passwords are logged or committed. Token values are ephemeral (only in conninfo strings, never stored).

**Why:** Single place for Azure credential lifecycle. Prevents duplicate `DefaultAzureCredential` instantiations and redundant IMDS probe races.

**Import pattern for all new code:**
```python
from talent_backend.azure_clients import get_credential, get_cosmos_client, get_keyvault_client, configure_app_insights, get_foundry_token_provider
```

### 2026-05-12T01:30:00Z: Data pipeline Entra ID token auth for Azure PostgreSQL
**By:** Brett (Data Generator & Loader)
**Status:** Implemented

**What:**
1. Created `talent_data_pipeline/talent_data_pipeline/db.py` — centralized connection helper with dual-mode auth (password vs Entra ID token). Auto-detects Azure target via `IS_AZURE_DEPLOY=true` or `PGHOST` suffix `.postgres.database.azure.com`.
2. Token caching: Entra access tokens cached in-process with thread-safe refresh 5 minutes before expiry. `DefaultAzureCredential` is only imported when Entra mode is active (zero overhead for local dev).
3. `ManagedConnectionPool` wrapper: rebuilds the `ThreadedConnectionPool` when the underlying token nears expiry, ensuring fresh connections get valid tokens during long parallel loads.
4. Refactored all 6 connection call sites (connectivity_test, validate, create_relational_tables, create_indexes, base_loader) to use `db.connect()` or `ManagedConnectionPool` instead of raw `psycopg2.connect(**db_config.connection_dict)`.
5. Connectivity test now prints auth mode ("Entra ID (passwordless)" or "Password") at the top of its output.
6. Both outer stub files and inner package files updated and kept in sync.
7. `AZURE.md` added with 30-line usage note.

**Why:** Bishop's infra Pass 3 provisions PostgreSQL in Entra-only mode (no password auth). Pipeline must use Entra tokens against Azure PG while preserving local password-based dev flow.

**Impact:** All pipeline operations (connectivity test, schema creation, index creation, data loading, validation) now work against both local PG (password) and Azure PG (Entra token). No changes to `talent_backend/`, `talent_infra/`, or `talent_ui/`.

### 2026-05-12T01:00:00Z: Container App workloads + UAMI + RBAC wiring (Pass 3)
**By:** Bishop (Deployment Engineer)
**Status:** Implemented

**What:**
1. **User-Assigned Managed Identities** — 3 UAMIs created per environment: `uami-talentiq-backend-{env}`, `uami-talentiq-frontend-{env}`, `uami-talentiq-mcp-{env}`. Created before Container Apps so RBAC assignments propagate before app startup.

2. **RBAC assignments wired into existing data modules:**
   - Cosmos DB: Built-in Data Contributor (`00000000-0000-0000-0000-000000000002`) → backend + MCP UAMIs
   - Foundry: Cognitive Services OpenAI User (`5e0bd9bd-7b93-4f28-af87-19fc36ad61bd`) → backend + MCP UAMIs
   - Key Vault: Key Vault Secrets User (`4633458b-17de-408a-b874-0445c86b69e6`) → all 3 UAMIs
   - ACR: AcrPull (`7f951dda-4ed3-4680-a7ca-43fe172d538d`) → all 3 UAMIs
   - PostgreSQL: Entra Admin (server-level) → backend UAMI + MCP UAMI + deploying user (principalType: 'User')

3. **Container App module** — Generic `container-app.bicep` used 3 times. UAMI-only identity, ACR pull via UAMI, configurable external/internal ingress, env vars with KV secret reference support, bootstrap image `mcr.microsoft.com/k8se/quickstart:latest`.

4. **Env var contract:**
   - Backend (8000) & MCP (3002): POSTGRES_HOST, POSTGRES_DB, COSMOS_ENDPOINT, FOUNDRY_ENDPOINT, FOUNDRY_DEPLOYMENT_NAME, KEY_VAULT_URI, APPLICATIONINSIGHTS_CONNECTION_STRING, AZURE_CLIENT_ID
   - Frontend (80): BACKEND_URL, KEY_VAULT_URI, APPLICATIONINSIGHTS_CONNECTION_STRING, AZURE_CLIENT_ID
   - Apps use `DefaultAzureCredential` with `AZURE_CLIENT_ID` set to UAMI clientId — NO passwords.

5. **azure.yaml** — `resourceName` activated for all 3 services. Dockerfiles marked TODO (not in Bishop's scope).

**Why:** Pass 3 completes the infrastructure stack. `azd up` now provisions the entire topology: networking + data + supporting services + container apps. Apps start with quickstart placeholder; `azd deploy` builds + pushes real images.

**Impact:** All agents — env var names above are the contract between infra and app code. Kane/Dallas/Brett must implement `DefaultAzureCredential` in backend, frontend, and MCP using `AZURE_CLIENT_ID` for identity selection. Dockerfiles are the remaining blocker before a full `azd up && azd deploy` cycle works end to end.

### 2026-05-12T00:00:00Z: Data + supporting service modules deployed
**By:** Bishop (Deployment Engineer)
**Status:** Implemented

**What:**
1. **Cosmos DB** — SQL API, `publicNetworkAccess: 'Disabled'`, `disableLocalAuth: true` (RBAC-only via Cosmos SQL role assignments, not Azure RBAC). Built-in Data Contributor role `00000000-0000-0000-0000-000000000002`. Default database `talentiq` with `sessions` container (autoscale 1000 RU/s, partition key `/sessionId`).

2. **PostgreSQL Flexible Server** — PG 16, VNet-integrated via delegated subnet `snet-db` (NOT private endpoint). Entra ID-only auth (`passwordAuth: 'Disabled'`, `activeDirectoryAuth: 'Enabled'`). Extensions allowlisted: `age`, `vector`, `pg_trgm`, `pg_stat_statements`. Burstable B2ms SKU for dev. `entraAdmins` array param for server-level Entra admins (empty by default — wire MIs in Container Apps pass).

3. **Azure AI Foundry** — Cognitive Services account kind `AIServices`, system-assigned MI, `publicNetworkAccess: 'Disabled'`, `disableLocalAuth: true`. Single PE with dual DNS zones (cognitive + openai). `gpt-5.4` model deployment (GlobalStandard, 30K TPM default). `principalIds` array for Cognitive Services OpenAI User role.

4. **App Insights** — Log Analytics workspace + workspace-based Application Insights. Workspace shared key passed to Container Apps Environment via module output with `#disable-next-line outputs-should-not-contain-secrets` (no secrets in files, deployment-time only).

5. **Key Vault** — RBAC authorization mode, soft-delete + purge protection, `publicNetworkAccess: 'disabled'`. Name truncated to 24 chars via `take()`. `principalIds` for Key Vault Secrets User role.

6. **ACR** — Premium SKU, `adminUserEnabled: false`, `publicNetworkAccess: 'Disabled'`. Alphanumeric name (no hyphens). `principalIds` for AcrPull role.

**All modules:** Private endpoints (or VNet integration for PG) + private DNS zone linking. All `principalIds` arrays empty — wired when Container App MIs land.

**Why:** Pass 2 of the infra build-out. Networking foundation (Pass 1) is in place; data + supporting services now deployed. Container App workloads are next (Pass 3).

**Impact:** All agents — Bicep template is now a complete infrastructure-minus-apps deployment. `azd up` will provision networking + all PaaS services. Container App modules + MI RBAC wiring are the remaining gap.

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
