# Decisions

> Shared decision log. All agents read this before starting work.
> Only the Coordinator (via Scribe merge) writes here.

<!-- Decisions appear below, newest first. -->

### 2026-05-21: Postgres SKU/tier defaults in `talent_infra_modules/01-postgresql/` MUST mirror `talent_infra_v2/`

**By:** Bishop (Deployment Engineer) — at Anil's directive
**What:** `talent_infra_modules/01-postgresql/` postgres SKU defaults must track `talent_infra_v2/` exactly. As of 2026-05-21 the canonical pair is `skuName=Standard_D4ds_v5`, `skuTier=GeneralPurpose` (storage `32 GiB`, version `16`), sourced from `talent_infra_v2/infra/main.parameters.json` lines 86–95.
**Why:** Deploy was failing with `ServerEditionIncompatibleWithSkuSize`. Root cause: the standalone module shipped with `skuName=Standard_B2s` + `skuTier=GeneralPurpose` — an invalid pairing (B-series is **Burstable only**; D-series is GeneralPurpose; E-series is MemoryOptimized). The v2 stack avoided the bug because its `main.parameters.json` overrides the (also-broken) Bicep default with `Standard_D4ds_v5`. The standalone module had no such override.
**Files changed (3):**
- `talent_infra_modules/01-postgresql/deploy.ps1` — param-block defaults (`$SkuName`, `$SkuTier`) and the two `Get-ParameterValue -Default ...` calls now resolve to `Standard_D4ds_v5` / `GeneralPurpose`. Env-var overrides `POSTGRESQL_SKU_NAME` / `POSTGRESQL_SKU_TIER` still win.
- `talent_infra_modules/01-postgresql/infra/main.bicep` — `param skuName` default `Standard_B2s` → `Standard_D4ds_v5`; expanded `@description` to spell out the valid `tier ↔ family` pairings (Burstable=B*, GeneralPurpose=D*ds_v4/v5, MemoryOptimized=E*ds_v4/v5) so the next operator doesn't repeat the mistake.
- `talent_infra_modules/01-postgresql/infra/main.parameters.json` — `skuName` value `Standard_B2s` → `Standard_D4ds_v5`. Added `_comment_sku` field citing the v2 source-of-truth file.

**Files INTENTIONALLY NOT changed:**
- `talent_infra_modules/01-postgresql/infra/modules/postgresql-flexible-server.bicep` (still defaults to `Standard_B2s` on its own param) — `main.bicep:112-113` always passes explicit `skuName`/`skuTier` values into the module, so the submodule default is unreachable. Keeping it untouched preserves verbatim parity with `talent_infra_v2/infra/modules/postgresql-flexible-server.bicep`.
- `talent_infra_v2/` (read-only canonical source; not in scope for this fix).

**Rule going forward:** Any change to the postgres SKU+tier+storage+version in `talent_infra_v2/infra/main.parameters.json` triggers a matching update in `talent_infra_modules/01-postgresql/{deploy.ps1, infra/main.bicep, infra/main.parameters.json}`. Reviewers should flag divergence between the two paths at PR time, not at `Deployment failed` time.

**Validation:**
- `bicep build` on `talent_infra_modules/01-postgresql/infra/main.bicep` → `success=true`, 0 errors, 0 warnings.
- `[System.Management.Automation.Language.Parser]::ParseFile` (pwsh 7) on `deploy.ps1` → zero parse errors, 2455 tokens.
- SKU/tier sanity: `Standard_D4ds_v5` is D-series → `GeneralPurpose` ✓ (valid Azure Database for PostgreSQL Flexible Server pairing).
- Deploy NOT re-run (per workflow: Anil owns deploys).

