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

### 2026-05-21 — talent_infra_modules toolkit validation (Bishop + Dallas)

- **Scope:** Read-only end-to-end review of 	alent_infra_modules/ — 4 standalone per-component PowerShell deploy scripts (01-postgresql, 02-backend, 03-frontend, 04-data-loading) + 3 `main.bicep` templates + `talent_ui` `VITE_DISABLE_AUTH` MSAL bypass.
- **Verdict:** APPROVED. All 6 sub-tasks PASS, no required fixes. 3 WARN-level doc/cosmetic items.
- **Methodology that worked:**
  1. Parameter-name cross-check: extract bicep `param X` names via regex, extract `deploy.ps1` `--parameters "name=..."` keys via regex, diff the two sets. ⚠ Must filter the deploy regex to only `[a-z]` first-char identifiers (Bicep convention) or you false-positive on `VITE_*` build-arg tokens that flow through `az acr build`, not bicep. Use `-Pattern '"([a-z][A-Za-z0-9_]*)='`.
  2. PS parse check via `[System.Management.Automation.Language.Parser]::ParseFile()` is fast (<1s for 5 files) and catches braces / quoting issues before any actual deploy attempt. Cheap to add to every PS-heavy review.
  3. Bicep validation via `az bicep build --file X --outfile <tmp>`. Exit code + stderr captures both compile errors and lint warnings. Linter warnings of type `use-safe-access` in copied modules are noise — note source path, don't flag as a defect in the new code.
  4. Auth-disable contract spans 4 file types: backend bicep (omit `AZURE_TENANT_ID` env var), frontend deploy (pass `VITE_DISABLE_AUTH=true`, omit `VITE_MSAL_*`), Dockerfile (`ARG` declarations BEFORE `RUN npm run build`), and React entry (`main.jsx` skip `MsalProvider` when constant is true). Must verify all four — partial verification gives false confidence.
- **Hazard checklist (/memories/repo/talentiq-azd-deploy.md):** All 6 covered.
  - AGE preload + restart: `01-postgresql/deploy.ps1` Phase 9 polls `isConfigPendingRestart` + restarts.
  - PG admin re-PUT race: `01-postgresql/main.bicep` passes `entraAdminObjectId: ''` to the child module; deployer admin registered via control-plane CLI post-bicep.
  - MCP sidecar UAMI sharing: `02-backend/main.bicep` line 132-135 sets `PGUSER = '${backendAppName}-identity'` in the shared env block consumed by BOTH containers. Module auto-injects `AZURE_CLIENT_ID`.
  - AcrPull race: copied `container-app.bicep` modules both have `resource acrPullRole` BEFORE `resource containerApp` with explicit `dependsOn: [acrPullRole]`.
  - Foundry ETag race: N/A — bicep never re-PUTs the Foundry account, only adds the OpenAI User role assignment.
  - psql missing: `04-data-loading/deploy.ps1` Phase 2 detects + emits winget/choco install hints.
- **WARN-level findings (doc/cosmetic, ship-as-is):**
  1. `02-backend/README.md` shows example key `mcpImage` while actual `.outputs.json` writes `mcpServerImage` (script matches task spec; README is the outlier). Owner: Bishop.
  2. `02-backend/README.md` mentions optional Docker Desktop local build, but `deploy.ps1` only wires `az acr build`. Owner: Bishop.
  3. `talent_ui/src/App.jsx` uses `// eslint-disable-next-line react-hooks/rules-of-hooks` at 2 sites for `AUTH_DISABLED`-conditional `useMsal()` / `useIsAuthenticated()` calls. Safe because `AUTH_DISABLED` is a Vite *build-time* constant (only one branch ever taken at runtime) but technically a React anti-pattern. Cleaner refactor: wrap auth-aware tree in an `<AuthShell>` mounted only when `!AUTH_DISABLED`. Owner: Dallas.
- **Operational scope cuts to remember:**
  - `02-backend` and `03-frontend` fail fast on cross-RG ACR/Foundry/Cosmos (copied `container-app.bicep` only supports same-RG `existing` lookups). Documented in READMEs.
  - `04-data-loading` warns when `-PgPrivateIp` is supplied that `talent_data_pipeline` doesn't honor `PGHOSTADDR` — operator needs hosts-file override. Documented.
  - `01-postgresql/deploy.ps1` auto-detects deployer public IP via `api.ipify.org`. Anyone behind CGNAT or restrictive proxy must pass `-ClientIpAddress` explicitly.
- **Drop-box pattern used correctly:** Wrote findings to `.squad/decisions/inbox/lambert-talent-infra-modules-review.md` (not directly to `decisions.md`). Scribe will merge.
