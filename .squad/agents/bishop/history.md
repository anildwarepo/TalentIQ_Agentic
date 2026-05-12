# Bishop — History

## Project Context
- **Project:** TalentIQ — Talent Matching/Searching platform
- **Owner:** Anil
- **Stack:** React Vite (frontend), Python (backend, Agent Framework, MCP servers), PostgreSQL + Apache AGE + DiskANN + FTS, Cosmos DB, Azure AI Foundry (`gpt-5.4`)
- **My role:** Deployment Engineer — own Azure infra (Bicep), `azd` config, VNet, private endpoints, Entra ID + MI auth, and end-to-end `azd up` deployment

## Target Topology
- VNet with subnets: `containerapps-env`, `private-endpoints`, optionally `postgres-delegated`
- Container Apps Environment (internal, VNet-integrated)
  - **backend** — internal ingress only
  - **frontend** — external ingress, talks to backend over internal DNS
  - **mcp-server** — internal ingress only
- Cosmos DB — private endpoint + RBAC (backend MI, mcp MI)
- PostgreSQL Flexible Server — AGE + DiskANN + pg_trgm/tsvector, private endpoint, Entra ID auth, MI roles
- Azure AI Foundry — `gpt-5.4` deployment, private endpoint, MI access
- Application Insights — wired to all three Container Apps
- Key Vault — secrets via MI (no passwords)
- Private DNS zones for: cosmos, postgres, foundry, key vault, ACR

## Key References
- `talentiq_requirements/azd_deploy/` — prior azd patterns
- `talentiq_requirements/foundy-managed-vnet-setup/` — Foundry managed VNet reference (Bicep, azure.yaml)
- `docs/specs/vnet-integration.md`, `authentication.md`, `backend-architecture.md`, `database-architecture.md`, `mcp-server-tools.md`, `telemetry.md`
- Skills: `azure-postgres` (passwordless PG), `microsoft-foundry` (Foundry deploy/RBAC)

## Work Log

### 2026-05-12: Pass 1 — Networking Foundation Scaffold

**Files created:**
- `talent_infra/azure.yaml` — azd project config, three services (backend, frontend, mcp) with placeholder Container App resource names
- `talent_infra/main.bicep` — top-level orchestrator wiring vnet + ACA env + private DNS; commented stubs for cosmos, postgres, foundry, app-insights, key-vault, ACR, and per-service Container App modules
- `talent_infra/main.parameters.json` — environment-driven params (location, environmentName, principalId)
- `talent_infra/modules/vnet.bicep` — VNet 10.0.0.0/16 with three subnets (snet-aca /23, snet-pe /24, snet-db /24), NSGs per subnet, delegations for ACA and PostgreSQL
- `talent_infra/modules/container-app-env.bicep` — Consumption workload-profile CAE, VNet-integrated, `internal: false` (frontend gets public ingress, backend/MCP internal only)
- `talent_infra/modules/private-dns.bicep` — six private DNS zones (cosmos, postgres, cognitive, openai, keyvault, ACR) linked to VNet
- `talent_infra/README.md` — architecture decisions, naming convention, pending work checklist

**Design decisions:**
1. Single CAE with `internal: false` — avoids Application Gateway; per-app ingress handles mixed access
2. VNet CIDR 10.0.0.0/16 aligned with `docs/specs/vnet-integration.md` diagram
3. PostgreSQL gets delegated subnet (snet-db) per team decision 2026-05-10
4. Naming: `{abbreviation}-talentiq-{env}-{resourceToken}` where resourceToken = uniqueString(sub, rg, location)
5. All Bicep validated via `mcp_bicep_build_bicep` — zero diagnostics

