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

---

## Archived 2026-05-21 by Scribe — talent_infra_modules deep-dive entries

### 2026-05-16: Pass 4 — Full Infrastructure Rebuild (Files Lost -> Recreated)
All Bicep files from Passes 1-3 were lost to disk. Rebuilt entire `talent_infra/` directory (17 files) from this history file as blueprint. Bicep validation passed with zero errors/diagnostics. Removed unused `rbac.bicep` module (RBAC handled inline in each data module). All design decisions preserved exactly. **Files:** 11 Bicep modules + main.bicep + main.parameters.json + azure.yaml + README + docs/azd-up.md.

**Learnings (Pass 4):**
- History.md as blueprint worked perfectly — exhaustive design decisions = zero ambiguity during rebuild
- Inline RBAC (inside each resource module) is cleaner than separate generic rbac.bicep
- PostgreSQL `@batchSize(1)` on admin loop is critical — Flex Server API rejects concurrent ops
- Foundry PE needs dual DNS zone config (cognitive + openai) — single PE, two privateDnsZoneConfigs
- Key Vault 24-char and Container App 32-char name limits require `take()` truncation
- `mcp_bicep_build_bicep` validation confirms zero-error compilation end-to-end

### 2026-05-16: Pass 5 — Reference Pattern Alignment
Anil requested full alignment with `talentiq_requirements/reference_code/azd_deploy/` pattern. Deleted all existing `talent_infra/` files (except `.azure/`) and rebuilt from scratch.

**New pattern:** Two-phase deployment — Phase 1 `azd provision` deploys infra only (container app deploy flags = false); Phase 2 postprovision hook builds Docker images, then deploys container apps via `az deployment group create`.

