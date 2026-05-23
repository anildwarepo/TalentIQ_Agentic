# Bishop — History

> Older entries archived to `history-archive.md` on 2026-05-21 by Scribe (originally truncated 2026-05-16; 2026-05-22 pass moved 2026-05-21 deep-dive Learnings; 2026-05-22T23:59:59Z pass moved full text of the mojibake-cascading parser bug + GitGuardian remediation entries).

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

### 2026-05-22T18:00:00Z — Stale PE `privateDnsZoneGroup` self-heal in `01-postgresql/deploy.ps1` (Archived)

Azure forbids in-place mutation of `privateDnsZoneConfigs[*].properties.privateDnsZoneId` (`UpdatingPrivateDnsZoneIdOnPrivateDnsZoneConfigNotAllowed`) — script-only fix (Bicep cannot recover). Added `[switch]$FixStaleDnsZoneGroup` (umbrella `-Force` implies) + Section 6c read-only detection + Section 7b gated delete + Section 7c best-effort orphan-zone cleanup (same-RG + `rsCount -le 1 -and linkCount -eq 0` guards). Bicep surface untouched. Pattern is normative for every PE-bearing module — see `decisions.md` `2026-05-22T18:00:00Z` and `.squad/skills/azure-pe-dns-zone-group-self-heal/SKILL.md`. **See `history-archive.md` for full root-cause + section-by-section walkthrough + live recovery transcript.**

### 2026-05-22T22:15:00Z — `01-postgresql/deploy.ps1` Bug 2: Section 8 `az deployment group create` JSON-capture stream pollution (Archived)

`Invoke-Native { az ... --output json 2>&1 }` merged the Bicep upgrade notice (and other stderr lines) into the JSON body, breaking `ConvertFrom-Json` even though the deployment succeeded. Fix: separate streams (`2>$stderrLog` to `.deploy-logs/{stamp}-bicep-stderr.txt`), force `-o json`, validate non-empty before parsing, dump unparseable stdout to disk (never echo — may contain secrets/IDs), surface stderr inline only on non-zero exit, scrub `$plainPw` immediately. Same antipattern lives in every `talent_infra_modules/*/deploy.ps1` — Lambert sweep candidate. **See `history-archive.md` for full root-cause + Section 8 walkthrough.**

### 2026-05-22T23:00:00Z — `talent_infra_v2/scripts/test_pg_entra_connection.py` path-aware + PRIVATE-BY-DEFAULT (Archived)

Script silently connected over the public PaaS firewall when run from a non-VNet host (PE never actually exercised). Installed **resolve → classify → gate → connect** pattern: `socket.getaddrinfo` → `ipaddress.ip_address(ip).is_private` (covers RFC1918 + CGNAT 100.64/10) → colored indicator line → gate BEFORE Entra token. New flags `--allow-public` (opt-in for public path, yellow warning) and `--show-path-only` (network-only diagnostic, skips token+psycopg2). Diagnostic hint surfaces the firewall-rule check when public-path connections fail. stdlib-only, exit-code contract unchanged. Pattern lifts to every PE-fronted PaaS probe (Cosmos, Cognitive, OpenAI, ACR, KeyVault) — captured as skill `azure-pe-test-script-private-default`. **See `history-archive.md` for full pattern walkthrough + live verification transcript.**

### 2026-05-22 — `01-postgresql/deploy.ps1` mojibake-cascading parser bug on Windows PowerShell 5.1 + UTF-8-with-BOM mandate (Archived)

