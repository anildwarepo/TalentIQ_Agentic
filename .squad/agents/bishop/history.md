# Bishop — History

> Older entries archived to `history-archive.md` on 2026-05-16 by Scribe.

## Project Context
- **Project:** TalentIQ — Talent Matching/Searching platform
- **Owner:** Anil
- **Stack:** React Vite (frontend), Python (backend, Agent Framework, MCP servers), PostgreSQL + Apache AGE + DiskANN + FTS, Cosmos DB, Azure AI Foundry (`gpt-5.4`)
- **My role:** Deployment Engineer — own Azure infra (Bicep), `azd` config, VNet, private endpoints, Entra ID + MI auth, and end-to-end `azd up` deployment

## Target Topology
- VNet 10.0.0.0/16 with subnets: snet-aca (/23), snet-pe (/24), snet-db (/24)
- Container Apps Environment (Consumption, VNet-integrated, `internal: false`)
  - **backend** (port 8000) — internal ingress only
  - **frontend** (port 80) — external ingress
  - **mcp-server** (port 3002) — internal ingress only
- Cosmos DB — PE + RBAC-only (disableLocalAuth: true)
- PostgreSQL Flex Server — PG 16, delegated subnet, Entra ID-only auth, extensions: age, vector, pg_trgm, pg_stat_statements
- Azure AI Foundry — AIServices, gpt-5.4, PE dual DNS, RBAC-only
- App Insights + Log Analytics, Key Vault (RBAC, PE), ACR (Premium, PE)
- 3 UAMIs (backend, frontend, mcp) with RBAC: Cosmos Data Contributor, Foundry OpenAI User, KV Secrets User, ACR Pull, PG Entra Admin
- Private DNS zones: cosmos, postgres, cognitive, openai, keyvault, ACR
- Naming: `{abbreviation}-talentiq-{env}-{resourceToken}`

## Key References
- `talentiq_requirements/azd_deploy/`, `talentiq_requirements/foundy-managed-vnet-setup/`
- `docs/specs/vnet-integration.md`, `authentication.md`, `backend-architecture.md`, `database-architecture.md`
- Skills: `azure-postgres`, `microsoft-foundry`

## Work Log

### 2026-05-12: Passes 1-3 (Archived — see history-archive.md)
Built complete infra in 3 passes: networking foundation -> data/supporting services -> Container App workloads + UAMI + RBAC. Also created deployment runbook and fixed MCP Dockerfile override in azure.yaml.

### 2026-05-16: Pass 4 — Full Infrastructure Rebuild (Files Lost -> Recreated)
All Bicep files from Passes 1-3 were lost to disk. Rebuilt entire `talent_infra/` directory (17 files) from this history file as blueprint. Bicep validation passed with zero errors/diagnostics. Removed unused `rbac.bicep` module (RBAC handled inline in each data module). All design decisions preserved exactly.

**Files:** 11 Bicep modules + main.bicep + main.parameters.json + azure.yaml + README + docs/azd-up.md

## Learnings
- History.md as blueprint worked perfectly — exhaustive design decisions = zero ambiguity during rebuild
- Inline RBAC (inside each resource module) is cleaner than separate generic rbac.bicep
- PostgreSQL `@batchSize(1)` on admin loop is critical — Flex Server API rejects concurrent ops
- Foundry PE needs dual DNS zone config (cognitive + openai) — single PE, two privateDnsZoneConfigs
- Key Vault 24-char and Container App 32-char name limits require `take()` truncation
- `mcp_bicep_build_bicep` validation confirms zero-error compilation end-to-end

### 2026-05-16: Pass 5 — Reference Pattern Alignment
Anil requested full alignment with `talentiq_requirements/reference_code/azd_deploy/` pattern. Deleted all existing `talent_infra/` files (except `.azure/`) and rebuilt from scratch.

**New pattern:** Two-phase deployment
- Phase 1: `azd provision` deploys infra only (container app deploy flags = false)
- Phase 2: postprovision hook builds Docker images, then deploys container apps via `az deployment group create`

**Key changes from previous passes:**
- Moved Bicep files from `talent_infra/` to `talent_infra/infra/` (matching `infra.path: ./infra`)
- Added hooks/ directory with preprovision + postprovision (PowerShell + bash)
- Switched from Entra-only auth to password-based PG auth (simpler for dev/test, matching ref)
- Container App module creates its own UAMI inline (not external module)
- Docker builds: local Docker Desktop preferred, ACR remote build fallback, content hashing to skip unchanged
- Data loading uses `talent_data_pipeline/main.py` (not ref's scripts)
- Added Cosmos DB module for chat history (new vs ref)
- Kept Key Vault module
- PostgreSQL extensions: AGE + VECTOR + PG_TRGM
- Bicep compiles clean (1 warning: unused throughput param in serverless Cosmos)

**Files created:** azure.yaml, infra/bicepconfig.json, infra/main.bicep, infra/main.parameters.json, 13 Bicep modules, 4 hook scripts