**Key changes from previous passes:**
- Moved Bicep files from `talent_infra/` to `talent_infra/infra/` (matching `infra.path: ./infra`)
- Added hooks/ directory with preprovision + postprovision (PowerShell + bash)
- Switched from Entra-only auth to password-based PG auth (simpler for dev/test, matching ref)
- Container App module creates its own UAMI inline (not external module)
- Docker builds: local Docker Desktop preferred, ACR remote build fallback, content hashing to skip unchanged
- Data loading uses `talent_data_pipeline/main.py` (not ref's scripts)
- Added Cosmos DB module for chat history (new vs ref); Kept Key Vault module
- PostgreSQL extensions: AGE + VECTOR + PG_TRGM
- Bicep compiles clean (1 warning: unused throughput param in serverless Cosmos)

**Files created:** azure.yaml, infra/bicepconfig.json, infra/main.bicep, infra/main.parameters.json, 13 Bicep modules, 4 hook scripts.

### 2026-05-21: 04-data-loading orchestrator (`talent_infra_modules/04-data-loading/deploy.ps1`)
Built the terminal step in the per-component deploy chain. Pure local Python invocation against an already-deployed PG (and optionally restarts an already-deployed backend Container App). No Bicep — nothing to deploy at the ARM level.

**Flow:**
1. Dot-source `shared/common.ps1`, verify az sign-in.
2. Read `01-postgresql/.outputs.json` (required), `02-backend/.outputs.json` (optional).
3. Resolve params via `Get-ParameterValue` (explicit → env var → outputs → signed-in user).
4. Check psql + python on PATH, check `talent_data_pipeline.main` importable.
5. Acquire OSSRDBMS Entra token via `az account get-access-token --resource-type oss-rdbms`.
6. Snapshot all PG*/GRAPH_NAME/AZURE_OPENAI_*/FORCE_REGENERATE env vars; restore in `finally`.
7. (Skippable) Pipe SQL into psql to `CREATE EXTENSION IF NOT EXISTS age, vector, pg_trgm, pg_diskann`, `LOAD 'age'`, `create_graph(...)` wrapped in a `DO ... EXCEPTION WHEN ... LIKE '%already exists%'` block so re-runs are idempotent.
8. (Skippable via -Force) Idempotency gate: run a Cypher count of Employee nodes via psql; if > 0 prompt before proceeding.
9. `cd talent_data_pipeline && python -m talent_data_pipeline.main [--force]` — pipeline uses its own `pg_entra.pg_connect()` (DefaultAzureCredential), so PGPASSWORD is irrelevant to it but PGHOST/PGPORT/PGDATABASE/PGUSER/PGSSLMODE/GRAPH_NAME drive its connect kwargs.
10. (Opt-in) `-NarrowBackendGrants` invokes `talent_infra_v2/scripts/provision_pg_entra_roles.py` with `--principals` built from `02-backend/.outputs.json` (backendUamiName + backendUamiPrincipalId, type=service). Forwards `--hostaddr` when `-PgPrivateIp` is set. Script is invoked AS-IS — not modified.
11. (Opt-in) `-RestartBackend` discovers active revision via `az containerapp show --query properties.latestRevisionName` then runs `az containerapp revision restart`.
12. Final summary: 15-label vertex count table via psql Cypher, grants-narrowed flag, backend-restarted flag. No `.outputs.json` (terminal step).

**Files:** `04-data-loading/deploy.ps1` (~510 lines). README.md was already authored.

**Learnings (04-data-loading):**
- **Data pipeline invocation pattern:** `python -m talent_data_pipeline.main` from the pipeline directory, after `pip install -e .` makes the inner `talent_data_pipeline/talent_data_pipeline/` package importable. Pipeline reads env at `import` time (config.py `field(default_factory=lambda: os.getenv(...))`), so env vars MUST be set BEFORE the python child process starts. Pipeline ignores `PGPASSWORD` (uses its own `pg_entra.pg_connect()` → DefaultAzureCredential → OSSRDBMS token per connect). Pipeline ALSO ignores `PGHOSTADDR` — it only reads `PGHOST`. If PG is private-link-only, a hosts-file entry is required for the pipeline; psql can use `PGHOSTADDR` natively to bypass.
- **`-NarrowBackendGrants` is OPT-IN (not default):** The deliberate trade-off documented in 04-data-loading/README.md and `/memories/repo/talentiq-azd-deploy.md` is that the broad PG-admin grant from 01-postgresql's control-plane registration is a fallback for networks that block port 5432. Auto-narrowing on every run would break working deployments when the deployer's network conditions change (Comcast DPI, VPN swaps, etc.). The operator explicitly opts in once the deployment is healthy and they're on a network that can reach PG over 5432.
- **psql dependency:** Required and non-substitutable for the extensions step. Cannot replace with a Python script easily because the pipeline's `pg_entra.pg_connect` lives inside the pipeline package — calling it before extensions exist would require either importing the pipeline (which requires extensions for its connectivity_test) or duplicating its token logic. Cleaner to mandate psql, which is universal and well-supported on Windows via choco/winget.
- **PowerShell here-string + Postgres dollar-quoting:** Inside an expandable `@"..."@`, escape `$$` as `` `$`$ `` and `$cy$` as `` `$cy`$ ``. Validated by printing the expanded string before piping to psql.
- **Idempotent `create_graph`:** Wrapped in `DO $$ ... EXCEPTION WHEN OTHERS THEN IF SQLERRM LIKE '%already exists%' THEN RAISE NOTICE ... ELSE RAISE; END IF; END $$` so re-runs are no-ops. Lets ON_ERROR_STOP=1 catch every other error class.
- **Env var hygiene:** Snapshot to a hashtable, restore in a top-level `try/finally`. Avoids polluting the caller's shell with PGPASSWORD (a real Entra token) on success OR failure.

### 2026-05-21: talent_infra_modules/01-postgresql — standalone deployer implemented
**Files:** deploy.ps1 (parser-validated), infra/main.bicep (mcp_bicep_build_bicep: zero diagnostics), infra/main.parameters.json, infra/modules/postgresql-flexible-server.bicep (verbatim copy), infra/modules/private-endpoint.bicep (verbatim copy).
**Layout decision:** infra/modules/ holds copies of the v2 modules so 01-postgresql is fully self-contained — no relative `../../talent_infra_v2/...` paths. The v2 originals are untouched.

**Learnings (01-postgresql):**
- main.bicep deviates from the v2 wiring in one critical way: `entraAdminObjectId` and `entraAdminPrincipalName` are passed as EMPTY strings, deliberately skipping the `Microsoft.DBforPostgreSQL/flexibleServers/administrators` child resource. This avoids the `AadAuthOperationCannotBePerformedWhenServerIsNotAccessible` re-PUT race on idempotent redeploys (the same one I patched in v2 postprovision by clearing those params before redeploy). Admin registration moves entirely to deploy.ps1 via control plane.
- Conditional `existing` VNet + PE subnet refs scoped to `vnetResourceGroup` work cleanly when the consuming module is also guarded by `if (enablePrivateEndpoint)`. Used the safe `!.id` accessor — zero diagnostics from the Bicep compiler.
- `Get-ParameterValue` from common.ps1 only resolves strings/SecureString. For int (`storageSizeGB`) and bool (`enablePrivateEndpoint`) params I read env vars manually with explicit casts rather than passing strings through Get-ParameterValue and casting later — keeps the type contract explicit.
- The deterministic auto-server-name uses SHA-256 of `subId|rg|location` truncated to 5 hex chars (`tiqpg<hash>`). Re-runs with the same inputs produce the same name → Bicep idempotency works. Re-runs across regions or RGs produce a different name → no PG global-uniqueness collisions when iterating envs.
- Bicep best practices say "avoid setting the `name` field for `module` statements" — followed throughout main.bicep. The implicit module symbol-name is used wherever a deployment-name was previously required.
- `ConvertFrom-SecureStringPlain` is called once and the resulting plain string is null'd immediately after the `az deployment group create` call returns — never logged, never reused.
- Two control-plane admin registrations are wired with full idempotency: list-then-add for the deployer (User), and list-then-add-per-entry for UAMIs (ServicePrincipal). Both swallow "already exists / conflict" errors so re-runs are a clean no-op.
- The pending-restart probe + restart is the same belt-and-braces pattern as v2's `Ensure-PostgresqlConfigApplied` helper — without it, AGE silently fails on every `cypher()` call and the user has no diagnostic signal until the first query runs.
- PE private IP discovery is done via NIC ID lookup (matching v2's `Get-PostgresqlPrivateEndpointInfo` shape) and stored as null in .outputs.json when the PE has no NIC reference — downstream 02-backend can decide whether private IP is required.

### 2026-05-21: 02-backend orchestrator + Bicep (`talent_infra_modules/02-backend/`)
Built the standalone backend deployment for the per-component chain. Produces a single Container App with the MCP server as a sidecar, sharing one UAMI. Bicep + deploy.ps1 + parameters.json + .acrignore. Bicep validation passed (1 cosmetic `use-safe-access` warning preserved from the v2 module for parity).

**Flow:**
1. Dot-source `shared/common.ps1`, az sign-in.
2. Read `01-postgresql/.outputs.json` (required). Prefer `postgresqlPrivateFqdn` when `postgresqlPrivateIp` is present (PE detected).
3. Resolve params (`Get-ParameterValue`). Default `BackendAppName` is SHA256-hash-derived from (SubscriptionId, ResourceGroup) → stable across re-runs.
4. Same-RG fail-fast on AcrResourceGroup/FoundryResourceGroup/CosmosResourceGroup mismatches.
5. `Assert-PrerequisitesExist` (RG, ACR, ACA env, optional Cosmos) + `Test-FoundryProject` (account + project + `ChatModelDeployment` exists).
6. Resolve ACR loginServer + ACA env full ARM ID via az.
7. `az acr build` for backend (Dockerfile) + mcp-server (Dockerfile.mcp). `-SkipBuild` bypasses.
8. Bicep deploy with explicit `--parameters key=value` overrides; deployment name includes UTC timestamp.
9. Post-deploy: `az postgres flexible-server microsoft-entra-admin create --type ServicePrincipal --display-name <UAMI-name> --object-id <principalId>`. Idempotent via ad-admin list match on `objectId`/`sid`.
10. `-RestartActive`: resolve active revision via `[?properties.active].name | [0]`, restart to flush MCP session cache.
11. Emit `.outputs.json` ⇒ 03-frontend reads `backendContainerAppFqdn`; 04-data-loading reads `backendUamiName`/`backendUamiPrincipalId`.

**Files:** `deploy.ps1`, `infra/main.bicep`, `infra/main.parameters.json`, `infra/modules/container-app.bicep`, `.acrignore`.

**Learnings (02-backend):**
- **Bicep cross-RG role assignments** require sub-modules deployed at the target scope. Inline `scope: <existing-cross-RG-ref>` on a `Microsoft.Authorization/roleAssignments` resource hits BCP139. For talent_infra_modules MVP, chose same-RG constraint over the sub-module sprawl — talent_infra_v2 remains the cross-RG path.
- **BCP120 ("name must be calculable at start")** triggers when `guid(...)` for a role-assignment `name` uses a module output (e.g. `backend.outputs.identityPrincipalId`). Fix: use deploy-time-known param values in `guid()` — `backendAppName`, `foundryAccountName`, `cosmosAccountName`. `principalId` itself is still allowed in `properties.principalId` (runtime is fine there).
- **AcrPull race mitigation** stays inline in container-app.bicep via `dependsOn: [ acrPullRole ]` on the Container App resource. The v2 pattern works; do not reinvent.
- **MCP sidecar wiring**: both containers get `AZURE_CLIENT_ID` injected from the SAME UAMI via the module — no separate MCP UAMI, no separate PG role. PGUSER on both = `<backendAppName>-identity`. MCP_ENDPOINT on backend only = `http://localhost:3002/mcp`.
- **AZURE_TENANT_ID omission is THE auth-disable contract** — talent_backend/auth.py lines 86-90 short-circuit to dev mode without it. Verifiable via grep on the bicep env arrays. Never set this var in talent_infra_modules — even reflexively. README, AUTH-DISABLED.md, and the bicep comments all triple-state this.
- **PG control-plane registration is post-bicep, not in-bicep**: `az postgres flexible-server microsoft-entra-admin create --type ServicePrincipal --display-name <UAMI-name> --object-id <principalId>`. Display-name MUST equal UAMI name (it becomes the PG username). The 01-postgresql/ pattern uses the same control-plane mechanism; we reuse it here for the brand-new 02-backend UAMI.
- **PE detection via `postgresqlPrivateIp` presence** is simpler than DNS resolution. If 01-postgresql/.outputs.json contains a non-empty `postgresqlPrivateIp`, use `postgresqlPrivateFqdn`; otherwise use `postgresqlServerFqdn`. The Container Apps are VNet-integrated, so privatelink FQDN resolves correctly via Azure DNS.
- **Deterministic `BackendAppName` default** (SHA256 first 5 chars of `SubscriptionId|ResourceGroup|backend`) gives idempotent re-runs without operator pinning. Same RG → same name → same Container App.
- **Active revision restart** uses `--query "[?properties.active].name | [0]"` rather than the bicep-output `latestRevisionName` because a bicep deploy creates a NEW revision; the "latest" output is the post-deploy revision but the "active" one may differ in edge cases (e.g. multi-revision modes).
- **`Resolve-Path` + `?.Path` + `??`** requires PowerShell 7. `Stop = 'Continue'` inside `Invoke-Native` allows native non-zero exits to propagate via `0` rather than throwing.
- **`az deployment group create` argument shape**: each `--parameters key=value` override must be its OWN argv slot. Build the argv array explicitly (`@(...)`); PowerShell native-command splatting works correctly when each override is added as two consecutive elements (`--parameters`, `key=value`).

---

## Learnings (Archived)

> Three deep-dive Learnings entries from 2026-05-21 moved here by Scribe on 2026-05-22 (Bishop's history.md crossed the 15,360-byte gate after appending the 2026-05-22 RBAC-asymmetry Learning). Entries appear in the same order they had in history.md.
### 2026-05-21 — PowerShell case-insensitive variable/parameter shadowing in `Get-ParameterValue`

- **Symptom:** `01-postgresql/deploy.ps1` blew up at the secure-password prompt with two cascading errors:
  - `Cannot convert the "System.Security.SecureString" value of type "System.Security.SecureString" to type "System.Management.Automation.SwitchParameter"` (origin: `shared/common.ps1:219`)
  - `Cannot convert "System.Management.Automation.SwitchParameter" to "System.Security.SecureString"` (cascade: `01-postgresql/deploy.ps1:123` on the typed `[SecureString]$AdminPassword` assignment)
- **Root cause:** Inside `Get-ParameterValue` the `if ($Secure) {...}` branch assigned `$secure = Read-Host -AsSecureString`. PowerShell variable identifiers are **case-insensitive**, so `$secure` (local) and the `[switch]$Secure` parameter are the **same variable**. Assigning a `[SecureString]` to a slot already typed as `[switch]` failed type coercion, the function never returned a real value, and the caller's `[SecureString]$AdminPassword` then received a `[switch]` — second error.
- **Fix (single-point cure for all 5 components dot-sourcing `common.ps1`):** Renamed the local in the `if ($Secure) {...}` block from `$secure` → `$secureValue` (3 references: assignment, null/Length guard, return). Added an in-source `# NOTE:` warning explaining the case-insensitivity trap so future edits don't regress.
- **Audit performed:**
  - Grepped `common.ps1` for any other `$(name|prompt|value|default|envVar|secure) =` assignments. Only the buggy line and one harmless `$name = [string]$c.Name` inside `Assert-PrerequisitesExist` (which has no `$Name` parameter, so no collision).
  - `ConvertFrom-SecureStringPlain` reads its `[SecureString]$Secure` parameter directly — no local shadow.
- **Verified:** `[System.Management.Automation.Language.Parser]::ParseFile(...)` under **pwsh 7** reports `PARSE OK`. (Windows PowerShell 5.1 reports 12 comment-block parser-noise errors at lines 458/482/511/512/562 — these are pre-existing and unrelated; the toolkit targets pwsh 7.)
- **Rule for the `talent_infra_modules/` codebase:** PowerShell locals MUST NOT case-insensitively collide with a parameter name in the same scope. Prefer suffixed names (`$secureValue`, `$nameStr`, `$promptText`) when the natural local name would equal a parameter.
- **Files touched:** `talent_infra_modules/shared/common.ps1` only. No caller changes needed — fix is transparent to all 5 components (`00-container-apps-env`, `01-postgresql`, `02-backend`, `03-frontend`, `04-data-loading`) and to any future component using `Get-ParameterValue -Secure`.

### 2026-05-21 (later): `00-container-apps-env/` — standalone ACA env deployer (follow-on, silent-success)
Anil added a 5th component to the toolkit after Lambert's APPROVED verdict: an optional standalone deployer for the Container Apps Environment itself. This closes the last greenfield gap — operators on a brand-new tenant can now bring up `00 + 01 + 02 + 03 + 04` end-to-end through `talent_infra_modules/` without falling back to `talent_infra_v2/`.

- **Files produced (new):** `talent_infra_modules/00-container-apps-env/{README.md, deploy.ps1, infra/main.bicep, infra/main.parameters.json, infra/modules/container-apps-environment.bicep, infra/modules/aca-subnet.bicep}`.
- **Cross-folder edits:** `talent_infra_modules/README.md` (added `00` to component table + prerequisites), `DEPLOYMENT-ORDER.md` (added Step 0 — foundational, parallel-with-`01`, blocks `02` + `03`), `02-backend/deploy.ps1` and `03-frontend/deploy.ps1` (soft-fallback: when `ContainerAppsEnvName` not provided, read `../00-container-apps-env/.outputs.json` — operators no longer need to copy CAE names between commands).
- **Key choice — subnet handling lives in `deploy.ps1`, not Bicep.** The pre-existing-or-create branch validates delegation to `Microsoft.App/environments`, soft-lock awareness, and CIDR membership before any control-plane call. Bicep only ever receives a resolved `subnetId`, so the Bicep is a clean module take-or-create-CAE-against-a-subnet — single source of truth for subnet shape lives in PowerShell where it can talk to the control plane.
- **No data-plane operations.** This module never touches PG, Cosmos, or Foundry; it just produces a CAE id + subnet id that 02 and 03 will consume.
- **Validation (coordinator-side).** `az bicep build` against `00-container-apps-env/infra/main.bicep` → zero diagnostics. PowerShell AST parser against `00-container-apps-env/deploy.ps1` → zero parse errors.
- **Silent-success caveat — read this if you re-open the 00 work.** My spawn for this module returned no chat text and produced no `decisions/inbox/` drop file, but all 10 affected paths landed on disk correctly. Squad coordinator filesystem-verified everything per the `<!-- KNOWN PLATFORM BUGS -->` workaround in `squad.agent.md`, then handed Scribe a recovery manifest. The `decisions.md` entry for this work is attributed to Bishop with explicit `(recovered by Squad coordinator — Bishop spawn returned silent success; all artifacts verified on filesystem and validated)` status so the audit trail is honest — that decision was authored from the recovery manifest, not by me directly. If you re-spawn me on this module, the artifacts and design choices recorded here are authoritative; the silent-success episode is a platform symptom, not missing work.

### 2026-05-21 — Postgres SKU/tier parity: `01-postgresql/` must mirror `talent_infra_v2/`

- **Symptom:** Azure deploy of `talent_infra_modules/01-postgresql/` failed with `ServerEditionIncompatibleWithSkuSize: The requested server edition is incompatible with requested Sku Size.`
- **Root cause:** `01-postgresql/{deploy.ps1, infra/main.bicep, infra/main.parameters.json}` all defaulted to `skuName=Standard_B2s` + `skuTier=GeneralPurpose`. **`Standard_B2s` is Burstable-only.** The valid PG Flexible Server pairings are:
  - `Burstable` ↔ `Standard_B*` (B1ms, B2s, B2ms, B4ms, …)
  - `GeneralPurpose` ↔ `Standard_D*ds_v4/v5` (D2ds_v4, D4ds_v5, …)
  - `MemoryOptimized` ↔ `Standard_E*ds_v4/v5`
- **Why v2 didn't hit this:** `talent_infra_v2/infra/main.bicep:146` has the **same broken default** (`Standard_B2s`/`GeneralPurpose`), but `talent_infra_v2/infra/main.parameters.json:86–91` overrides it with `Standard_D4ds_v5`/`GeneralPurpose`. The standalone modules folder had no such override, so the broken Bicep default reached Azure.
- **Canonical source-of-truth for postgres SKU:** **`talent_infra_v2/infra/main.parameters.json`**, fields `postgresqlSkuName` / `postgresqlSkuTier` / `postgresqlStorageSizeGB` / `postgresqlVersion`. As of 2026-05-21: `Standard_D4ds_v5` / `GeneralPurpose` / `32` / `"16"`.
- **Fix applied to 01-postgresql:**
  - `deploy.ps1` param block: `$SkuName="Standard_D4ds_v5"`, `$SkuTier="GeneralPurpose"` (was `Standard_B2s`). Added a comment block above the params citing v2 parity + the Burstable/GeneralPurpose hazard.
  - `deploy.ps1` `Get-ParameterValue` calls: `-Default "Standard_D4ds_v5"` / `-Default "GeneralPurpose"`. Env-var overrides `POSTGRESQL_SKU_NAME` / `POSTGRESQL_SKU_TIER` still take precedence.
  - `infra/main.bicep`: `param skuName string = 'Standard_D4ds_v5'`. Rewrote `@description` to enumerate the valid `tier ↔ family` pairings so the next reader can't repeat the mistake.
  - `infra/main.parameters.json`: `skuName.value = "Standard_D4ds_v5"`. Added a `_comment_sku` field pointing to the v2 source file.
- **Files INTENTIONALLY NOT touched (verbatim-parity discipline):**
  - `infra/modules/postgresql-flexible-server.bicep` keeps its own `Standard_B2s` default — `main.bicep:112-113` always passes explicit `skuName`/`skuTier` into the module call, so the submodule default is unreachable. Leaving it identical to the v2 submodule keeps the diff surface clean.
  - `talent_infra_v2/` (read-only canonical source).
- **Validation:**
  - `bicep build` on the modified `infra/main.bicep` → `success=true`, 0 errors, 0 warnings.
  - PowerShell 7 AST parser on `deploy.ps1` → zero parse errors (2455 tokens).
- **Rule for this toolkit:** Postgres SKU/tier/version/storage in `talent_infra_modules/01-postgresql/` is a downstream mirror of `talent_infra_v2/infra/main.parameters.json`. Treat any divergence as a bug-in-waiting; reviewers should diff the two at PR time. Decision drop: `.squad/decisions/inbox/bishop-postgres-sku-parity.md`.
- **Deploy NOT re-run** — Anil owns deploys; the fix is staged but unexecuted on the live RG.


## Learnings (Archived 2026-05-22 by Scribe)

### 2026-05-22T00:00:00Z — Asymmetric RBAC: `az resource show` vs `az <rp> show` for prereq checks

- **Symptom:** Deploying `01-postgresql` produced a contradictory verification report — VNet `vnet-westus` in RG `vnet` reported "not found" while its child subnet `pe-subnet` in the same VNet reported "found" on the same RBAC principal. Logically impossible if both checks hit the same code path.
- **Root cause:** `Assert-PrerequisitesExist` was asymmetric. The `'vnet'` branch called `Test-ResourceExists` → `az resource show`, which goes through the generic ARM `Microsoft.Resources/resources` endpoint and requires broader RBAC than the resource-provider-specific call. The `'subnet'` branch called `Test-VnetSubnetExists` → `az network vnet subnet show`, which only needs `Microsoft.Network/virtualNetworks/subnets/read` (and implicitly verifies the parent VNet). Anil has Network-RP read on the cross-tenant `vnet` RG but not generic `Microsoft.Resources/resources/read`, so the VNet check 403'd silently (treated as 404) while the subnet check succeeded.
- **Fix:** Added `Test-VnetExists` (`az network vnet show ...`) alongside `Test-VnetSubnetExists`. Switched the `'vnet'` branch in `Assert-PrerequisitesExist` to use it. Kept `Test-ResourceExists` and its `vnet → Microsoft.Network/virtualNetworks` alias intact for any external callers using it directly. Success/failure messages unchanged so log scrapers and docs aren't disturbed.
- **Rule of thumb for this codebase:** Prereq existence checks should use **resource-provider-specific `az <rp> show` calls**, not `az resource show`. The minimum RBAC for the RP-specific call is the same RBAC the actual deploy needs (read on the same resource type), so if the prereq check passes, the deploy can also see the resource. `az resource show` adds a generic ARM read requirement that's strictly extra and frequently missing on cross-team / cross-tenant network RGs.
- **Applies to future modules:** 02-backend, 03-frontend, 04-data-loading prereq checks against the VNet, ACR, Container Apps env, Foundry, Cosmos, Postgres should all migrate to RP-specific helpers as needs arise (don't refactor preemptively — only when a real RBAC mismatch surfaces, since `Test-ResourceExists` is still fine for the common case where the operator has full RG read).

### 2026-05-22T12:15:00Z — Private DNS zone discover-and-reuse (overlapping-namespaces fix)

- **Symptom:** `01-postgresql` deploy failed with `BadRequest — A virtual network cannot be linked to multiple zones with overlapping namespaces. You tried to link virtual network with 'privatelink.postgres.database.azure.com' and 'privatelink.postgres.database.azure.com' zones.`
- **Constraint:** Azure enforces **at most one Private DNS zone per namespace per VNet** via `Microsoft.Network/privateDnsZones/virtualNetworkLinks`. Adding a *second* zone of the same name and linking it to the *same* VNet — even from a different RG and even with the original link untouched — is rejected at create time. The error is the same whether the conflict is detected because the new zone is being created or because an existing-elsewhere zone is being re-linked.
- **Discovery confirmed live:** Smoke-tested in Anil's sub `e4718866-...`. Found TWO zones of that exact name: one in RG `vnet` (already linked to `vnet-westus`) and one in RG `rg-kg4-westus` (unlinked). The deploy was creating a brand-new third zone in `rg-talent-devtest-11` and tried to link `vnet-westus` to it → rejected. The fix correctly picks the LINKED zone in `vnet` (not the unlinked duplicate) and reuses it.
- **Fix — script side:** Two new helpers in `talent_infra_modules/shared/common.ps1`:
  - `Get-LinkedPrivateDnsZoneId -SubscriptionId -ZoneName -VnetId` — lists all subscription zones with that exact name and per-zone enumerates `virtualNetworkLinks` to find one whose `virtualNetwork.id` matches (case-insensitive). Returns zone ID or `$null` on miss/RBAC fail.
  - `Get-PrivateDnsZoneIdByName -SubscriptionId -ZoneName` — fallback when no linked zone exists; returns the first zone of that name anywhere in the sub or `$null`.
  - Both use `Invoke-Native { az network private-dns ... }` so they obey the same RP-specific RBAC pattern as `Test-VnetExists` (Microsoft.Network read on the zone RG is sufficient — no generic `Microsoft.Resources/resources/read` needed).
  - Both return `$null` on miss — never `throw` — so the deploy script can decide whether to keep going or let Bicep create a fresh zone.
- **Fix — script wiring (`01-postgresql/deploy.ps1`):** New "Section 6b" between prereq check and confirm: when PE is enabled AND no explicit `-ExistingDnsZoneId`/`POSTGRESQL_DNS_ZONE_ID` override is in play, call `Get-LinkedPrivateDnsZoneId` first; on miss, call `Get-PrivateDnsZoneIdByName`. Sets `$ExistingDnsZoneId` and a new `$ExistingDnsZoneLinked` flag (true when reusing the linked path, false when reusing an unlinked zone, true by default when nothing was found so Bicep's defaults remain backward-compatible). Both are passed as `--parameters` overrides.
- **Fix — Bicep side (`infra/main.bicep` + `infra/modules/private-endpoint.bicep`):** New `existingPrivateDnsZoneLinked bool = true` param at both layers. New nested module `infra/modules/private-dns-zone-vnet-link.bicep` that creates a single `virtualNetworkLinks` child of an `existing` zone reference. Caller deploys it with `scope: resourceGroup(existingZoneRg)` parsed from the existing zone's resource ID (`split(...)[4]` for RG, `last(split(...))` for zone name). Gated by `if (useExistingDnsZone && !existingPrivateDnsZoneLinked)` so it only fires for the unlinked-reuse path. Defaults preserve the original behavior bit-for-bit (when no `existingPrivateDnsZoneId` is passed, Bicep still creates the zone + link in the deployment RG).
- **Validation:** PSParser clean on both `.ps1` files. `mcp_bicep_build_bicep` on `main.bicep` returned `"diagnostics": []` (zero errors, zero warnings). Compiled ARM correctly shows the nested deployment at `"resourceGroup": "[variables('existingZoneRg')]"` with the conditional `and(useExistingDnsZone, not(existingPrivateDnsZoneLinked))`. Live discovery smoke-tested against Anil's sub — found the linked zone in RG `vnet`.
- **Same pattern applies to every other PaaS PE in this stack.** Cosmos (`privatelink.documents.azure.com`), Foundry/CogServices (`privatelink.cognitiveservices.azure.com` + `privatelink.openai.azure.com`), Key Vault (`privatelink.vaultcore.azure.net`), ACR (`privatelink.azurecr.io`). When 02-backend/03-frontend modules add PEs for those services, copy the same discover-then-reuse flow. Decision drop + skill file capture the rule.
- **Did NOT do (per spawn):** modify `talent_infra_v2/`, re-run `.\deploy.ps1`, add interactive prompting, remove the `POSTGRESQL_DNS_ZONE_ID` env-var override (still honored as the highest-priority signal — discovery only runs when it's empty).

---

## Archived 2026-05-22T22:30:00Z by Scribe

### 2026-05-21: `talent_infra_modules/` — per-component deploy chain (original Work Log entry)

Owned three of the four component folders:

- **01-postgresql/** — standalone PG Flex Server deployer. `deploy.ps1` + `infra/main.bicep` + parameters + verbatim copies of v2's `postgresql-flexible-server.bicep` and `private-endpoint.bicep` under `infra/modules/`. Folder is self-contained — no `../../talent_infra_v2/...` paths. Bicep compiles zero-diagnostics. Admin registration moved out of Bicep into deploy.ps1 control-plane calls (avoids `AadAuthOperationCannotBePerformedWhenServerIsNotAccessible` re-PUT race). Deterministic server name `tiqpg<sha5>` from `subId|rg|location`. Emits `.outputs.json` consumed by 02-backend and 04-data-loading.
- **02-backend/** — Container App + MCP sidecar sharing one UAMI. `deploy.ps1` + `infra/main.bicep` + parameters + `infra/modules/container-app.bicep` + `.acrignore`. Bicep validation passed (1 cosmetic `use-safe-access` warning preserved for parity with v2). Reads `01-postgresql/.outputs.json`; same-RG fail-fast on AcrResourceGroup/FoundryResourceGroup/CosmosResourceGroup mismatches. `az acr build` for both Dockerfile + Dockerfile.mcp. Post-deploy control-plane PG admin registration using `--display-name <UAMI-name>` (display-name == UAMI name == PGUSER). Emits `.outputs.json` consumed by 03-frontend and 04-data-loading.
- **04-data-loading/** — terminal step. Pure local Python invocation, no Bicep. `deploy.ps1` (~510 lines) reads 01 and 02 outputs, acquires OSSRDBMS Entra token, snapshots/restores all `PG*`/`GRAPH_NAME`/`AZURE_OPENAI_*`/`FORCE_REGENERATE` env vars in `try/finally`, pipes idempotent extension+graph SQL through psql, runs `python -m talent_data_pipeline.main`. `-NarrowBackendGrants` (opt-in) invokes `talent_infra_v2/scripts/provision_pg_entra_roles.py` AS-IS. `-RestartBackend` (opt-in) restarts the active revision. No `.outputs.json` (terminal). README.md was pre-authored.

**Files produced this session (all under `talent_infra_modules/`):** 3 deploy.ps1 files + 3 `infra/main.bicep` + 3 parameter files + module copies (postgresql, private-endpoint, container-app) + 1 `.acrignore`. Plus the shared `AUTH-DISABLED.md`, `DEPLOYMENT-ORDER.md`, `README.md` from prior turns.

### 2026-05-22T00:00:00Z — Asymmetric RBAC: `az resource show` vs `az <rp> show` for prereq checks (original)

Prereq existence checks under `talent_infra_modules/` should use resource-provider-specific `az <rp> show` calls (e.g. `az network vnet show`) rather than the generic `az resource show`, because the RP-specific call needs the same RBAC the deploy itself needs — passing the prereq guarantees the deploy can also see the resource. Fix already shipped in `shared/common.ps1::Test-VnetExists` + `Assert-PrerequisitesExist`'s `'vnet'` branch.

### 2026-05-22T12:15:00Z — Private DNS zone discover-and-reuse (original)

Azure enforces at most one Private DNS zone per namespace per VNet. The fix added `Get-LinkedPrivateDnsZoneId` + `Get-PrivateDnsZoneIdByName` helpers to `shared/common.ps1`, wired a Section 6b discovery pass into `01-postgresql/deploy.ps1`, and added an `existingPrivateDnsZoneLinked` Bicep param + a new `private-dns-zone-vnet-link.bicep` module so unlinked existing zones can be reused. Pattern applies to every PaaS PE in the stack.

### 2026-05-22T00:30:00Z — ARM/Bicep parameter files reject non-DeploymentParameter keys (original)

- ARM/Bicep parameter files reject any top-level key under `parameters` that isn't a `{value: ...}` DeploymentParameter — no `_comment_*` keys, no JSON comments. Use `@description()` on Bicep `param` declarations for inline docs. (Symptom: `az deployment ... validate` failed in `01-postgresql/` with `Unable to deserialize response data ... {DeploymentParameter}` after a `_comment_sku` string was added next to `skuName`. Fix: deleted the comment key; Bicep already has the description on the `param skuName` decorator.)

### 2026-05-22T18:00:00Z — Stale PE `privateDnsZoneGroup` self-heal in `01-postgresql/deploy.ps1` (original)

- **Symptom (live on `rg-talent-devtest-11`):** Redeploy after the 6b discover-and-reuse patch failed with `UpdatingPrivateDnsZoneIdOnPrivateDnsZoneConfigNotAllowed`. PE `tiqpg9a6d3-pe` already had a `default` zone group with config `privatelink-postgres-database-azure-com` pointing at an orphan zone in `rg-talent-devtest-11` (created in-place by the pre-fix PE itself, 1 A record `tiqpg9a6d3 -> 10.0.4.16`). The current run resolves the canonical zone in RG `vnet` (2 record sets, 1 link). Bicep tries to in-place mutate `privateDnsZoneConfigs[*].properties.privateDnsZoneId` — Azure forbids it. **No Bicep edits could fix this** because the constraint is at the ARM/Network-RP layer, not the template.
- **Azure rule (load-bearing):** `privateDnsZoneConfigs.properties.privateDnsZoneId` is **immutable** on an existing `privateDnsZoneGroup`. The ONLY way to repoint a PE's zone group at a different Private DNS zone is to **delete the parent `privateDnsZoneGroup`** (always named `default` on PEs created from `private-endpoint.bicep`, but read from the API not hardcoded) and let the next deploy recreate it. This generalises to every PE in the stack — Cosmos, Foundry, KeyVault, ACR all hit it the same way on environments with pre-pattern artifacts.
- **Fix — script side only, no Bicep changes:**
  - **New param `-FixStaleDnsZoneGroup` (switch)** in `deploy.ps1` `param()` block, sits right before `[switch]$Force`. `-Force` implies it (so existing CI does not need to learn a new switch). Documentation comment in-line referencing Sections 6c and 7b.
  - **Section 6c (detection, read-only)** between 6b zone discovery and Section 7 confirm. Probes `az network private-endpoint show -g $rg -n "${ServerName}-pe" 2>$null`; first-run safe (exit != 0 or empty body -> log "PE not present yet" and skip). Lists zone groups via `az network private-endpoint dns-zone-group list`. For each config, case-insensitive compares `privateDnsZoneId` to the resolved `$ExistingDnsZoneId` using `-ieq`. On mismatch, sets `$StaleZoneGroup` + `$StaleZoneGroupOldZoneId` and breaks the outer loop (one mismatch is enough to trigger the repair). Read-only — no destructive action here.
  - **Section 7 plan summary** got two new yellow lines surfacing the planned repair: the stale zone group name + the gate status (`auto-approved (-FixStaleDnsZoneGroup or -Force)` vs `BLOCKED -- rerun with -FixStaleDnsZoneGroup`).
  - **Section 7b (act)** between Confirm-Action and Bicep deploy. If `$null -ne $StaleZoneGroup` AND not (`$FixStaleDnsZoneGroup -or $Force`) -> `Write-Fail` with rerun instructions and `exit 1` (fail loud -- don't silently let Bicep error half-way). If gated, runs `az network private-endpoint dns-zone-group delete -g $rg --endpoint-name $peName -n $StaleZoneGroup --output none` (the `--yes` flag does **not** exist on this subcommand and was removed during design -- only on `private-dns zone delete`). Checks `$LASTEXITCODE`; exit 1 on failure with the captured stderr indented under the error line.
  - **Section 7c (orphan-zone best-effort cleanup)** runs ONLY when 7b actually deleted a stale group AND the gate was on AND the old zone ID is non-empty. Parses RG (`segments[4]`) and zone name (`segments[8]`) from the old zone ID. **Only acts when `orphanRg -ieq $ResourceGroup`** -- we never touch zones in other RGs (could be shared infra). Reads `numberOfRecordSets` + `numberOfVirtualNetworkLinks` via `az network private-dns zone show`. **Empty + unlinked guard:** deletes only if `rsCount -le 1 -and linkCount -eq 0` (<=1 because the SOA always survives). Anything higher -> log a manual `az network private-dns zone delete` command and move on. **Non-fatal on failure** (Section 8 does not depend on this step).
- **Idempotence preserved:** On a clean re-run after success, Section 6c finds zero mismatches (sets `$StaleZoneGroup = $null`, emits `Write-Success "No stale zone group detected"`) and Sections 7b/7c are no-ops. On true first run (no PE yet), Section 6c emits `Write-Info "PE not present yet"` and 7b/7c skip. The patch only does work when there's drift to repair.
- **README updated:** New bullet in "Deployment lessons encoded" explaining the immutability rule + the 6c/7b/7c orchestration. New row in the Inputs table for `FixStaleDnsZoneGroup` (no env var binding by design -- operator must consciously opt in; CI can use `-Force` if it already runs unattended).
- **Terminal output buffering workaround used during live verification:** Multi-line `pwsh + az` calls intermittently returned stale/empty stdout in this shell. Reliable capture pattern: `... -o json *> $env:TEMP\f.json; Get-Content $env:TEMP\f.json -Raw`. Worth remembering for any future diagnostic-against-live-Azure sessions.
- **Did NOT do:** modify `infra/main.bicep`, `infra/modules/private-endpoint.bicep`, `infra/modules/private-dns-zone-vnet-link.bicep`, `talent_infra/`, `talent_infra_v2/`, `shared/common.ps1` (all required helpers -- `Invoke-Native`, `Write-Step/Success/Warn/Info/Fail` -- already present and untouched). Did NOT change server-name auto-detection. Did NOT widen the script to delete unrelated resources (orphan cleanup is empty+unlinked guard only).
- **Generalises to:** Every other PE this stack will eventually add -- same pattern (detect -> fail loud -> repair under switch -> optional orphan cleanup) lifts cleanly to `02-backend` (none yet), `03-frontend` (none yet), and any future Cosmos/Foundry/KeyVault/ACR PE deploys. Captured in the skill drop `azure-pe-dns-zone-group-self-heal/SKILL.md`.


## Archived 2026-05-22T23:45:00Z by Scribe

### 2026-05-22T18:00:00Z — Orphan fragments from Stale PE privateDnsZoneGroup self-heal entry (original tail)

The 2026-05-22T18:00:00Z entry was previously summarized but two trailing list items + a recovery note were left dangling in history.md without a header. Preserved here for completeness:

- (Continuation of Section 7c logic, item 3:) **Attempt zone delete unconditionally** with 2>&1 capture, but treat failure as **non-fatal** (Bicep does not depend on orphan removal) — log a manual-cleanup hint listing the three commands an operator can run after a few minutes for the RP cache to settle.
- **Recovery executed before the patch:** z network private-dns link vnet delete -g rg-talent-devtest-11 --zone-name privatelink.postgres.database.azure.com -n vnet-westus-link --yes (exit 0) → z network private-dns zone delete -g rg-talent-devtest-11 -n privatelink.postgres.database.azure.com --yes (exit 0) → verified empty via z network private-dns zone show -g rg-talent-devtest-11 -n privatelink.postgres.database.azure.com 2>$null.
- **Generalises to:** every Private DNS zone in the stack (cosmos, postgres, cognitive, openai, keyvault, ACR) wherever a PE in the same RG migrates from an in-RG zone to a canonical zone in RG net. Same trap will fire if the discover-and-reuse pattern from 2026-05-22T12:15:00Z is rolled out to other modules.

### 2026-05-22T22:15:00Z — 	alent_infra_modules/01-postgresql/deploy.ps1 Bug 2: z deployment group create JSON-capture stream pollution (Section 8) (original)

- **Symptom (live, same rg-talent-devtest-11 run):** Bicep deployment exited `0` (resources updated successfully in Azure), but immediately after the success banner the script failed with Could not parse az deployment output as JSON. and exited 1, so ` = .properties.outputs` never ran and downstream steps (e.g. `Restart-AzPostgreSqlFlexibleServer` in Section 9) were skipped.
- **Root cause:** The capture was `Invoke-Native { az deployment group create ... --output json 2>&1 }`. `2>&1` interleaves stderr lines into the captured stdout. `az` writes incidental notices to stderr even on success — most commonly "A new Bicep release is available: vX.Y.Z" — plus any ARM diagnostic warnings. Those text lines get joined with the JSON body via `($deployOut -join "`n")` and break `ConvertFrom-Json` with Conversion from JSON failed with error: Unexpected character encountered.
- **Fix (now encoded in Section 8):**
  1. **Stream separation.** Redirect stderr to a per-run file under `/.deploy-logs/{yyyyMMdd-HHmmss}-bicep-stderr.txt` with `2>`; capture stdout-only into ``. Force `-o json` defensively in case the operator has `AZURE_DEFAULTS_OUTPUT=table` in env.
  2. **Validate non-empty BEFORE parsing.** A success exit with empty stdout is itself a bug worth surfacing (`Write-Fail` + point at stderr log) rather than silently NPE'ing on `.properties.outputs`.
  3. **On parse failure, dump to disk — never echo inline.** Bicep stdout can be hundreds of KB and may include resource IDs/connection metadata; `Out-File` it to `{stamp}-bicep-stdout-unparseable.txt`, log both stdout and stderr file paths with `Write-Info`, then `exit 1`. Surface the failure cause; preserve the evidence.
  4. **On non-zero exit, surface stderr inline (small)** plus dump stdout to disk. On success, delete the stderr file (it only holds the Bicep upgrade notice).
  5. **Scrub ` = ` immediately after the capture** (was already in place) so nothing downstream can leak the admin password into a log file.
- **Generalises to:** every `az deployment group create` capture in `talent_infra_modules/*/deploy.ps1` (currently `00-container-apps-env`, `01-postgresql`, `02-backend`, `03-frontend`, `04-data-loading`). The `2>&1` idiom for JSON capture is unsound across the board; this Section-8 shape is the canonical replacement pattern. Lambert may want to sweep the other four folders in a follow-up.

### 2026-05-22T23:00:00Z — 	alent_infra_v2/scripts/test_pg_entra_connection.py made path-aware and PRIVATE-BY-DEFAULT (original)

- **Why this exists:** Anil's previous run of this script against `tiqpg9a6d3.postgres.database.azure.com` succeeded — and that was the problem. The script connected without ever stating which network path it used. The laptop is not VNet-resident and has no Private DNS zone wired in, so the public PaaS FQDN resolved to a public IP (`20.237.146.249`) and the connection traversed the **server-level firewall rule** for the laptop's WAN IP. The PE was being "validated" by a code path that doesn't actually exercise the PE. Same shape as Bug 1 from 22:00 (silent drift between assumed and actual topology) but at the test-tool layer rather than the deploy-script layer.
- **Pattern installed: resolve -> classify -> gate -> connect.** Before anything else (token acquisition, libpq dial), the script now:
  1. **Resolves** the FQDN via `socket.getaddrinfo(host, port, type=SOCK_STREAM)`. System resolver walks the CNAME chain implicitly (`<srv>.postgres.database.azure.com` -> `<srv>.privatelink.postgres.database.azure.com` -> A). Dedupes IPs preserving order.
  2. **Classifies** the **first** returned IP via `ipaddress.ip_address(ip).is_private`. `is_private` covers BOTH RFC1918 (10/8, 172.16/12, 192.168/16) AND RFC6598 CGNAT (100.64/10) in one call — no need to enumerate ranges. Loopback / link-local / multicast / unspecified collapse to `"other"` (refuse to connect). All other IPs are `"public"`.
  3. **Prints a single colored indicator line** stating the resolved IP(s) and the classification — green PRIVATE / red PUBLIC / red OTHER. All resolved IPs are reported (primary + "(+ N more: ...)") so multi-record cases are visible, even though classification is made on the first IP only. Unicode special characters (`\u2014` em-dash, `\u2713` check, `\u26A0` warning, `\u2717` cross) use escape literals to avoid Windows console encoding issues.
  4. **Gates** on classification BEFORE acquiring an Entra token. `"public"` without `--allow-public` -> exit 1 with explicit override instruction. `"other"` -> exit 1 unconditionally (non-routable; refuses). `"public"` with `--allow-public` -> yellow WARNING line + proceed. `"private"` -> silent pass-through, proceed normally.
- **New flags:**
  - `--allow-public` (store_true) — required to opt into public-path connection. The yellow WARNING line names the IP so it's visible in CI logs / scrollback.
  - `--show-path-only` (store_true) — runs steps 1–3 then `return 0` BEFORE touching `acquire_token` or `psycopg2.connect`. Cheap network-only diagnostic that does NOT burn a token. Useful when you just want to confirm "am I VNet-resident from here?" without auth round-trips.
- **Diagnostic threading:** `resolved_classification` is threaded into `test_connection` -> `_diagnose`. When a libpq network error hits AND classification was `"public"`, `_diagnose` adds the targeted hint: `az postgres flexible-server firewall-rule list -g <rg> -n <server>` so the operator immediately knows where to look.
- **Error handling:** DNS failure (`socket.gaierror`) -> exit 1 with the captured exception text and the host name (rather than letting it bubble up as a stack trace). Empty A/AAAA record set -> exit 1 ("No A/AAAA records returned"). Both are caught BEFORE token acquisition so a DNS misconfiguration doesn't waste an Entra round-trip or pollute the orchestration log with a misleading "auth failed" error.
- **Exit code contract preserved:** `0` = success or successful classification (`--show-path-only`); `1` = connection / auth / DNS failure incl. public-without-override; `2` = invalid args. No new exit codes; the public-gate failure deliberately reuses `1` so CI treats it as a connection failure.
- **stdlib-only** for the new logic: `socket` + `ipaddress`. No new wheels. Python 3.10+ syntax (`str | None`, PEP 604) matches the existing file.
- **Live verification (this session, against `tiqpg9a6d3.postgres.database.azure.com` from Anil's laptop, run via `..\..\.venv\Scripts\python.exe`):**
  1. `--show-path-only` -> `Resolved: 20.237.146.249 — PUBLIC path (server-level firewall) ⚠`, exit 0, no `==> Acquiring token` line. ✓
  2. Default (no flags) -> same resolve line, then explicit `ERROR: Resolved to a PUBLIC IP (20.237.146.249). This server should be reached privately.` + override hint, exit 1, no token call. ✓
  3. `--allow-public` -> resolve line, yellow `WARNING: proceeding over PUBLIC path (20.237.146.249) because --allow-public was set.`, then token acquired (`expires in ~69.5 min`), connection succeeded, all sanity queries ran. Interestingly `inet_server_addr()` returned `10.34.0.4` — the backend IS on a private subnet, but the client crossed the public NAT'd PaaS endpoint. The new indicator now makes that divergence impossible to miss.
- **Generalises to:** every probe/test script in the repo that targets an Azure PaaS resource intended to be PE-fronted (PostgreSQL today; same applies to Cosmos, Cognitive, OpenAI, ACR, KeyVault). The resolve->classify->gate pattern is universal — captured as the new skill `azure-pe-test-script-private-default`.


---

### 2026-05-22 - talent_infra_modules/01-postgresql/deploy.ps1 mojibake-cascading parser bug on Windows PowerShell 5.1 + UTF-8-with-BOM mandate (Archived 2026-05-22T23:59:59Z by Scribe)

**Reported by Anil:** adwarakanat2@CXAILABDevBox-3 saw a 30+ line cascade of "Missing closing }", "Missing closing )", "Unexpected token" errors when invoking deploy.ps1, including the smoking-gun mojibake line "nual cleanup (Azure RP cache can lag a EUR'' retry after a few minutes)".

**Root cause confirmed.** talent_infra_modules\01-postgresql\deploy.ps1 was saved as UTF-8 without BOM (file head = 0x3C 0x23 0x0D, no 0xEF 0xBB 0xBF) and contained 2405 non-ASCII characters across 66 lines:

| Codepoint | Glyph | Count | Where |
|---|---|---|---|
| U+2014 | em-dash | 33 | inline prose inside Write-*/comment/quoted strings |
| U+2500 | box-drawing horizontal | 2368 | Section header # ---...--- separators (74 chars/line x ~32 lines) |
| U+2192 | right arrow | 4 | comment text e.g. "script arg -> env var -> prompt" |

**Why it broke 5.1, not pwsh 7+:** Windows PowerShell 5.1 (Desktop, .NET Framework) defaults to the current ANSI codepage (CP1252 on en-US) when reading a .ps1 with no BOM; the UTF-8 byte sequence E2 80 94 (em-dash) becomes the three CP1252 glyphs aEUR''. The trailing quote terminated the enclosing single-quoted string, and every subsequent brace/paren mismatched -> cascade. pwsh 7+ (Core, .NET 8+) defaults to UTF-8 for BOM-less .ps1, so the author never saw the bug. The smoking gun for Anil's reported error is line 509 (Write-Info "Manual cleanup (Azure RP cache can lag - retry after a few minutes):") plus line 368 (em-dash inside a single-quoted string: BLOCKED - rerun with -FixStaleDnsZoneGroup).

**Fix applied (target only - the other 11 .ps1 files in scope deferred per Anil):**
- Fix A - char substitution map applied (codepoint -> ASCII): U+2014 -> " - " (33x), U+2500 -> "-" (2368x), U+2192 -> "->" (4x). Total: 2405 substitutions. No logic changes; no refactoring.
- Fix B - re-saved as UTF-8 with BOM via [System.IO.File]::WriteAllText($path, $text, [System.Text.UTF8Encoding]::new($true)).

**Verification (post-fix):**
- File size: 46189 -> 40552 bytes (smaller because U+2500 = 3 UTF-8 bytes -> 1 ASCII byte saves ~5400).
- First 3 bytes = EF BB BF (BOM present).
- Non-ASCII bytes in content (excluding BOM): 0. Decoded-string non-ASCII char count: 0.
- Line count: 832 (unchanged).
- Parse test pwsh 7.6.1 (Core): PARSE OK.
- Parse test powershell.exe 5.1.26100 (Desktop): PARSE OK.

**Cross-file scan (Bishop''s surface, deferred per Anil''s "only-target-this-round" instruction).** Every .ps1 under talent_infra_modules/, talent_infra/hooks/, talent_infra_v2/hooks/ is NO-BOM with non-ASCII bytes - same latent bug:

| File | Bytes | Non-ASCII bytes |
|---|---|---|
| talent_infra_modules\00-container-apps-env\deploy.ps1 | 23165 | 429 |
| talent_infra_modules\02-backend\deploy.ps1 | 31939 | 6855 |
| talent_infra_modules\03-frontend\deploy.ps1 | 26576 | 5874 |
| talent_infra_modules\04-data-loading\deploy.ps1 | 29502 | 6048 |
| talent_infra_modules\shared\common.ps1 | 31533 | 3789 |
| talent_infra\hooks\postprovision.ps1 | 63131 | 246 |
| talent_infra\hooks\postup.ps1 | 10106 | 63 |
| talent_infra\hooks\preprovision.ps1 | 5571 | 9 |
| talent_infra_v2\hooks\postprovision.ps1 | 64888 | 249 |
| talent_infra_v2\hooks\postup.ps1 | 10106 | 63 |
| talent_infra_v2\hooks\preprovision.ps1 | 5571 | 9 |

These 11 files are tracked for a follow-up sweep. The other 10 modules likely fail on 5.1 too (02-backend and 03-frontend carry the most non-ASCII per byte - high mojibake risk).

**Prevention (recommended, not yet committed - awaits Lambert review):**
1. .editorconfig rule: [*.ps1] + charset = utf-8-bom.
2. .vscode/settings.json: "[powershell]": { "files.encoding": "utf8bom" }.
3. Pre-commit hook (optional): scan .ps1 files for missing BOM before commit.

**Skill candidate:** This bug class (UTF-8 no-BOM + non-ASCII + PS 5.1) is generic enough to lift into a reusable skill powershell-utf8-bom-for-5.1-compat - flagged for Lambert review.

**Files touched:** talent_infra_modules\01-postgresql\deploy.ps1 (encoding + chars only; zero logic change). Tmp helper scripts deleted.

---

### 2026-05-22T23:59:30Z - GitGuardian remediation: 01-postgresql/deploy.ps1 .EXAMPLE literal-password scrub (Archived 2026-05-22T23:59:59Z by Scribe)

GitGuardian flagged ConvertTo-SecureString "P@ssw0rd!Strong!" -AsPlainText -Force at talent_infra_modules/01-postgresql/deploy.ps1:43 (pushed 2026-05-22T22:58:37Z, present in commits 69af3ac and HEAD cbb8b23). Literal lived inside the script-header .EXAMPLE block - pure documentation, never an active credential. Fix: rewrote the example to use Read-Host -AsSecureString -Prompt "Postgres admin password" (better security guidance - nothing lands in shell history, scripts, or CI logs; also leverages shared/common.ps1::Get-ParameterValue''s built-in Read-Host fallback when -AdminPassword is omitted). Added a CI guidance block with the <your-strong-password> angle-bracket placeholder pattern for cases where documentation must show the ConvertTo-SecureString form. Working-tree grep for the literal -> 0 matches. PowerShell parse -> 0 errors.

**Three lessons that go beyond this single file:**

1. **.EXAMPLE blocks ARE production surface for secret scanners.** PowerShell Get-Help surfaces them verbatim, operators copy-paste them into terminals, and tools like GitGuardian regex on shape, not intent. A plausible-looking literal in .EXAMPLE is functionally a hardcoded credential. New rule: literal strings inside ConvertTo-SecureString "..." are forbidden anywhere a script can be committed. Only the four allowed shapes: (a) Read-Host -AsSecureString, (b) Get-AzKeyVaultSecret, (c) variable from secret-store at call site, (d) <angle-bracket-placeholder> in pure-doc comments. Captured in decision 2026-05-22T23:59:30Z.

2. **shared/common.ps1 ConvertTo-SecureString call sites are NOT the same hazard.** Lines 195/206/225 convert a variable ($Value, $envVal, $Default) to SecureString. The dangerous pattern is literal string between the quotes. Scanners distinguish; reviewers should too. Future Lambert sweeps: regex ConvertTo-SecureString\s+["][^<\$].*["].*-AsPlainText - the [^<\$] negation excludes both angle-bracket placeholders and variable references.

3. **The two .env files found with literal Postgres password under talent_infra_v2/.azure/talent-devtest-v{2,8}/ were a false alarm - gitignored by talent_infra_v2/.azure/.gitignore line 2 (* wildcard), git log --all -S "<literal>" returns zero commits. Local-dev azd state only.** That said: any future azd env or .outputs.json written under talent_infra_*/.azure/ MUST be gitignored at the parent-folder level - never per-file - because azd generates these on azd env new and they bypass any per-file .gitignore we''d add reactively. The wildcard * pattern in talent_infra_v2/.azure/.gitignore is the correct shape; if a future toolkit (talent_infra_v3, etc.) is added, the same wildcard MUST be in its .azure/.gitignore on day one.

**Operator action required (NOT done by Bishop - Anil controls git operations):** see remediation runbook delivered inline 2026-05-22. Recommended: accept the exposure (the literal was never an active credential), rotate-as-precaution only if the value is actively used anywhere (it is not - confirmed via grep across .env + .outputs.json files), resolve GitGuardian alert as "doc example, no real impact." Optional: install gitleaks pre-commit hook to catch the next one before push.

**Cross-toolkit guardrail (forward-looking):** Every future talent_infra_*/ script that takes a -SecureString parameter MUST:
- Default to Read-Host -AsSecureString in its .EXAMPLE block.
- Document the Get-AzKeyVaultSecret form for CI.
- Treat any literal between ConvertTo-SecureString "..." quotes as a bug - fail review.
This rule is codification-grade and should be applied to every 00-*/, 01-*/, 02-*/, ... module in any current or future toolkit.

### 2026-05-22 — 11-file `.ps1` UTF-8-with-BOM sweep (executes the deferred Decision `2026-05-22T23:59:59Z`)

> Archived 2026-05-23T00:30:00Z by Scribe. Moved here from `history.md` after the entry drove bishop/history.md over the 15KB threshold. Brief stub remains in `history.md`.

Anil mandate (acting urgently because `adwarakanat2@CXAILABDevBox-3` was hitting the same cascading parser bug fixed on `01-postgresql/deploy.ps1` two days prior, now in `shared/common.ps1`). Built single-pass sweep helper `.scratch/ps1_utf8bom_sweep.ps1` applying Fix A (ASCII substitution per fixed codepoint map) + Fix B (`[System.IO.File]::WriteAllText` with `[System.Text.UTF8Encoding]::new($true)` BOM). Atomic fail-fast: throw BEFORE write on unknown codepoints; throw AFTER write on parse-test failure. Dual-engine parse verification via external-process `[scriptblock]::Create((Get-Content -Raw))` in both `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe` (PS 5.1.26100, source-of-bug) AND `C:\Program Files\WindowsApps\Microsoft.PowerShell_7.6.1.0_x64__8wekyb3d8bbwe\pwsh.exe` (PS 7.6.1, tolerant). **Result: 11/11 files swept clean.** All have BOM `EF BB BF`, 0 non-ASCII bytes, parse OK in pwsh 7+. Per-file char-substitution totals (top contributors): `04-data-loading/deploy.ps1` 2016, `03-frontend/deploy.ps1` 1958, `00-container-apps-env/deploy.ps1` 143, `postprovision.ps1` (both copies) 82/83 each, `postup.ps1` (both copies) 21 each, `preprovision.ps1` (both copies) 3 each — total 4330 chars substituted. `shared/common.ps1` and `02-backend/deploy.ps1` reported 0 chars in this final sweep because `shared/common.ps1` was already fixed in an earlier run-1 pass and `02-backend/deploy.ps1` in an earlier run-2 pass — both are confirmed BOM+ASCII on disk; the final-run delta=0 just means idempotent re-processing was a no-op. **Surprises found beyond standard 12-entry map** (added to extended 18-entry map after a one-pass enumeration of all 11 files via `.scratch/enumerate_nonascii.ps1` + context disambiguation via `.scratch/context_surprises.ps1`): U+2194 ↔ → `<->`, U+2550 ═ → `=`, U+2588 █ → `#`, U+26A0 ⚠ → `[WARN]`, U+2705 ✅ → `[OK]`, U+2713 ✓ → `[OK]`. **One asymmetry — PS 7+ language dependency surfaced by the encoding fix**: `talent_infra_modules/02-backend/deploy.ps1` uses `?.` null-conditional (2x, lines 100 and 343) and `??` null-coalesce (1x). PS 5.1 cannot parse these regardless of encoding. HEAD version of the file ALSO failed PS 5.1 parse (with mojibake errors at lines 119/318/319/321/533/534) — so the encoding fix STRICTLY IMPROVES the file: mojibake red-herrings gone, the genuine PS 7+ dependency is now visible. Recorded as `EXPECT_FAIL_PS7_ONLY` in the sweep report. **Survey via `.scratch/survey_ps7_syntax.ps1` confirmed only `02-backend/deploy.ps1` uses PS 7+-only syntax** — the other 10 files all parse clean in both engines. This is consistent with `01-postgresql/deploy.ps1` line 43 documenting `pwsh ./deploy.ps1` as the invocation pattern (all `talent_infra_modules/*/deploy.ps1` deployers target pwsh 7+). **Prevention guards added** per decision: `.editorconfig` (root=true, `[*.ps1]` charset=utf-8-bom, end_of_line=crlf, insert_final_newline=true) + `.vscode/settings.json` (`"[powershell]": { "files.encoding": "utf8bom" }`). VS Code will now save new `.ps1` files with BOM by default. **Repo-wide scan** (informational, out of decision scope): 12 `.ps1` files now have BOM (11 swept + `01-postgresql/deploy.ps1` already fixed); 15 BOM-less remain — 8 are `_tmp_*.ps1` author-scratch in repo root (ASCII-only, harmless); 4 are admin/test scripts under `talent_infra*/scripts/` (ASCII-only); 1 is `talentiq_requirements/reference_code/azd_deploy/hooks/*.ps1` (reference snapshots, ASCII-only); 2 have non-ASCII bytes and remain at risk for the same bug under PS 5.1: `.squad/templates/skills/distributed-mesh/sync-mesh.ps1` (template) and `talent_infra_v2/scripts/Purge-SoftDeletedFoundryAccounts.ps1` (standalone admin). Flagged for follow-up; not in this decision's 11-file scope. **Helpers deleted from `.scratch/`** post-sweep: `ps1_utf8bom_sweep.ps1`, `enumerate_nonascii.ps1`, `context_surprises.ps1`, `parse_test.ps1`, `survey_ps7_syntax.ps1`. Decisions-inbox completion note dropped at `.squad/decisions/inbox/bishop-ps1-sweep-complete.md` (merged + deleted by Scribe in the same pass as this archival, see `decisions.md 2026-05-23T00:30:00Z`). **adwarakanat2 unblocker**: `git pull` + retry `pwsh talent_infra_modules\01-postgresql\deploy.ps1` (or any other module) on his box — `shared/common.ps1` will now dot-source clean in PS 5.1 AND pwsh 7+.


---

## Archived 2026-05-22 by Scribe (Tier: per-agent history >= 15360 bytes)

### 2026-05-22 — 11-file sweep ROLLBACK + 12-file BYTE-LEVEL re-sweep (sweep methodology hardened)

Anil hit `Get-ParameterValue: A positional parameter cannot be found that accepts argument ''.` running `talent_infra_modules/01-postgresql/deploy.ps1`. **Root cause of runtime bug:** the previous sweep (committed in `53a94e9` "security: remediate GitGuardian leak") used a **regex** that matched `\s+-\w+` across the whole file text, which incorrectly mangled ASCII PowerShell parameter prefixes ( `    -Value`, `    -EnvVar`, `    -Default`) into ` - Value`, ` - EnvVar`, ` - Default`. PowerShell then parsed `-` as a positional arg and the parameter name as its value. 5 such regressions hit lines 122-131 of `01-postgresql/deploy.ps1`.

**Per Anil's 11-step plan**: rolled back ALL 11 swept `.ps1` files via `git checkout HEAD --`, rebuilt the sweep helper at **byte-level (codepoint ≥ 0x80)** so ASCII is ALWAYS passthrough, re-swept all 11 files clean. **Discovered mid-sweep** that `01-postgresql/deploy.ps1` HEAD is ALREADY broken (regression baked into `53a94e9`); rollback to HEAD does NOT restore good source — had to pull pristine pre-sweep version from `HEAD~2` (`cbb8b23`) to make this the **12th file** swept. **Encountered and fixed second-order bug**: `git show HEAD~2:<path>` piped through PowerShell stdout decodes UTF-8 multi-byte sequences via console code page (CP1252), producing double-encoded mojibake (em-dash `E2 80 94` → Γ ö Ç = U+0393, U+00F6, U+00C7) — fixed by using `cmd.exe /c "git show ... > tempfile"` for byte-level redirect, then `[System.IO.File]::ReadAllBytes($tmp)` + em-dash-byte-sequence assertion to guard against silent capture corruption.

**Final state (12/12 swept clean):** `shared/common.ps1` 1263 subs, `01-postgresql/deploy.ps1` 2405 subs (re-sweep from HEAD~2), `02-backend/deploy.ps1` 2285 subs, `03-frontend/deploy.ps1` 1958 subs, `04-data-loading/deploy.ps1` 2016 subs, `00-container-apps-env/deploy.ps1` 143 subs, `talent_infra/hooks/postprovision.ps1` 82 subs, `talent_infra_v2/hooks/postprovision.ps1` 83 subs, `talent_infra/hooks/postup.ps1` 21 subs, `talent_infra_v2/hooks/postup.ps1` 21 subs, `talent_infra/hooks/preprovision.ps1` 3 subs, `talent_infra_v2/hooks/preprovision.ps1` 3 subs. All BOM `EF BB BF` verified. 0 unknown codepoints across all files. 0 residual non-ASCII bytes. **Step 7 regression smoke test (` - Word` pattern):** 0 real regressions; 1 hit in `shared/common.ps1` line 482 verified as benign comment-help-block prose (originally em-dash separator, correctly substituted to ` - `). **Step 8 dual-engine parse:** all 12 PASS pwsh 7+; 11/12 PASS Windows PowerShell 5.1; `02-backend/deploy.ps1` FAILS PS 5.1 due to pre-existing `?.` + `??` pwsh-7+-only syntax (NOT an encoding regression — tagged `EXPECT_FAIL_PS7_ONLY`, consistent with previous sweep). **Step 9 visual confirmation:** `01-postgresql/deploy.ps1` lines 118-135 show every `Get-ParameterValue` continuation with correct `    -Value $X -EnvVar "Y" -Default "Z"` shape. Per Anil's Step 11: **DO NOT COMMIT** — all 12 swept files left unstaged. Anil owns the code commit. Decision inbox file `.squad/decisions/inbox/bishop-ps1-sweep-byte-level-fix.md` proposes the byte-level mandate to supersede the implementation contract of `2026-05-23T00:30:00Z` (rule statement unchanged).