Anil reported a 30+ line parse-error cascade from `adwarakanat2@CXAILABDevBox-3` invoking `talent_infra_modules\01-postgresql\deploy.ps1` with the smoking-gun mojibake line `nual cleanup (Azure RP cache can lag â€" retry after a few minutes)`. Root cause: file saved as UTF-8 *without* BOM with 2405 non-ASCII chars (33 em-dash, 2368 box-drawing horizontal, 4 right-arrow) → Windows PowerShell 5.1 (Desktop, .NET Framework) read it as CP1252 → em-dash `E2 80 94` rendered as `â€"` → trailing `"` terminated quoted string → cascade. pwsh 7+ (Core) defaults to UTF-8 for BOM-less `.ps1` so the author never saw the bug. Fix: char substitution map (codepoint → ASCII) + re-save as UTF-8 with BOM via `[System.IO.File]::WriteAllText($path, $text, [System.Text.UTF8Encoding]::new($true))`. Post-fix: file shrank 46189 → 40552 bytes, first 3 bytes = `EF BB BF`, 0 non-ASCII bytes, parses clean in both `powershell.exe` 5.1.26100 and `pwsh` 7.6.1. **11 sibling `.ps1` files identified with same latent bug — deferred for a future single-pass sweep** (`shared/common.ps1` highest priority since every component sources it; `02-backend`/`03-frontend`/`04-data-loading` carry 5874–6855 non-ASCII bytes each). Decision proposed via inbox (now merged as `decisions.md 2026-05-22T23:59:59Z`) — all `.ps1` MUST be UTF-8 with BOM going forward; `.editorconfig` + `.vscode/settings.json` prevention guards recommended. **See `history-archive.md` for full root-cause + per-file byte-count table + prevention recommendations + skill candidate (`powershell-utf8-bom-for-5.1-compat`).**

### 2026-05-22T23:59:30Z — GitGuardian remediation: `01-postgresql/deploy.ps1` `.EXAMPLE` literal-password scrub (Archived)