### 2026-05-21: PowerShell variable naming — no case-insensitive collisions with parameters
**By:** Bishop (Deployment Engineer)
**What:** In all PowerShell scripts under `talent_infra_modules/` (and any sibling toolkit added later), a local variable inside a function MUST NOT have a name that matches a parameter of the same function under case-insensitive comparison. PowerShell treats `$secure` and `$Secure` as the same variable, so the local overwrites the parameter — corrupting typed parameters (e.g., a `[switch]` being assigned a `[SecureString]`) and producing confusing cascade type-coercion errors at the call site. Prefer suffixed local names (`$secureValue`, `$nameStr`, `$promptText`) when the natural name would collide.
**Why:** Concrete regression in `shared/common.ps1::Get-ParameterValue` where `$secure = Read-Host -AsSecureString` shadowed `[switch]$Secure`, breaking the secure-prompt path that all 5 component `deploy.ps1` scripts depend on. One-line discipline prevents an entire class of hard-to-diagnose runtime errors in shared infra helpers.

### 2026-05-21: talent_infra_modules/00-container-apps-env — standalone ACA env deployer
**By:** Bishop (Deployment Engineer)
**Status:** Implemented (recovered by Squad coordinator — Bishop spawn returned silent success; all artifacts verified on filesystem and validated)
**What:** Added new `talent_infra_modules/00-container-apps-env/` component (optional standalone deployer for the Container Apps Environment when it does not already exist). Files: `README.md`, `deploy.ps1`, `infra/main.bicep`, `infra/main.parameters.json`, `infra/modules/container-apps-environment.bicep`, `infra/modules/aca-subnet.bicep`. Cross-cutting updates: `talent_infra_modules/README.md` (added 00 to component table + prerequisites), `talent_infra_modules/DEPLOYMENT-ORDER.md` (added Step 0 — foundational, parallel-with-01-postgresql, blocks 02 + 03), `talent_infra_modules/02-backend/deploy.ps1` and `talent_infra_modules/03-frontend/deploy.ps1` (soft-fallback: when `ContainerAppsEnvName` not provided, read `../00-container-apps-env/.outputs.json`).
**Why:** ACA env was originally listed as a pre-existing prerequisite in the toolkit. Anil needed the toolkit to also be capable of standing up the ACA env on greenfield environments where it does not yet exist — without forcing operators back to the full `talent_infra_v2/` greenfield path.
**Key choices:** (1) Numbered `00` to mark it foundational and parallel-deployable with `01-postgresql` (both must precede `02-backend` / `03-frontend`). (2) Subnet handling lives in `deploy.ps1` as a pre-existing-or-create branch: validates delegation to `Microsoft.App/environments`, soft-lock awareness, CIDR membership; Bicep only receives a resolved `subnetId` (single source of truth for subnet shape). (3) Downstream components (02, 03) gained soft-fallback to read `.outputs.json` from `../00-container-apps-env/` so operators do not have to copy `ContainerAppsEnvName` between commands. (4) No data-plane operations.
**Validation (coordinator-side):** `az bicep build` against `00-container-apps-env/infra/main.bicep` → BICEP OK. PowerShell AST parser against `deploy.ps1` → PS-PARSE OK (zero syntax errors).
**Impact:** Toolkit grew to 5 components (`00-container-apps-env`, `01-postgresql`, `02-backend`, `03-frontend`, `04-data-loading`). Operators with an existing ACA env keep skipping straight to `01`; greenfield-app-tier operators now have a self-contained path through the modules toolkit.

### 2026-05-21: talent_infra_modules toolkit — APPROVED (Lambert review verdict)
**By:** Lambert (Tester)
**Status:** Approved — ship as-is
**What:** Read-only validation of `talent_infra_modules/` (4 component folders + `shared/common.ps1`) and Dallas's `talent_ui/` MSAL-bypass changes. All 6 hazards from `/memories/repo/talentiq-azd-deploy.md` covered: AGE shared_preload_libraries restart, PG Entra-admin re-PUT race (bicep passes empty `entraAdminObjectId`, control-plane CLI registers post-deploy), MCP sidecar shared UAMI with `PGUSER=<backendAppName>-identity`, AcrPull RBAC race (`dependsOn: [acrPullRole]`), no Foundry account re-PUT (only role assignment), `psql` PATH check with install hints. All 3 `main.bicep` files compile; all 5 `.ps1` files parse zero errors; cross-folder `.outputs.json` schema consistent (keys match consumer reads).
**Findings (WARN — non-blocking):** (1) `02-backend/README.md` says `mcpImage` but `.outputs.json` writes `mcpServerImage`; (2) `02-backend/README.md` mentions Docker Desktop local-build option not wired in `deploy.ps1` (no `-UseAcrTasks` switch); (3) `talent_ui/src/App.jsx` uses `eslint-disable react-hooks/rules-of-hooks` for conditional `useMsal()`/`useIsAuthenticated()` — safe because `AUTH_DISABLED` is build-time constant, but a `<AuthShell>` wrapper would be cleaner. All three are doc/style nits; none block merge.
**Impact:** Toolkit is end-to-end coherent. 01 → 02 → 03 → 04 hand off correctly. Bishop and Dallas may address WARN items in a tidy-up commit.

