# Decisions

> Shared decision log. All agents read this before starting work.
> Only the Coordinator (via Scribe merge) writes here.

<!-- Decisions appear below, newest first. -->

### 2026-05-22T12:30:00Z: Every PaaS Private Endpoint module must discover-and-reuse its `privatelink.<service>.*` Private DNS zone before creating one

**By:** Bishop (Deployment Engineer) — captured at Anil's direction after the `01-postgresql` overlapping-namespaces failure.

**What:** When a per-component deploy module provisions a Private Endpoint for an Azure PaaS service, it MUST first discover whether a Private DNS zone of the canonical `privatelink.<service>.*` name (a) is already linked to the target VNet, or (b) exists unlinked anywhere in the subscription, and REUSE that zone instead of creating a duplicate. The component module only creates a fresh zone when neither check finds anything.

**Why:** Azure enforces *at most one Private DNS zone per namespace per VNet* via `Microsoft.Network/privateDnsZones/virtualNetworkLinks`. A second zone of the same name linked to the same VNet — even from a different RG, even with the original link untouched — is rejected at create time with `BadRequest — A virtual network cannot be linked to multiple zones with overlapping namespaces`. Shared-tenant subs (where a central network team owns the canonical zones in an RG like `vnet`) hit this every time a new per-component deploy lands. Discover-and-reuse is the only resilient fix; pre-conditioning operators on env-var overrides is brittle.

**Where:** Pattern lives in `talent_infra_modules/shared/common.ps1` as two helpers:
- `Get-LinkedPrivateDnsZoneId -SubscriptionId -ZoneName -VnetId` — returns zone ID when any zone of that name is already linked to the VNet, else `$null`.
- `Get-PrivateDnsZoneIdByName -SubscriptionId -ZoneName` — fallback returning the first zone of that name anywhere in the sub, else `$null`.

