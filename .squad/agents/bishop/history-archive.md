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