### 2026-05-21: talent_infra_modules/04-data-loading — orchestrator implemented
**By:** Bishop (Deployment Engineer)
**Status:** Implemented
**What:** Authored `talent_infra_modules/04-data-loading/deploy.ps1` (~510 lines, no Bicep — pure local Python invocation). Flow: read `01-postgresql/.outputs.json` (required) + `02-backend/.outputs.json` (optional) → acquire OSSRDBMS Entra token (`az account get-access-token --resource-type oss-rdbms`) → optional psql `CREATE EXTENSION` for age/vector/pg_trgm/pg_diskann + `LOAD 'age'` + `create_graph()` (wrapped in `DO ... EXCEPTION` block for idempotency) → idempotency gate (Cypher `:Employee` count, prompt unless `-Force`) → `python -m talent_data_pipeline.main` from pipeline dir → opt-in `-NarrowBackendGrants` invokes `talent_infra_v2/scripts/provision_pg_entra_roles.py` with JSON `--principals` array → opt-in `-RestartBackend` discovers active revision via `az containerapp show --query properties.latestRevisionName` and restarts → 15-label vertex count summary.
**Key choices:** (1) `-NarrowBackendGrants` opt-in — broad PG admin grant is the deliberate fallback for networks blocking 5432 (Comcast DPI etc.); auto-narrow would break deployments on every network change. (2) `psql` is hard prerequisite — bootstrap chicken-and-egg: can't use pipeline's `pg_entra.pg_connect()` for extensions step because the package import runs connectivity test presupposing extensions exist. (3) Pipeline ignores `PGHOSTADDR` (`config.py` only reads `PGHOST`) — script warns when `-PgPrivateIp` set; operator must add hosts-file entry. (4) Env-var snapshot/restore in top-level try/finally so PGPASSWORD (real bearer token) never leaks. (5) No `.outputs.json` (terminal step in the chain).
**Impact:** Closes 01 → 02 → 03 → 04 chain. `talent_data_pipeline/`, `provision_pg_entra_roles.py`, and other folders unchanged. psql becomes documented prerequisite for step 4.

### 2026-05-21: Frontend VITE_DISABLE_AUTH build-time MSAL bypass
**By:** Dallas (Frontend Dev)
**Status:** Implemented
**What:** `talent_ui/` now honors `VITE_DISABLE_AUTH=true` at Docker build time. When set: (1) `PublicClientApplication` not constructed; (2) `<App />` not wrapped in `<MsalProvider>` (`main.jsx`); (3) user treated as authenticated with synthetic `{ name: "Demo User", username: "demo@local", homeAccountId: "demo" }`; (4) `getToken()` returns `null`; outbound `fetch` omits `Authorization: Bearer …`; (5) thread-list effect fires on `isAuthenticated && AUTH_DISABLED`. When unset or any other value, MSAL flows exactly as before — production unchanged.
**Files touched:** `Dockerfile` (new `ARG`/`ENV` for `VITE_DISABLE_AUTH`, `VITE_API_BASE`, `VITE_AF_BACKEND_URL`, `VITE_AGENT_NAME`), `src/authConfig.js` (exports `msalConfig=null` when disabled; reads `VITE_MSAL_*` env), `src/main.jsx` (conditional `MsalProvider` wrap), `src/App.jsx` (module-level `AUTH_DISABLED` constant + `DEMO_ACCOUNT`; conditional `useMsal`/`useIsAuthenticated` with `eslint-disable react-hooks/rules-of-hooks` — safe because build-time inlined, DCE removes unused branch; every `!token` bail gated `&& !AUTH_DISABLED`; bearer header replaced with `AUTH_DISABLED ? {} : { Authorization: ... }`), `.env.example`.
**Contract with `03-frontend/deploy.ps1`:** build-arg name MUST be `VITE_DISABLE_AUTH`; check is literal string `"true"` (any other value leaves MSAL active); backend must also have `AZURE_TENANT_ID` unset (`02-backend/deploy.ps1` default) — without backend half, frontend sends unauthenticated requests that production-mode backend would 401.
**Impact:** Bishop — Dockerfile + frontend code match `AUTH-DISABLED.md` contract; `03-frontend/deploy.ps1` can pass `--build-arg VITE_DISABLE_AUTH=true`. Kane — no backend changes needed. Lambert — production `talent_infra_v2/` deployment unchanged (does not set this flag). Re-enabling MSAL later requires only env-var changes, no source edits.

