# Bishop — History Archive

> Archived 2026-05-16 by Scribe. Entries from 2026-05-12 work log moved here after history.md exceeded 15KB threshold.

## Work Log (Archived)

### 2026-05-12: Pass 1 — Networking Foundation Scaffold

**Files created:** azure.yaml, main.bicep, main.parameters.json, modules/vnet.bicep, modules/container-app-env.bicep, modules/private-dns.bicep, README.md

**Design decisions:**
1. Single CAE with `internal: false` — per-app ingress handles mixed access
2. VNet CIDR 10.0.0.0/16 aligned with vnet-integration.md
3. PostgreSQL gets delegated subnet (snet-db)
4. Naming: `{abbreviation}-talentiq-{env}-{resourceToken}`
5. All Bicep validated — zero diagnostics

### 2026-05-12: Pass 2 — Data + Supporting Service Modules

**Files created:** modules/cosmos.bicep, modules/postgres.bicep, modules/foundry.bicep, modules/app-insights.bicep, modules/key-vault.bicep, modules/acr.bicep

**Design decisions:**
1. PostgreSQL: delegated subnet, Entra ID-only auth, extensions: age, vector, pg_trgm, pg_stat_statements
2. Cosmos DB: own SQL RBAC (not Azure RBAC) for data plane
3. Foundry PE: dual DNS zones (cognitive + openai)
4. Key Vault: name truncated via take(…, 24)
5. ACR: alphanumeric-only name format
6. Log Analytics shared key via `#disable-next-line` output
7. All principalIds arrays left empty for Pass 3

### 2026-05-12: Pass 3 — Container App Workloads, UAMI, RBAC Wiring

**Files created:** modules/managed-identity.bicep, modules/container-app.bicep, modules/rbac.bicep

**RBAC wired:** Cosmos (Data Contributor → backend+MCP), Foundry (OpenAI User → backend+MCP), Key Vault (Secrets User → all 3), ACR (AcrPull → all 3), PostgreSQL (Entra Admin → backend+MCP+deployer)

**Env var contract:** Backend/MCP (POSTGRES_HOST, COSMOS_ENDPOINT, FOUNDRY_ENDPOINT, etc. + AZURE_CLIENT_ID), Frontend (BACKEND_URL, KV, AppInsights, AZURE_CLIENT_ID)

**Design decisions:**
1. UAMI per workload — created before CAs so RBAC propagates
2. Bootstrap image: mcr.microsoft.com/k8se/quickstart:latest
3. CA names truncated to 32 chars: ca-tiq-{svc}-{env}-{token}
4. Frontend external: true; backend+MCP external: false
5. Postgres admin loop @batchSize(1)
6. No passwords anywhere — DefaultAzureCredential + AZURE_CLIENT_ID

### 2026-05-12: Deployment Runbook — talent_infra/docs/azd-up.md
~420 lines covering prerequisites, first-time setup, deploy, post-deploy verification, local dev, common operations, troubleshooting, and Mermaid architecture diagram.

### 2026-05-12: Fix — MCP service Dockerfile override in azure.yaml
Added `docker.dockerfile: Dockerfile.mcp` to mcp service in azure.yaml.

### 2026-05-12: Cross-agent — Lambert's smoke suite validates Bicep outputs
All required outputs present: AZURE_CONTAINER_APP_BACKEND_NAME, _MCP_NAME, _FRONTEND_NAME, POSTGRES_FQDN. No Bicep changes needed.
