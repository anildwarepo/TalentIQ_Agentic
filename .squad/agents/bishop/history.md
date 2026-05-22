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

### 2026-05-21: `talent_infra_modules/` — per-component deploy chain (Archived)
Authored `01-postgresql/`, `02-backend/`, `04-data-loading/`: self-contained `deploy.ps1` + Bicep + module copies per folder; `.outputs.json` hand-off chain; control-plane PG admin registration; same-RG fail-fast on cross-RG ACR/Foundry/Cosmos mismatches. Bicep zero-diagnostics; PowerShell zero parse errors; Lambert APPROVED. **See history-archive.md (2026-05-21 entry) for full per-folder breakdown + ~25 learnings.**

## Learnings

> Older Learnings (2026-05-21 PowerShell case-insensitive shadowing in `Get-ParameterValue`, 00-container-apps-env silent-success postmortem, Postgres SKU/tier parity; 2026-05-22T00:00:00Z asymmetric-RBAC prereq checks; 2026-05-22T12:15:00Z Private DNS zone discover-and-reuse; 2026-05-22T00:30:00Z ARM/Bicep param-file no-comment rule) moved to `history-archive.md` by Scribe. All patterns also codified in `.squad/decisions.md` (search by ISO date) and reusable skills under `.squad/skills/`.

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
- **Terminal output buffering workaround used during live verification:** Multi-line `pwsh + az`  (Archived)

Azure forbids in-place mutation of `privateDnsZoneConfigs[*].properties.privateDnsZoneId` (`UpdatingPrivateDnsZoneIdOnPrivateDnsZoneConfigNotAllowed`) — script-only fix (Bicep cannot recover). Added `[switch]$FixStaleDnsZoneGroup` (umbrella `-Force` implies) + Section 6c read-only detection + Section 7b gated delete + Section 7c best-effort orphan-zone cleanup (same-RG + `rsCount -le 1 -and linkCount -eq 0` guards). Bicep surface untouched. Pattern is normative for every PE-bearing module — see decisions.md `2026-05-22T18:00:00Z` and `.squad/skills/azure-pe-dns-zone-group-self-heal/SKILL.md`. **See history-archive.md for full root-cause + section-by-section walkthrough + live verification transcript.**
  3. **Attempt zone delete unconditionally** with `2>&1` capture, but treat failure as **non-fatal** (Bicep does not depend on orphan removal) — log a manual-cleanup hint listing the three commands an operator can run after a few minutes for the RP cache to settle.
- **Recovery executed before the patch:** `az network private-dns link vnet delete -g rg-talent-devtest-11 --zone-name privatelink.postgres.database.azure.com -n vnet-westus-link --yes` (exit 0) → `az network private-dns zone delete -g rg-talent-devtest-11 -n privatelink.postgres.database.azure.com --yes` (exit 0) → verified empty via `az network private-dns zone show -g rg-talent-devtest-11 -n privatelink.postgres.database.azure.com 2>$null`.
- **Generalises to:** every Private DNS zone in the stack (cosmos, postgres, cognitive, openai, keyvault, ACR) wherever a PE in the same RG migrates from an in-RG zone to a canonical zone in RG `vnet`. Same trap will fire if the discover-and-reuse pattern from 2026-05-22T12:15:00Z is rolled out to other modules.

### 2026-05-22T22:15:00Z — `talent_infra_modules/01-postgresql/deploy.ps1` Bug 2: `az deployment group create` JSON-capture stream pollution (Section 8)

- **Symptom (live, same rg-talent-devtest-11 run):** Bicep deployment exited `0` (resources updated successfully in Azure), but immediately after the success banner the script failed with `Could not parse az deployment output as JSON.` and exited 1, so `$bicepOutputs = $deployJson.properties.outputs` never ran and downstream steps (e.g. `Restart-AzPostgreSqlFlexibleServer` in Section 9) were skipped.
- **Root cause:** The capture was `Invoke-Native { az deployment group create ... --output json 2>&1 }`. `2>&1` interleaves stderr lines into the captured stdout. `az` writes incidental notices to stderr even on success — most commonly "A new Bicep release is available: vX.Y.Z" — plus any ARM diagnostic warnings. Those text lines get joined with the JSON body via `($deployOut -join "`n")` and break `ConvertFrom-Json` with `Conversion from JSON failed with error: Unexpected character encountered`.
- **Fix (now encoded in Section 8):**
  1. **Stream separation.** Redirect stderr to a per-run file under `$scriptDir/.deploy-logs/{yyyyMMdd-HHmmss}-bicep-stderr.txt` with `2>$stderrLog`; capture stdout-only into `$deployOut`. Force `-o json` defensively in case the operator has `AZURE_DEFAULTS_OUTPUT=table` in env.
  2. **Validate non-empty BEFORE parsing.** A success exit with empty stdout is itself a bug worth surfacing (`Write-Fail` + point at stderr log) rather than silently NPE'ing on `$deployJson.properties.outputs`.
  3. **On parse failure, dump to disk — never echo inline.** Bicep stdout can be hundreds of KB and may include resource IDs/connection metadata; `Out-File` it to `{stamp}-bicep-stdout-unparseable.txt`, log both stdout and stderr file paths with `Write-Info`, then `exit 1`. Surface the failure cause; preserve the evidence.
  4. **On non-zero exit, surface stderr inline (small)** plus dump stdout to disk. On success, delete the stderr file (it only holds the Bicep upgrade notice).
  5. **Scrub `$plainPw = $null` immediately after the capture** (was already in place) so nothing downstream can leak the admin password into a log file.
- **Generalises to:** every `az deployment group create` capture in `talent_infra_modules/*/deploy.ps1` (currently `00-container-apps-env`, `01-postgresql`, `02-backend`, `03-frontend`, `04-data-loading`). The `2>&1` idiom for JSON capture is unsound across the board; this Section-8 shape is the canonical replacement pattern. Lambert may want to sweep the other four folders in a follow-up.


## Cross-agent note — 2026-05-22T22:30:00Z (Scribe)
- **Model directive (Anil, captured 2026-05-22T18:30:00Z):** all squad spawns — including Scribe and Ralph, including any agent normally defaulted to a fast/cheap tier — MUST use `claude-opus-4.6-1m` (Opus 4.7 Extra-high reasoning). `.squad/config.json` `defaultModel` is the source of truth; the "never bump Scribe" rule is overridden. Per `decisions.md` `2026-05-22T18:30:00Z`.