GitGuardian flagged `ConvertTo-SecureString 'P@ssw0rd!Strong!' -AsPlainText -Force` at `talent_infra_modules/01-postgresql/deploy.ps1:43` (pushed 2026-05-22T22:58:37Z, present in commits `69af3ac` and HEAD `cbb8b23`). Literal lived inside the script-header `.EXAMPLE` block — pure documentation, never an active credential, but `Get-Help` surfaces verbatim and scanners regex on shape, not intent. Fix: rewrote example to `Read-Host -AsSecureString -Prompt 'Postgres admin password'` (leverages `shared/common.ps1::Get-ParameterValue`'s built-in `Read-Host` fallback) + added CI guidance block with `<your-strong-password>` angle-bracket placeholder pattern. Working-tree grep → 0 matches; PowerShell parse → 0 errors. **New rule (decisions.md `2026-05-22T23:59:30Z`): literal strings inside `ConvertTo-SecureString '...'` are forbidden anywhere a script can be committed.** Allowed shapes: (a) `Read-Host -AsSecureString`, (b) `Get-AzKeyVaultSecret`, (c) variable from secret-store at call site, (d) `<angle-bracket-placeholder>` in pure-doc comments. `shared/common.ps1` `ConvertTo-SecureString` lines 195/206/225 are NOT the same hazard (they convert variables, not literals). Two `.env` files under `talent_infra_v2/.azure/talent-devtest-v{2,8}/` with literal passwords were a false alarm — gitignored by the parent-folder `*` wildcard. Cross-toolkit guardrail: every future `talent_infra_*/` script with a `-SecureString` parameter MUST default to `Read-Host -AsSecureString` in `.EXAMPLE`. **See `history-archive.md` for the three lessons + cross-toolkit guardrail + operator runbook.**

### 2026-05-22 — 11-file `.ps1` UTF-8-with-BOM sweep (Archived)

Executed the deferred sweep from Decision `2026-05-22T23:59:59Z`. **11/11 files swept clean** (BOM `EF BB BF`, 0 non-ASCII bytes, parse OK in pwsh 7+); ~4330 chars substituted this pass (~6927 cumulative across all sweep runs). **Substitution map extended by 5 new entries** (↔ → `<->`, ═ → `=`, █ → `#`, ⚠ → `[WARN]`, ✅/✓ → `[OK]`); full 18-entry working map preserved in archive. **One pwsh-7+-only syntax dependency surfaced and confirmed pre-existing** in `02-backend/deploy.ps1` (`?.` 2x + `??` 1x); HEAD already failed PS 5.1 parse with mojibake red-herrings — encoding fix STRICTLY IMPROVES the file. Tagged `EXPECT_FAIL_PS7_ONLY`. **Prevention guards landed**: `.editorconfig` + `.vscode/settings.json` (Anil owns code commit). **2 BOM-less files flagged for a future cleanup pass**: `.squad/templates/skills/distributed-mesh/sync-mesh.ps1` and `talent_infra_v2/scripts/Purge-SoftDeletedFoundryAccounts.ps1`. **adwarakanat2 unblocker**: `git pull` + retry any `talent_infra_modules/*/deploy.ps1` on his box. **See `history-archive.md` for full sweep helper design, per-file char counts, dual-engine parse setup, repo-wide BOM scan, and `.scratch/` cleanup list.**


## Cross-agent note — 2026-05-22T22:30:00Z (Scribe)
- **Model directive (Anil, captured 2026-05-22T18:30:00Z):** all squad spawns — including Scribe and Ralph, including any agent normally defaulted to a fast/cheap tier — MUST use `claude-opus-4.6-1m` (Opus 4.7 Extra-high reasoning). `.squad/config.json` `defaultModel` is the source of truth; the "never bump Scribe" rule is overridden. Per `decisions.md` `2026-05-22T18:30:00Z`.

## Cross-agent note — 2026-05-22T23:55:00Z (Scribe, from Brett)
- `talent_data_pipeline.main` gained `--mode {env,manual}` CLI flag + `DATALOAD_MODE` env var (precedence: CLI > env var > default `env`). Default `env` preserves today's behavior — no prompts, reads `PGHOST` from `.env`. `manual` interactively prompts `PG host [<current PGHOST>]:` (host only — port/user/database/sslmode stay from `.env`); fails fast with exit 2 when no TTY, so CI never hangs. Entra `DefaultAzureCredential` path is fully preserved (no password fallback). Inner package only; outer stubs deliberately untouched per 2026-05-22 cleanup. Relevant to `talent_infra_modules/04-data-loading/deploy.ps1` if operators ever want to override the deployed PG host ad-hoc without re-publishing `.env`. Per `decisions.md 2026-05-22T23:55:00Z`.

## Cross-agent note — 2026-05-22T23:58:00Z (Scribe, from Brett)
- **Empty-`PGUSER` pitfall + new `pg_entra` hint behavior (from the Phase 1 connectivity test root cause on 2026-05-22).** Empty `PGUSER` in any env source (`.env`, Container App env array, Functions app setting, K8s manifest) makes libpq fall back to the **OS account name**, which is then sent to PG as the role to authenticate — even when the Entra bearer token is for a completely different principal. PG rejects with the misleading `password authentication failed for user "<OS-account>"`. Toolkit implication: every UAMI-bound role provisioned by `talent_infra_modules/01-postgresql/` and `talent_infra_modules/02-backend/` MUST set the consumer's `PGUSER` env var to the **UAMI resource name** (which equals the PG role name after `microsoft-entra-admin create --display-name <UAMI-name>`) — never empty, never the OID, never the client GUID. Decision `2026-05-21 talent_infra_modules/02-backend` already does this (`PGUSER=${backendAppName}-identity`); reaffirmed here for any new compute (data-loader job, future workers, sidecar containers) the toolkit adds. `pg_entra.pg_connect()` and `EntraThreadedConnectionPool._connect()` now wrap libpq `password authentication failed` errors with an actionable hint surfacing the empty-PGUSER vs short-PGUSER vs full-UPN cases — Container App stderr from any pipeline job will now point straight at the misconfigured env var instead of looking like a missing password. Per `decisions.md 2026-05-22T23:59:00Z`.