### 2026-05-21: talent_infra_modules/02-backend — Container App + sidecar implemented
**By:** Bishop (Deployment Engineer)
**Status:** Implemented
**What:** Authored `talent_infra_modules/02-backend/`: `deploy.ps1` (orchestrator), `infra/main.bicep` (one Container App with backend port 8000 external + `mcp-server` sidecar port 3002 intra-pod, one shared UAMI, Foundry `Cognitive Services OpenAI User` role + conditional Cosmos Contributor), `infra/modules/container-app.bicep` (copied from `talent_infra_v2/` with two added outputs `identityClientId`/`identityName`), `infra/main.parameters.json` (ARM defaults), `.acrignore`.
**Key decisions:** (1) **Auth-disable contract honored** — `AZURE_TENANT_ID` is NEVER assigned on either container's env array (verified by grep; appears only in comments). `auth.py` short-circuits to dev mode without it. (2) **Single shared UAMI** — both containers inherit `AZURE_CLIENT_ID` injection from the module; `PGUSER` on both = `${backendAppName}-identity`; MCP reaches backend via `http://localhost:3002/mcp` (pod loopback). (3) **PG registration post-bicep, control plane only** — `az postgres flexible-server microsoft-entra-admin create --type ServicePrincipal --display-name <UAMI-name> --object-id <principalId>`. Display-name MUST equal UAMI name (becomes PG username). Idempotent via `ad-admin list` pre-check on `objectId`/`sid`. (4) **Same-RG constraint** for ACR/Foundry/Cosmos — `deploy.ps1` keeps the ergonomic `*ResourceGroup` params but fails fast if any differ from `ResourceGroup`, pointing operator at `talent_infra_v2/` for cross-RG support. `containerAppsEnvironmentId` passed as full ARM ID. (5) **Role-assignment names use param values** (`backendAppName`, `foundryAccountName`, `cosmosAccountName`) in `guid()`, not module outputs — avoids BCP120. (6) **AcrPull inline in container-app.bicep**, created BEFORE Container App via `dependsOn` to avoid pull-unauthorized startup race. (7) **`postgresqlPrivateFqdn` preferred when `postgresqlPrivateIp` present** in 01-postgresql outputs; falls back to public FQDN when no PE. (8) Cosmos is optional (empty `CosmosAccountName` skips both env vars and role assignment). (9) BackendAppName default is deterministic per `(SubscriptionId, ResourceGroup)` — SHA256 first 5 chars. (10) `-RestartActive` switch resolves active revision via `az containerapp revision list --query "[?properties.active].name | [0]"` and restarts (flushes MCP `Mcp-Session-Id` cache).
**Output schema:** `backendContainerAppName`, `backendContainerAppFqdn`, `backendUamiName`, `backendUamiClientId`, `backendUamiPrincipalId`, `mcpServerImage`, `backendImage`.
**Validation:** `mcp_bicep_build_bicep` success (one cosmetic `use-safe-access` warning preserved from v2 module for parity). PowerShell parse-check zero syntax errors.
**Impact:** 03-frontend reads `backendContainerAppFqdn`; 04-data-loading reads `backendUamiName`/`backendUamiPrincipalId` to narrow broad PG admin grant to schema-scoped grants. Cross-RG ACR/Foundry/Cosmos intentionally not supported in this MVP — `talent_infra_v2/` remains the cross-RG path.

