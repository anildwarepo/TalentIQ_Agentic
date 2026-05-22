# Bishop — History

> Older entries archived to `history-archive.md` on 2026-05-21 by Scribe (originally truncated 2026-05-16; 2026-05-22 pass moved 2026-05-21 deep-dive Learnings).

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

### 2026-05-12: Passes 1–3 — initial infra (Archived)
Built complete infra in 3 passes: networking foundation → data/supporting services → Container App workloads + UAMI + RBAC. Also created deployment runbook and fixed MCP Dockerfile override in azure.yaml. **See history-archive.md.**

### 2026-05-16: Passes 4–5 — rebuild then reference-pattern alignment (Archived)
Pass 4 rebuilt entire `talent_infra/` (17 files lost to disk) from this history as blueprint; Bicep validation zero diagnostics. Pass 5 then deleted everything and rebuilt to match `talentiq_requirements/reference_code/azd_deploy/` — two-phase deploy (azd provision + postprovision hook), Bicep moved under `talent_infra/infra/`, password-PG for dev parity, Cosmos added, AGE+VECTOR+PG_TRGM extensions, 13 modules + 4 hook scripts. **Full design decisions + learnings in history-archive.md.**

### 2026-05-21: `talent_infra_modules/` — per-component deploy chain (this session)
Owned three of the four component folders:

- **01-postgresql/** — standalone PG Flex Server deployer. `deploy.ps1` + `infra/main.bicep` + parameters + verbatim copies of v2's `postgresql-flexible-server.bicep` and `private-endpoint.bicep` under `infra/modules/`. Folder is self-contained — no `../../talent_infra_v2/...` paths. Bicep compiles zero-diagnostics. Admin registration moved out of Bicep into deploy.ps1 control-plane calls (avoids `AadAuthOperationCannotBePerformedWhenServerIsNotAccessible` re-PUT race). Deterministic server name `tiqpg<sha5>` from `subId|rg|location`. Emits `.outputs.json` consumed by 02-backend and 04-data-loading.
- **02-backend/** — Container App + MCP sidecar sharing one UAMI. `deploy.ps1` + `infra/main.bicep` + parameters + `infra/modules/container-app.bicep` + `.acrignore`. Bicep validation passed (1 cosmetic `use-safe-access` warning preserved for parity with v2). Reads `01-postgresql/.outputs.json`; same-RG fail-fast on AcrResourceGroup/FoundryResourceGroup/CosmosResourceGroup mismatches. `az acr build` for both Dockerfile + Dockerfile.mcp. Post-deploy control-plane PG admin registration using `--display-name <UAMI-name>` (display-name == UAMI name == PGUSER). Emits `.outputs.json` consumed by 03-frontend and 04-data-loading.
- **04-data-loading/** — terminal step. Pure local Python invocation, no Bicep. `deploy.ps1` (~510 lines) reads 01 and 02 outputs, acquires OSSRDBMS Entra token, snapshots/restores all `PG*`/`GRAPH_NAME`/`AZURE_OPENAI_*`/`FORCE_REGENERATE` env vars in `try/finally`, pipes idempotent extension+graph SQL through psql, runs `python -m talent_data_pipeline.main`. `-NarrowBackendGrants` (opt-in) invokes `talent_infra_v2/scripts/provision_pg_entra_roles.py` AS-IS. `-RestartBackend` (opt-in) restarts the active revision. No `.outputs.json` (terminal). README.md was pre-authored.

**Files produced this session (all under `talent_infra_modules/`):** 3 deploy.ps1 files + 3 `infra/main.bicep` + 3 parameter files + module copies (postgresql, private-endpoint, container-app) + 1 `.acrignore`. Plus the shared `AUTH-DISABLED.md`, `DEPLOYMENT-ORDER.md`, `README.md` from prior turns.

**See history-archive.md for the full per-folder flow narratives and the ~25 learnings (cross-RG BCP139/BCP120, AZURE_TENANT_ID omission contract, PE detection via private IP, deterministic naming SHA recipes, psql here-string dollar-quoting, env-var hygiene, etc.).**

## Learnings

> Deep-dive Learnings entries from 2026-05-21 (PowerShell case-insensitive shadowing in `Get-ParameterValue`; 00-container-apps-env follow-on silent-success postmortem; Postgres SKU/tier parity for `01-postgresql/`) moved to `history-archive.md` on 2026-05-22 by Scribe. Two additional 2026-05-22 entries (T00:00:00Z asymmetric-RBAC prereq checks; T12:15:00Z Private DNS zone discover-and-reuse) archived later same day after history.md exceeded 15KB.

### 2026-05-22T00:00:00Z — Asymmetric RBAC: `az resource show` vs `az <rp> show` for prereq checks (Archived)

Prereq existence checks under `talent_infra_modules/` should use resource-provider-specific `az <rp> show` calls (e.g. `az network vnet show`) rather than the generic `az resource show`, because the RP-specific call needs the same RBAC the deploy itself needs — passing the prereq guarantees the deploy can also see the resource. Fix already shipped in `shared/common.ps1::Test-VnetExists` + `Assert-PrerequisitesExist`'s `'vnet'` branch. **See `history-archive.md` for the full symptom/root-cause/applies-to writeup.**

### 2026-05-22T12:15:00Z — Private DNS zone discover-and-reuse (overlapping-namespaces fix, Archived)

Azure enforces at most one Private DNS zone per namespace per VNet. The fix added `Get-LinkedPrivateDnsZoneId` + `Get-PrivateDnsZoneIdByName` helpers to `shared/common.ps1`, wired a Section 6b discovery pass into `01-postgresql/deploy.ps1`, and added an `existingPrivateDnsZoneLinked` Bicep param + a new `private-dns-zone-vnet-link.bicep` module so unlinked existing zones can be reused. Pattern applies to every PaaS PE in the stack. **See `history-archive.md` for the full validation transcript, helper signatures, and Bicep wiring detail.**

### 2026-05-22T00:30:00Z — ARM/Bicep parameter files reject non-DeploymentParameter keys

- ARM/Bicep parameter files reject any top-level key under `parameters` that isn't a `{value: ...}` DeploymentParameter — no `_comment_*` keys, no JSON comments. Use `@description()` on Bicep `param` declarations for inline docs. (Symptom: `az deployment ... validate` failed in `01-postgresql/` with `Unable to deserialize response data ... {DeploymentParameter}` after a `_comment_sku` string was added next to `skuName`. Fix: deleted the comment key; Bicep already has the description on the `param skuName` decorator.)

## Cross-agent note — 2026-05-21 (Scribe)
- **Auth-disable contract is a two-agent deliverable.** Bishop owns the Container App env-vars + deploy scripts (omit `AZURE_TENANT_ID` on backend; pass `VITE_DISABLE_AUTH=true` to the frontend Docker build); Dallas owns the React source change (conditional `<MsalProvider>`, suppressed bearer header, synthetic demo account in `talent_ui/`). Both halves must move together to deliver the "auth-off demo deploy" promised by `talent_infra_modules/AUTH-DISABLED.md`. Changing the contract requires coordinated edits across both surfaces — never one in isolation.
- **Lambert APPROVED the talent_infra_modules/ output (2026-05-21).** All 6 hazards from `/memories/repo/talentiq-azd-deploy.md` covered; all `.bicep` files compile; all `.ps1` files parse zero errors; `.outputs.json` schema consistent across folder boundaries. Three WARN-level cosmetic findings logged but non-blocking. No Reviewer Rejection Protocol invoked.
- **00-container-apps-env shipped (2026-05-21, later).** The toolkit is now 5 components (`00 + 01-04`) and self-contained end-to-end on greenfield environments. Decision recorded under coordinator-recovered attribution; see Work Log entry above for the silent-success postmortem.

### 2026-05-22T18:00:00Z — Stale PE `privateDnsZoneGroup` self-heal in `01-postgresql/deploy.ps1`

- **Symptom (live on `rg-talent-devtest-11`):** Redeploy after the 6b discover-and-reuse patch failed with `UpdatingPrivateDnsZoneIdOnPrivateDnsZoneConfigNotAllowed`. PE `tiqpg9a6d3-pe` already had a `default` zone group with config `privatelink-postgres-database-azure-com` pointing at an orphan zone in `rg-talent-devtest-11` (created in-place by the pre-fix PE itself, 1 A record `tiqpg9a6d3 → 10.0.4.16`). The current run resolves the canonical zone in RG `vnet` (2 record sets, 1 link). Bicep tries to in-place mutate `privateDnsZoneConfigs[*].properties.privateDnsZoneId` — Azure forbids it. **No Bicep edits could fix this** because the constraint is at the ARM/Network-RP layer, not the template.
- **Azure rule (load-bearing):** `privateDnsZoneConfigs.properties.privateDnsZoneId` is **immutable** on an existing `privateDnsZoneGroup`. The ONLY way to repoint a PE's zone group at a different Private DNS zone is to **delete the parent `privateDnsZoneGroup`** (always named `default` on PEs created from `private-endpoint.bicep`, but read from the API not hardcoded) and let the next deploy recreate it. This generalises to every PE in the stack — Cosmos, Foundry, KeyVault, ACR all hit it the same way on environments with pre-pattern artifacts.
- **Fix — script side only, no Bicep changes:**
  - **New param `-FixStaleDnsZoneGroup` (switch)** in `deploy.ps1` `param()` block, sits right before `[switch]$Force`. `-Force` implies it (so existing CI doesn't need to learn a new switch). Documentation comment in-line referencing Sections 6c and 7b.
  - **Section 6c (detection, read-only)** between 6b zone discovery and Section 7 confirm. Probes `az network private-endpoint show -g $rg -n "${ServerName}-pe" 2>$null`; first-run safe (exit≠0 or empty body → log "PE not present yet" and skip). Lists zone groups via `az network private-endpoint dns-zone-group list`. For each config, case-insensitive compares `privateDnsZoneId` to the resolved `$ExistingDnsZoneId` using `-ieq`. On mismatch, sets `$StaleZoneGroup` + `$StaleZoneGroupOldZoneId` and breaks the outer loop (one mismatch is enough to trigger the repair). Read-only — no destructive action here.
  - **Section 7 plan summary** got two new yellow lines surfacing the planned repair: the stale zone group name + the gate status (`auto-approved (-FixStaleDnsZoneGroup or -Force)` vs `BLOCKED — rerun with -FixStaleDnsZoneGroup`).
  - **Section 7b (act)** between Confirm-Action and Bicep deploy. If `$null -ne $StaleZoneGroup` AND not (`$FixStaleDnsZoneGroup -or $Force`) → `Write-Fail` with rerun instructions and `exit 1` (fail loud — don't silently let Bicep error half-way). If gated, runs `az network private-endpoint dns-zone-group delete -g $rg --endpoint-name $peName -n $StaleZoneGroup --output none` (the `--yes` flag does **not** exist on this subcommand and was removed during design — only on `private-dns zone delete`). Checks `$LASTEXITCODE`; exit 1 on failure with the captured stderr indented under the error line.
  - **Section 7c (orphan-zone best-effort cleanup)** runs ONLY when 7b actually deleted a stale group AND the gate was on AND the old zone ID is non-empty. Parses RG (`segments[4]`) and zone name (`segments[8]`) from the old zone ID. **Only acts when `orphanRg -ieq $ResourceGroup`** — we never touch zones in other RGs (could be shared infra). Reads `numberOfRecordSets` + `numberOfVirtualNetworkLinks` via `az network private-dns zone show`. **Empty + unlinked guard:** deletes only if `rsCount -le 1 -and linkCount -eq 0` (≤1 because the SOA always survives). Anything higher → log a manual `az network private-dns zone delete` command and move on. **Non-fatal on failure** (Section 8 doesn't depend on this step).
- **Idempotence preserved:** On a clean re-run after success, Section 6c finds zero mismatches (sets `$StaleZoneGroup = $null`, emits `Write-Success "No stale zone group detected"`) and Sections 7b/7c are no-ops. On true first run (no PE yet), Section 6c emits `Write-Info "PE not present yet"` and 7b/7c skip. The patch only does work when there's drift to repair.
- **README updated:** New bullet in "Deployment lessons encoded" explaining the immutability rule + the 6c/7b/7c orchestration. New row in the Inputs table for `FixStaleDnsZoneGroup` (no env var binding by design — operator must consciously opt in; CI can use `-Force` if it already runs unattended).
- **Terminal output buffering workaround used during live verification:** Multi-line `pwsh + az` calls intermittently returned stale/empty stdout in this shell. Reliable capture pattern: `... -o json *> $env:TEMP\f.json; Get-Content $env:TEMP\f.json -Raw`. Worth remembering for any future diagnostic-against-live-Azure sessions.
- **Did NOT do:** modify `infra/main.bicep`, `infra/modules/private-endpoint.bicep`, `infra/modules/private-dns-zone-vnet-link.bicep`, `talent_infra/`, `talent_infra_v2/`, `shared/common.ps1` (all required helpers — `Invoke-Native`, `Write-Step/Success/Warn/Info/Fail` — already present and untouched). Did NOT change server-name auto-detection. Did NOT widen the script to delete unrelated resources (orphan cleanup is empty+unlinked guard only).
- **Generalises to:** Every other PE this stack will eventually add — same pattern (detect → fail loud → repair under switch → optional orphan cleanup) lifts cleanly to `02-backend` (none yet), `03-frontend` (none yet), and any future Cosmos/Foundry/KeyVault/ACR PE deploys. Captured in the skill drop `azure-pe-dns-zone-group-self-heal/SKILL.md`.