**What's next (later passes):**
- ~~Cosmos DB module + PE + RBAC~~ ✅
- ~~PostgreSQL module + Entra ID passwordless (use `azure-postgres` skill)~~ ✅
- ~~Azure AI Foundry module + PE + MI (use `microsoft-foundry` skill)~~ ✅
- ~~App Insights + Log Analytics → wire into CAE~~ ✅
- ~~Key Vault + PE~~ ✅
- ~~ACR + PE~~ ✅
- Individual Container App modules (backend, frontend, MCP) with managed identities
- Role assignments (data-plane RBAC for each MI)

### 2026-05-12: Pass 2 — Data + Supporting Service Modules

**Files created:**
- `talent_infra/modules/cosmos.bicep` — Cosmos DB SQL API, PE, RBAC-only (`disableLocalAuth: true`), default `talentiq/sessions` container with autoscale 1000 RU/s
- `talent_infra/modules/postgres.bicep` — PG 16 Flex Server, delegated subnet VNet integration, Entra ID-only auth (`passwordAuth: 'Disabled'`), extensions allowlisted: `age,vector,pg_trgm,pg_stat_statements`
- `talent_infra/modules/foundry.bicep` — AI Services account (kind: AIServices), gpt-5.4 model deployment, PE with dual DNS (cognitive + openai), `disableLocalAuth: true`
- `talent_infra/modules/app-insights.bicep` — Log Analytics workspace + workspace-based App Insights
- `talent_infra/modules/key-vault.bicep` — RBAC auth, PE, soft-delete + purge protection, name truncated to 24 chars
- `talent_infra/modules/acr.bicep` — Premium SKU, PE, `adminUserEnabled: false`, alphanumeric name

**Files modified:**
- `talent_infra/main.bicep` — replaced all 6 placeholder stubs with real module references, added `foundryModelName`/`foundryModelCapacity` params, wired App Insights → CAE Log Analytics, added 11 new outputs
- `talent_infra/modules/container-app-env.bicep` — replaced `logAnalyticsWorkspaceId` param with `logAnalyticsCustomerId` + `@secure() logAnalyticsSharedKey`, wired into `appLogsConfiguration`

**Design decisions:**
1. PostgreSQL uses delegated subnet (snet-db), NOT private endpoint — native VNet integration per architecture decision 2026-05-10
2. PostgreSQL Entra ID-only auth — `passwordAuth: 'Disabled'`, `activeDirectoryAuth: 'Enabled'`. No SQL admin password. Entra admins added via child resources. Server deploys but is inaccessible until at least one admin is provided (fine for infra-only pass)
3. Extensions allowlisted: `age` (graph), `vector` (pgvector/DiskANN), `pg_trgm` (fuzzy text), `pg_stat_statements` (query perf) — aligns with `docs/specs/database-architecture.md`
4. Cosmos DB uses its own SQL RBAC system (not Azure RBAC) for data plane — built-in Data Contributor role `00000000-0000-0000-0000-000000000002`
5. Foundry PE linked to both `privatelink.cognitiveservices.azure.com` AND `privatelink.openai.azure.com` DNS zones — single PE, dual DNS config
6. Foundry `disableLocalAuth: true` — MI/RBAC only, pattern adapted from `talentiq_requirements/foundy-managed-vnet-setup/`
7. Key Vault name truncated via `take(..., 24)` to respect 3-24 char limit
8. ACR name uses alphanumeric-only format (`crtalentiq{env}{token}`) since ACR doesn't allow hyphens
9. Log Analytics shared key passed to CAE via `#disable-next-line outputs-should-not-contain-secrets` module output — no secrets stored in files, resolved at deployment time only
10. All `principalIds` arrays left empty — Container App managed identities are wired in the next pass

**Skills applied:**
- `azure-postgres`: Entra ID-only auth, delegated subnet VNet integration, `pgaadauth` admin pattern
- `microsoft-foundry`: AIServices kind, SystemAssigned MI, `publicNetworkAccess: 'Disabled'`, `disableLocalAuth: true`
- `mcp_bicep_get_bicep_best_practices`: User-defined types for entraAdmins, `string[]` instead of `array`, `parent` instead of `/` names, no `name` on module statements