### 2026-05-21: talent_infra_modules/01-postgresql — standalone deployer implemented
**By:** Bishop (Deployment Engineer)
**Status:** Implemented
**What:** Authored `talent_infra_modules/01-postgresql/`: `deploy.ps1` (orchestrator, dot-sources `../shared/common.ps1`), `infra/main.bicep`, `infra/main.parameters.json`, plus **verbatim copies** of `postgresql-flexible-server.bicep` and `private-endpoint.bicep` from `talent_infra_v2/infra/modules/` into `01-postgresql/infra/modules/`. Per the `do NOT modify the originals; this folder is self-contained` directive, modules were copied byte-for-byte. Future divergence stays local to `talent_infra_modules/`.
**Entra admin registration — control-plane only:** Bicep wiring of `postgresql-flexible-server.bicep` called with `entraAdminObjectId: ''` and `entraAdminPrincipalName: ''`; child resource `Microsoft.DBforPostgreSQL/flexibleServers/administrators` gated by `if (enableEntraAuth && !empty(entraAdminObjectId))` — empty values deliberately skip that resource. All Entra admin writes happen post-deploy: (1) `az ad signed-in-user show` → register deployer as `Type=User`; (2) parse `-UamiPrincipalIds` JSON → register each UAMI as `Type=ServicePrincipal` with `--display-name == entry.name` (UAMI resource name becomes the PG username). Both flows list existing admins first; underlying CLI is also idempotent. Eliminates the `AadAuthOperationCannotBePerformedWhenServerIsNotAccessible` re-PUT race.
**Control-flow choices:** (1) Param resolution layering via `Get-ParameterValue` for strings/`SecureString`; explicit casts for `int`/`bool` env vars. (2) Deterministic server-name fallback `tiqpg<5-hex-chars-of-sha256(subId|rg|location)>` — same RG/region → same name → bicep idempotency. (3) Client IP auto-detect via `api.ipify.org` (5s timeout); skip firewall rule on failure rather than fail deploy. (4) Belt-and-braces restart: after deploy, query `[?isConfigPendingRestart]` and restart if non-empty (without this AGE silently fails on every `cypher()` call). (5) PE private IP discovery mirrors v2 `Get-PostgresqlPrivateEndpointInfo` shape; falls back to `null` in `.outputs.json` when NIC has no IP yet. (6) Password hygiene: `ConvertFrom-SecureStringPlain` once, passed to deploy, then null'd. (7) **NO `psql` / no SQL** — `deploy.ps1` does ZERO data-plane PG ops; every privileged write through Azure control plane (ISP-blocks-5432 footgun avoided).
**Validation:** `mcp_bicep_build_bicep` against `infra/main.bicep`: 0 diagnostics. PowerShell AST parser against `deploy.ps1`: 0 parse errors (2439 tokens). `.outputs.json` schema: `postgresqlServerName`, `postgresqlServerFqdn`, `postgresqlPrivateFqdn`, `postgresqlPrivateIp`, `deployerEntraUpn`, `tenantId`.
**Impact:** 02-backend consumes `postgresqlServerFqdn` + `tenantId`. 04-data-loading consumes `deployerEntraUpn` for Entra-token connect. Strictly additive under `talent_infra_modules/01-postgresql/`.