Bicep contract at every PE module:
- Param: `param existingPrivateDnsZoneId string = ''`
- Param: `param existingPrivateDnsZoneLinked bool = true` (true = skip link creation; false = create link in zone's RG via a nested module deployed with `scope: resourceGroup(split(existingPrivateDnsZoneId, '/')[4])`).
- Conditional creation: `resource privateDnsZone ... = if (empty(existingPrivateDnsZoneId)) { ... }` and matching `if` on the in-RG `virtualNetworkLinks`.

Deploy script contract: discover before confirm, pass both params via `--parameters` overrides, preserve any explicit env-var override (e.g. `POSTGRESQL_DNS_ZONE_ID`, `COSMOS_DNS_ZONE_ID`) as the highest-priority signal (skip discovery when set).

**Reference implementation (done):** `talent_infra_modules/01-postgresql/` — `deploy.ps1` Section 6b, `infra/main.bicep` + `infra/modules/private-endpoint.bicep` + new `infra/modules/private-dns-zone-vnet-link.bicep`. Validated by `mcp_bicep_build_bicep` with zero diagnostics and live-tested against Anil's subscription where the canonical zone in RG `vnet` was correctly discovered as already linked.

**Applies to (future modules — apply when adding PE for the service):**
| Service | Zone name |
|---------|-----------|
| Postgres Flex Server | `privatelink.postgres.database.azure.com` (DONE — 01-postgresql) |
| Cosmos DB SQL API | `privatelink.documents.azure.com` |
| Azure AI Foundry / Cognitive Services | `privatelink.cognitiveservices.azure.com` |
| Azure OpenAI sub-resource | `privatelink.openai.azure.com` |
| Key Vault | `privatelink.vaultcore.azure.net` |
| ACR Premium | `privatelink.azurecr.io` |
| Container Apps Env (when on internal ingress) | `privatelink.<region>.azurecontainerapps.io` |

**Does NOT apply to:** modules that do not create a PE (e.g., `00-container-apps-env` external-only path, anything using service endpoints or public endpoints). Does NOT apply to `talent_infra_v2/` — that lives untouched as the working reference; per-component re-implementations carry the pattern.

**Skill captured:** `.squad/skills/azure-private-dns-discover-reuse/SKILL.md`.

### 2026-05-22T00:30:00Z: ARM/Bicep parameter files — no comment keys allowed

**By:** Bishop (Deployment Engineer) — requested by Anil
**What:** Every top-level key inside the `parameters` block of an ARM/Bicep parameter file (`*.parameters*.json`) MUST be a `DeploymentParameter` object — i.e. `{"value": ...}`. JSON has no comment syntax, and ARM does **not** honor the `_comment_*` convention some tooling uses. Adding a bare-string key like `"_comment_sku": "..."` causes the entire file to fail deserialization with `az deployment ... validate` / `azd up`:

```
ERROR: Unable to build a model: Unable to deserialize response data.
Data: {..., '_comment_sku': '...', 'skuName': {'value': '...'}, ...}, {DeploymentParameter}
```

**Rule for all future modules** (`02-backend`, `03-frontend`, `04-data-loading`, and any new `talent_infra_modules/*/infra/*.parameters*.json`):
- Never add `_comment_*`, `//`-style, or any non-`DeploymentParameter` keys inside the `parameters` object.
- Put human-readable context on the corresponding `param` in the `.bicep` file using `@description('...')`. The description flows into Azure portal hints, `az deployment ... what-if` output, and IDE tooltips — strictly better than a JSON comment.
- If you need cross-file rationale that doesn't fit on a single `@description`, put it in a sibling `README.md` next to the `infra/` folder, not inside the parameter file.

**Why:** This came up because `01-postgresql/infra/main.parameters.json` had a `_comment_sku` explaining the SKU/tier parity with `talent_infra_v2/`. The Bicep already has `@description('PostgreSQL SKU name...')` on `param skuName`, so the comment was redundant **and** breaking the deploy. Removed.

**Scope check:** Swept `talent_infra_modules/**/*.parameters*.json` (all 4 files: `00-container-apps-env`, `01-postgresql`, `02-backend`, `03-frontend`); only `01-postgresql` had the issue. Fixed.

### 2026-05-22T00:00:00Z: Prereq existence checks must use RP-specific `az <rp> show`, not generic `az resource show`

**By:** Bishop (Deployment Engineer) — requested by Anil
**Scope:** `talent_infra_modules/shared/common.ps1` and all per-component `deploy.ps1` scripts that call `Assert-PrerequisitesExist`.
**What:** When a deployment script needs to verify that a piece of pre-existing Azure infrastructure exists, the check MUST call the resource-provider-specific CLI (e.g. `az network vnet show`, `az containerapp show`, `az acr show`, `az cognitiveservices account show`), wrapped in `Invoke-Native` with `$LASTEXITCODE -eq 0` as the truth test. The generic wrapper `Test-ResourceExists` (which goes through `az resource show` → ARM `Microsoft.Resources/resources` read) is ONLY safe when the operator is guaranteed to have `Microsoft.Resources/resources/read` on the target RG, which is NOT true for cross-team / cross-tenant network or shared-platform RGs.
**Why:** Observed on Anil's `01-postgresql` deploy against RG `vnet` containing `vnet-westus`: `Test-ResourceExists -ResourceType 'vnet'` reported "not found" while `Test-VnetSubnetExists` reported "found" on the same VNet's child subnet — same physical resource, same principal, contradictory result. The generic ARM endpoint silently 403'd (presents as 404 to the CLI) while the resource-provider-specific endpoint succeeded with only `Microsoft.Network/virtualNetworks/read`. The RP-specific call is the same RBAC the actual deploy needs, so passing the prereq check guarantees the deploy can also see the resource — no extra ARM-read requirement that's strictly bonus and frequently missing in real environments.
**Implementation already shipped (2026-05-22):**
- Added `Test-VnetExists` to `talent_infra_modules/shared/common.ps1` (sits directly above `Test-VnetSubnetExists` for symmetry).
- Switched the `'vnet'` branch in `Assert-PrerequisitesExist` to call `Test-VnetExists`.
- `Test-ResourceExists` and its `vnet → Microsoft.Network/virtualNetworks` alias are KEPT — they remain valid for any caller invoking the helper directly and for environments where the operator does hold generic ARM read.
- Success/failure log strings (`"VNet $name"` / `"VNet $name not found in RG $vnetRg"`) are unchanged so downstream log scrapers and `AUTH-DISABLED.md` / `DEPLOYMENT-ORDER.md` / `README.md` instructions remain accurate.
**Forward action:** When 02-backend / 03-frontend / 04-data-loading hit a similar RBAC-mismatch symptom for ACR, Container Apps Env, Foundry, Cosmos, Postgres, or Key Vault prereq checks, add the matching `Test-<Thing>Exists` helper (modeled on `Test-VnetExists`) and switch its branch in `Assert-PrerequisitesExist`. Do NOT refactor preemptively — `Test-ResourceExists` is fine for the default greenfield case where the operator has full RG read.
**Non-goals:** This decision does NOT change the public shape of `Assert-PrerequisitesExist`'s `-Checks` parameter or the `Type='vnet'` alias used by callers in `00-container-apps-env/deploy.ps1` (line 182) and `01-postgresql/deploy.ps1` (line 218). Both continue to work; only the internal implementation moved.

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