**Bicep build validation:** `mcp_bicep_build_bicep` on main.bicep — PASSED (zero errors, one warning: `principalId` unused — reserved for Container Apps pass)

**What's next (Pass 3):**
- Container App modules: backend, frontend, MCP — each with system-assigned managed identity
- Wire MI principal IDs into `principalIds` arrays: Cosmos (backend+MCP), Foundry (backend+MCP), KV (all three), ACR (all three)
- Add Entra admin for backend+MCP MIs on PostgreSQL
- Wire environment variables into each Container App (connection strings, endpoints from main.bicep outputs)
- Update `azure.yaml` with `resourceName` references
- Role assignments (data-plane RBAC for each MI)

### 2026-05-12: Pass 3 — Container App Workloads, UAMI, RBAC Wiring

**Files created:**
- `talent_infra/modules/managed-identity.bicep` — UAMI factory (name, location, tags → id, principalId, clientId, name)
- `talent_infra/modules/container-app.bicep` — Generic Container App module (UAMI identity, ACR pull, configurable ingress external/internal, env vars, KV-backed secrets array, quickstart bootstrap image)
- `talent_infra/modules/rbac.bicep` — Generic RBAC role assignment helper (resource-group or resource-scoped, guid() deterministic names)

**Files modified:**
- `talent_infra/main.bicep` — Full wiring: 3 UAMIs, principalIds into all data modules, entraAdmins for Postgres (backend+MCP+deployer), 3 Container App instances with env vars, 13 new outputs
- `talent_infra/azure.yaml` — Activated `resourceName` for all three services referencing main.bicep outputs
- `talent_infra/modules/postgres.bicep` — Added `@batchSize(1)` to Entra admin loop (prevents concurrent operation conflict)

**RBAC role assignments wired:**
| Resource | Role | Role ID | Assigned To |
|----------|------|---------|-------------|
| Cosmos DB | Built-in Data Contributor | `00000000-0000-0000-0000-000000000002` | backend UAMI, MCP UAMI |
| Foundry | Cognitive Services OpenAI User | `5e0bd9bd-7b93-4f28-af87-19fc36ad61bd` | backend UAMI, MCP UAMI |
| Key Vault | Key Vault Secrets User | `4633458b-17de-408a-b874-0445c86b69e6` | all 3 UAMIs |
| ACR | AcrPull | `7f951dda-4ed3-4680-a7ca-43fe172d538d` | all 3 UAMIs |
| PostgreSQL | Entra Admin (server admin) | via administrator child resource | backend UAMI, MCP UAMI, deploying user |

**Env var contract established:**
- Backend (port 8000): POSTGRES_HOST, POSTGRES_DB, COSMOS_ENDPOINT, FOUNDRY_ENDPOINT, FOUNDRY_DEPLOYMENT_NAME, KEY_VAULT_URI, APPLICATIONINSIGHTS_CONNECTION_STRING, AZURE_CLIENT_ID
- MCP (port 3002): same as backend with MCP UAMI clientId
- Frontend (port 80): BACKEND_URL, KEY_VAULT_URI, APPLICATIONINSIGHTS_CONNECTION_STRING, AZURE_CLIENT_ID

**Design decisions:**
1. User-Assigned Managed Identity (UAMI) per workload — created before Container Apps so RBAC propagates before app starts
2. Bootstrap image `mcr.microsoft.com/k8se/quickstart:latest` — Container Apps requires an image at create time; public quickstart lets first `azd up` succeed without ACR images; `azd deploy` replaces with real image
3. Container App names truncated to 32 chars via `take()` — pattern: `ca-tiq-{svc}-{env}-{token}`
4. Frontend gets `external: true` (public); backend + MCP get `external: false` (VNet-internal only)
5. Frontend references backend FQDN via `BACKEND_URL` env var (creates implicit Bicep dependency)
6. Postgres admin loop uses `@batchSize(1)` — Flex Server API doesn't support concurrent admin operations
7. `azd-service-name` tag on each Container App enables azd service discovery alongside `resourceName` in azure.yaml
8. No passwords anywhere — apps use `DefaultAzureCredential` with `AZURE_CLIENT_ID` pointing to their UAMI