### 2026-05-21: talent_infra_modules — per-component PowerShell deployment toolkit (architecture)
**By:** Ripley (Lead / Architect)
**Status:** Architecture locked — design accepted by Lambert (verdict above)
**What:** Created top-level `talent_infra_modules/` containing **four independent per-component PowerShell deployment scripts** for the TalentIQ app tier: `01-postgresql/` (PG flex + extensions + Entra admin + optional PE), `02-backend/` (Backend + MCP sidecar Container App + UAMI + role grants), `03-frontend/` (Webapp Container App with `VITE_DISABLE_AUTH=true` build), `04-data-loading/` (`python -m talent_data_pipeline.main` + UAMI narrow grants — no Bicep). Each folder owns `deploy.ps1` + (optionally) `infra/main.bicep` + `infra/main.parameters.json` and emits `.outputs.json` consumed by downstream folders. Shared infra in `shared/common.ps1` (dot-sourced). Toolkit **assumes most Azure infra already exists** (RG, VNet+subnets, ACA env, ACR, Foundry account+project+model deployments, optionally Cosmos) and VERIFIES via `Assert-PrerequisitesExist`, fails fast when missing. Scripts do NOT create infrastructure beyond app tier.
**Why:** (1) Existing demo environments have RG/VNet/ACA/ACR/Foundry already provisioned — forcing through `azd up` either fails or reprovisions things that didn't need to change. (2) Faster iteration loop on single component — e.g. `02-backend/` redeploys backend Container App in < 90 seconds for a tag bump. (3) Demo-mode auth simplification — no app registration churn (SPA redirect URI + admin consent + audience alignment). (4) Standalone documentation per folder.
**Constraints:** NO azd dependency (direct `az` CLI only). NO infra creation beyond app tier. All Bicep per-component (no shared root template). State is file-based (`.outputs.json`).
**Auth-disable contract (demo mode = DEFAULT):** Backend OMITS `AZURE_TENANT_ID` (auth.py lines 86-90 short-circuits to `dev-user`); Frontend uses `VITE_DISABLE_AUTH=true` Docker build arg (REQUIRES UI code change — gates `<MsalProvider>` and `useIsAuthenticated()` on flag — Dallas's responsibility, NOT in scope for `talent_infra_modules/`). NOT bypassed even in demo mode: Backend→PG (Entra), Backend→Foundry (Entra), Backend→Cosmos (Entra), ACR image pulls (Entra). Only inbound user→UI→backend HTTP path is unauthenticated.
**Deployment order:** `01-postgresql → 02-backend → 03-frontend`; `04-data-loading` can run any time after `01`. Skip patterns documented in `DEPLOYMENT-ORDER.md`.
**Boundary with `talent_infra_v2/`:** v2 = full-stack greenfield production (azd, MSAL on, JWT validated). modules = app tier only on pre-existing infra (PS scripts, MSAL off, dev-user passthrough). Both coexist in same repo; top-level `README.md` documents picking the right one.
**Files produced (architecture deliverables):** `talent_infra_modules/{README.md, AUTH-DISABLED.md, DEPLOYMENT-ORDER.md, shared/common.ps1, shared/README.md, 01-postgresql/README.md, 02-backend/README.md, 03-frontend/README.md, 04-data-loading/README.md}`. Bishop received the full contract surface.
**Impact:** Bishop (4 implementation spawns) + Dallas (UI bypass) executed against this contract. Lambert APPROVED the resulting toolkit.

### 2026-05-16: Infra rebuilt to match reference two-phase deployment pattern
**By:** Bishop (Deployment Engineer)
**Status:** Implemented
**What:** Deleted all existing `talent_infra/` files (except `.azure/`) and rebuilt the entire infrastructure following the `talentiq_requirements/reference_code/azd_deploy/` pattern exactly. Created 21 files: `azure.yaml` with hooks/outputs, `infra/main.bicep` with conditional deploy flags for two-phase deployment, 13 Bicep modules (including new Cosmos DB + Key Vault), 4 hook scripts (pre/postprovision for PS1 and bash). Key changes: two-phase deployment (provision infra first, then build+deploy containers via postprovision hook), deploy flags reset by preprovision/set by postprovision, Docker Desktop detection with ACR remote build fallback, content hashing to skip unchanged builds, PostgreSQL AGE init + data loading flag-gated.
**Why:** Anil requested alignment with the proven `talentiq_requirements/reference_code/azd_deploy/` pattern for production deployment reliability.
**Impact:** All agents — `talent_infra/` is completely new. Lambert's smoke tests should validate against these Bicep outputs. All Bicep compiles clean (1 warning: unused throughput param in serverless Cosmos).

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