**Bicep build validation:** `mcp_bicep_build_bicep` on main.bicep — PASSED (zero errors, zero warnings)

**What's remaining (not Bishop's scope):**
- Dockerfiles for backend, frontend, MCP — Kane/Dallas/Brett create these in `talent_backend/Dockerfile`, `talent_ui/Dockerfile`, `talent_backend/Dockerfile.mcp`
- App-side connection code refactor — switch from env-based connection strings to `DefaultAzureCredential` + endpoint env vars
- KV secrets — seed actual secrets into KV if needed (currently secrets=[] on all Container Apps)
- NAT Gateway — add if outbound connectivity is needed from the VNet (currently not provisioned)

### 2026-05-12: Deployment Runbook — `talent_infra/docs/azd-up.md`

**File created:** `talent_infra/docs/azd-up.md` (~420 lines)

Comprehensive deployment runbook covering:
1. Prerequisites (tools, permissions, region guidance, quota checks, resource provider registrations)
2. First-time setup (`azd env new`, required params: `AZURE_LOCATION`, `AZURE_PRINCIPAL_ID`)
3. Deploy (`azd up` flow, provision-only path, timing estimates)
4. Post-deploy verification (health checks, RBAC verification, Postgres Entra login, private DNS resolution)
5. Local dev against deployed stack (env export, DefaultAzureCredential, private access options)
6. Common operations (single-service redeploy, logs, scale, tear down)
7. Troubleshooting (role assignment failures, Foundry quota, ACR pull delays, Postgres Entra login, DNS resolution, hung deploys)
8. Mermaid architecture diagram (Internet → Frontend public → Backend/MCP internal → data services via PE/VNet)

**Key observations:**
- `main.parameters.json` only wires `location`, `environmentName`, `principalId` from azd env. Other Bicep params (`foundryModelName`, `foundryModelCapacity`, ports) have defaults in main.bicep but are NOT wired through `main.parameters.json` for `azd env set` override. Documented this gap with instructions on how to wire them if needed.
- All commands verified against actual param names and outputs in main.bicep (no hallucinated names).
- No architectural decisions made — this is documentation only.

### 2026-05-12: Fix — MCP service Dockerfile override in azure.yaml

Kane flagged that `azd` defaults to `Dockerfile` for all services sharing `project: ../talent_backend`. Added `docker.dockerfile: Dockerfile.mcp` to the `mcp` service so azd builds from the correct file. Removed stale TODO comments on backend/mcp since both Dockerfiles now exist. Trivial config fix — no decision file.

### 2026-05-12 — Cross-agent: Lambert's smoke suite validates all required Bicep outputs exist
**From Lambert (Tester):**
- Deployment smoke test suite refactored for VNet-aware testing (laptop not on VNet).
- **Bicep outputs verified:** All required outputs from `main.bicep` are present and accessible:
  - `AZURE_CONTAINER_APP_BACKEND_NAME`, `AZURE_CONTAINER_APP_MCP_NAME`, `AZURE_CONTAINER_APP_FRONTEND_NAME`
  - `POSTGRES_FQDN` (for deriving server name in Entra admin checks)
  - Fallback to convention names (`ca-talentiq-{backend|frontend|mcp}-{env}`) is retained for backward compat
- **Status:** No Bicep changes needed for smoke testing — all infrastructure outputs are ready.
- **For Bishop:** The smoke suite documents the env var contract. Any future changes to Container App naming or Bicep outputs must update the test constants to match.
